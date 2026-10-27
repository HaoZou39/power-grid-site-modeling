# -*- coding: utf-8 -*-
"""
dsop/path_planners.py
─────────────────────
Path construction algorithms used to seed the initial population.

Algorithms
----------
create_random_path           random waypoints sorted along the start→end direction
_multiresolution_astar_path  multi-scale A* with terrain cost avoidance
_rrt_path                    RRT with A* fallback
_build_astar_rrt_population  paper-style initialisation: A* seeds + RRT diversity

Internal helpers
----------------
_coarsen_obstacle_grid       downsample obstacle mask to coarse resolution
_build_coarse_terrain_cost_map  average terrain premium per coarse cell
_astar_on_binary_grid        standard 8-connected A* on a bool grid
_decode_coarse_path_to_fine  upscale coarse waypoints to fine-resolution pixels
_edge_is_collision_free      segment clearance check (cached)
_coarse_edge_is_collision_free  segment clearance check on the coarse grid
_sample_free_point           uniform random free cell
"""

import random
import numpy as np
from typing import List, Optional, Sequence

from dsop.constants import (
    MIN_TOWERS, MAX_TOWERS, ASTAR_INIT_CELL_SIZES,
    RRT_CELL_SIZE, RRT_GOAL_BIAS, RRT_MAX_ITERS, RRT_MIN_STEP, RRT_MAX_STEP,
    ASTAR_TERRAIN_COST_SCALE, LINE_SAMPLE_SPACING,
    _LINE_TERRAIN_COST_ARR, _LINE_TERRAIN_BASE_COST, RESIDENT_CODES,
    _neutral_prefer_safety,
)
from dsop.map_cache import _get_cached_map, _COARSE_OBSTACLE_CACHE
from dsop.path_metrics import (
    _encode_path_to_legacy_row, _row_signature,
    _resample_polyline, _dedup_consecutive_points,
    _sample_polyline_cells_sparse, _project_to_valid_cell,
)

# ─────────────────────────────────────────────
# Module-level caches
# ─────────────────────────────────────────────

_COARSE_TERRAIN_COST_CACHE: dict = {}
# A* is deterministic: same (start, end, cell_size) always returns the same path.
_ASTAR_PATH_CACHE: dict = {}
# Segment collision cache — keyed by (x0,y0,x1,y1).
_EDGE_COLLISION_CACHE: dict = {}
_EDGE_COLLISION_CACHE_MAX = 32768


# ─────────────────────────────────────────────
# Random path generator
# ─────────────────────────────────────────────

def create_random_path(start, end, num_towers, grid_map):
    """Generate a random path with ``num_towers - 2`` intermediate waypoints,
    sorted by projection along the start→end direction."""
    h, w   = grid_map.shape
    n_mid  = max(num_towers - 2, 0)

    xs = np.random.randint(0, w, size=n_mid) if n_mid > 0 else np.array([], dtype=int)
    ys = np.random.randint(0, h, size=n_mid) if n_mid > 0 else np.array([], dtype=int)

    pts = [(x, y) for x, y in zip(xs, ys) if grid_map[y, x] not in RESIDENT_CODES]
    while len(pts) < n_mid:
        x = random.randint(0, w - 1)
        y = random.randint(0, h - 1)
        if grid_map[y, x] not in RESIDENT_CODES:
            pts.append((x, y))

    dir_vec = np.array(end, dtype=float) - np.array(start, dtype=float)
    norm_sq = float(dir_vec.dot(dir_vec) + 1e-8)
    t_pts   = [
        (float(np.dot(np.array(p, dtype=float) - np.array(start, dtype=float), dir_vec) / norm_sq), p)
        for p in pts
    ]
    t_pts_sorted = sorted(t_pts, key=lambda x: x[0])

    raw = [start] + [p for _, p in t_pts_sorted] + [end]
    return [(int(x), int(y)) for x, y in raw]


# ─────────────────────────────────────────────
# Terrain cost map (coarse resolution)
# ─────────────────────────────────────────────

def _build_coarse_terrain_cost_map(grid_map, cell_size: int) -> np.ndarray:
    """Float32 (ch, cw) map: average terrain premium per coarse cell × scaling factor.

    Used as per-step extra cost in A* to naturally avoid expensive terrain
    (farmland, developed land) during pathfinding.
    """
    step      = max(int(cell_size), 1)
    cache_key = (int(grid_map.shape[0]), int(grid_map.shape[1]), step)
    cached    = _COARSE_TERRAIN_COST_CACHE.get(cache_key)
    if cached is not None:
        return cached

    h, w = grid_map.shape
    ch   = int(np.ceil(h / step))
    cw   = int(np.ceil(w / step))

    terrains = np.clip(grid_map.astype(np.int32), 0, len(_LINE_TERRAIN_COST_ARR) - 1)
    premiums = np.maximum(
        _LINE_TERRAIN_COST_ARR[terrains].astype(np.float32) - _LINE_TERRAIN_BASE_COST, 0.0
    )

    h_pad  = ch * step
    w_pad  = cw * step
    padded = np.zeros((h_pad, w_pad), dtype=np.float32)
    padded[:h, :w] = premiums
    coarse_premiums = padded.reshape(ch, step, cw, step).mean(axis=(1, 3))

    scale    = ASTAR_TERRAIN_COST_SCALE * float(step) / LINE_SAMPLE_SPACING
    cost_map = (coarse_premiums * scale).astype(np.float32)

    _COARSE_TERRAIN_COST_CACHE[cache_key] = cost_map
    return cost_map


# ─────────────────────────────────────────────
# A* planner
# ─────────────────────────────────────────────

def _astar_on_binary_grid(
    blocked: np.ndarray,
    start_cell: tuple,
    end_cell: tuple,
    terrain_cost_map: Optional[np.ndarray] = None,
) -> Optional[List[tuple]]:
    """Standard 8-connected A* on a boolean obstacle grid, with optional terrain cost."""
    import heapq

    h, w = blocked.shape
    sx, sy = int(start_cell[0]), int(start_cell[1])
    ex, ey = int(end_cell[0]),   int(end_cell[1])
    if not (0 <= sx < w and 0 <= sy < h and 0 <= ex < w and 0 <= ey < h):
        return None

    local_blocked = np.asarray(blocked, dtype=bool).copy()
    local_blocked[sy, sx] = False
    local_blocked[ey, ex] = False

    neighbors = [
        (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
        (-1, -1, np.sqrt(2.0)), (-1, 1, np.sqrt(2.0)),
        (1, -1, np.sqrt(2.0)),  (1, 1, np.sqrt(2.0)),
    ]

    def _heuristic(x: int, y: int) -> float:
        return float(np.hypot(ex - x, ey - y))

    open_heap = [(float(_heuristic(sx, sy)), 0.0, sx, sy)]
    came_from = {}
    g_score   = {(sx, sy): 0.0}
    visited   = set()

    while open_heap:
        _, g_cur, x, y = heapq.heappop(open_heap)
        node = (x, y)
        if node in visited:
            continue
        visited.add(node)
        if node == (ex, ey):
            path = [node]
            while node in came_from:
                node = came_from[node]
                path.append(node)
            path.reverse()
            return path

        for dx, dy, step_cost in neighbors:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if local_blocked[ny, nx]:
                continue
            nxt          = (nx, ny)
            terrain_extra = float(terrain_cost_map[ny, nx]) if terrain_cost_map is not None else 0.0
            tentative     = g_cur + float(step_cost) + terrain_extra
            if tentative + 1e-12 < g_score.get(nxt, float("inf")):
                g_score[nxt]   = tentative
                came_from[nxt] = node
                heapq.heappush(open_heap, (tentative + _heuristic(nx, ny), tentative, nx, ny))
    return None


def _decode_coarse_path_to_fine(
    coarse_path: Sequence[Sequence[float]],
    start: tuple,
    end: tuple,
    grid_map,
    cell_size: int,
) -> List[tuple]:
    """Map coarse-grid waypoints back to fine-pixel coordinates."""
    pts: List[tuple] = [tuple(map(int, start))]
    step = max(int(cell_size), 1)
    for cx, cy in coarse_path[1:-1]:
        x0 = int(cx) * step
        y0 = int(cy) * step
        x1 = min(x0 + step, grid_map.shape[1])
        y1 = min(y0 + step, grid_map.shape[0])
        center = (0.5 * (x0 + max(x1 - 1, x0)), 0.5 * (y0 + max(y1 - 1, y0)))
        pts.append(_project_to_valid_cell(center, grid_map, max_radius=max(3, 2 * step)))
    pts.append(tuple(map(int, end)))
    dedup = _dedup_consecutive_points(pts)
    if len(dedup) < 2:
        return [tuple(map(int, start)), tuple(map(int, end))]
    if len(dedup) > MAX_TOWERS + 2:
        resampled = _resample_polyline(np.asarray(dedup, dtype=float), MAX_TOWERS + 2)
        dedup = [tuple(map(int, np.rint(pt))) for pt in resampled]
        dedup = _dedup_consecutive_points(dedup)
    return dedup


def _multiresolution_astar_path(start: tuple, end: tuple, grid_map, cell_size: int) -> List[tuple]:
    """Run A* at a given coarse resolution and decode back to fine pixels (cached)."""
    global _ASTAR_PATH_CACHE
    cache_key = (tuple(map(int, start)), tuple(map(int, end)), int(cell_size))
    cached    = _ASTAR_PATH_CACHE.get(cache_key)
    if cached is not None:
        return cached

    step             = max(int(cell_size), 1)
    blocked          = _coarsen_obstacle_grid(grid_map, step)
    terrain_cost_map = _build_coarse_terrain_cost_map(grid_map, step)
    start_cell       = (int(start[0]) // step, int(start[1]) // step)
    end_cell         = (int(end[0])   // step, int(end[1])   // step)
    coarse_path      = _astar_on_binary_grid(blocked, start_cell, end_cell, terrain_cost_map=terrain_cost_map)

    if coarse_path is None:
        result = [tuple(map(int, start)), tuple(map(int, end))]
    else:
        result = _decode_coarse_path_to_fine(coarse_path, start, end, grid_map, step)

    _ASTAR_PATH_CACHE[cache_key] = result
    return result


def _coarsen_obstacle_grid(grid_map, cell_size: int) -> np.ndarray:
    """Downsample the obstacle map: a coarse cell is blocked if any fine cell is blocked."""
    step      = max(int(cell_size), 1)
    cache_key = (int(grid_map.shape[0]), int(grid_map.shape[1]), step)
    cached    = _COARSE_OBSTACLE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    h, w = grid_map.shape
    ch   = int(np.ceil(h / step))
    cw   = int(np.ceil(w / step))
    blocked       = np.zeros((ch, cw), dtype=bool)
    resident_codes = np.asarray(RESIDENT_CODES, dtype=int)

    for cy in range(ch):
        y0, y1 = cy * step, min((cy + 1) * step, h)
        for cx in range(cw):
            x0, x1 = cx * step, min((cx + 1) * step, w)
            blocked[cy, cx] = bool(np.isin(grid_map[y0:y1, x0:x1], resident_codes).any())

    _COARSE_OBSTACLE_CACHE[cache_key] = blocked
    return blocked


# ─────────────────────────────────────────────
# Collision checks
# ─────────────────────────────────────────────

def _edge_is_collision_free(p0: Sequence[float], p1: Sequence[float], grid_map) -> bool:
    """Check that the segment p0→p1 does not pass through any resident cell (cached)."""
    global _EDGE_COLLISION_CACHE
    key    = (int(round(float(p0[0]))), int(round(float(p0[1]))),
              int(round(float(p1[0]))), int(round(float(p1[1]))))
    cached = _EDGE_COLLISION_CACHE.get(key)
    if cached is not None:
        return cached

    seg    = np.asarray([p0, p1], dtype=float)
    cells  = _sample_polyline_cells_sparse(seg, grid_map.shape, spacing=1.0)
    result = not np.isin(grid_map[cells[:, 1], cells[:, 0]], RESIDENT_CODES).any()

    if len(_EDGE_COLLISION_CACHE) >= _EDGE_COLLISION_CACHE_MAX:
        evict = list(_EDGE_COLLISION_CACHE.keys())[: _EDGE_COLLISION_CACHE_MAX // 2]
        for k in evict:
            del _EDGE_COLLISION_CACHE[k]
    _EDGE_COLLISION_CACHE[key] = result
    return result


def _coarse_edge_is_collision_free(p0: Sequence[float], p1: Sequence[float], blocked: np.ndarray) -> bool:
    """Segment clearance check on the coarse blocked grid."""
    seg  = np.asarray([p0, p1], dtype=float)
    dist = float(np.linalg.norm(seg[1] - seg[0]))
    n    = max(int(np.ceil(dist * 2.0)), 1)
    xs   = np.rint(np.linspace(seg[0, 0], seg[1, 0], n + 1)).astype(int)
    ys   = np.rint(np.linspace(seg[0, 1], seg[1, 1], n + 1)).astype(int)
    xs   = np.clip(xs, 0, blocked.shape[1] - 1)
    ys   = np.clip(ys, 0, blocked.shape[0] - 1)
    return not blocked[ys, xs].any()


def _sample_free_point(blocked: np.ndarray) -> np.ndarray:
    """Return a random free (non-blocked) point in the coarse grid."""
    h, w = blocked.shape
    for _ in range(200):
        x = random.randint(0, w - 1)
        y = random.randint(0, h - 1)
        if not blocked[y, x]:
            return np.array([float(x), float(y)], dtype=float)
    return np.array([0.0, 0.0], dtype=float)


# ─────────────────────────────────────────────
# RRT planner
# ─────────────────────────────────────────────

def _rrt_path(
    start: tuple,
    end: tuple,
    grid_map,
    max_iters: int = RRT_MAX_ITERS,
    goal_bias: float = RRT_GOAL_BIAS,
    min_step: float = RRT_MIN_STEP,
    max_step: float = RRT_MAX_STEP,
    allow_astar_fallback: bool = True,
) -> List[tuple]:
    """Randomised tree planner.

    ``allow_astar_fallback`` exists for the initialization-strength ablation:
    coarsening can mark the start or goal cell as blocked, in which case the
    default behaviour is to hand off to A*. The ablation needs an A*-free
    population, so it disables the handoff and takes an empty path instead.
    """
    step   = max(int(RRT_CELL_SIZE), 1)
    blocked = _coarsen_obstacle_grid(grid_map, step)
    start_cell = np.asarray([int(start[0]) // step, int(start[1]) // step], dtype=float)
    goal_cell  = np.asarray([int(end[0])   // step, int(end[1])   // step], dtype=float)

    sx, sy = np.rint(start_cell).astype(int)
    gx, gy = np.rint(goal_cell).astype(int)
    sx = int(np.clip(sx, 0, blocked.shape[1] - 1))
    sy = int(np.clip(sy, 0, blocked.shape[0] - 1))
    gx = int(np.clip(gx, 0, blocked.shape[1] - 1))
    gy = int(np.clip(gy, 0, blocked.shape[0] - 1))
    start_cell = np.array([float(sx), float(sy)], dtype=float)
    goal_cell  = np.array([float(gx), float(gy)], dtype=float)

    if blocked[sy, sx] or blocked[gy, gx]:
        if not allow_astar_fallback:
            return []
        return _multiresolution_astar_path(start, end, grid_map, cell_size=max(1, step - 1))

    min_step_cells = max(float(min_step) / step, 1.0)
    max_step_cells = max(float(max_step) / step, min_step_cells + 0.5)

    nodes: List[np.ndarray] = [start_cell]
    parents: List[int] = [-1]

    for _ in range(max(int(max_iters), 1)):
        target   = goal_cell if random.random() < float(goal_bias) else _sample_free_point(blocked)
        node_arr = np.asarray(nodes, dtype=float)
        nearest_idx = int(np.argmin(np.sum((node_arr - target) ** 2, axis=1)))
        nearest = node_arr[nearest_idx]

        direction = target - nearest
        dist      = float(np.linalg.norm(direction))
        if dist <= 1e-8:
            continue

        extend  = float(np.random.uniform(min_step_cells, max_step_cells))
        new_pt  = nearest + direction / dist * min(extend, dist)
        new_pt[0] = np.clip(new_pt[0], 0, blocked.shape[1] - 1)
        new_pt[1] = np.clip(new_pt[1], 0, blocked.shape[0] - 1)
        new_cell  = np.rint(new_pt).astype(int)
        new_cell[0] = int(np.clip(new_cell[0], 0, blocked.shape[1] - 1))
        new_cell[1] = int(np.clip(new_cell[1], 0, blocked.shape[0] - 1))
        new_pt = new_cell.astype(float)

        if blocked[new_cell[1], new_cell[0]]:
            continue
        if np.linalg.norm(new_pt - nearest) < 0.5:
            continue
        if not _coarse_edge_is_collision_free(nearest, new_pt, blocked):
            continue

        nodes.append(new_pt)
        parents.append(nearest_idx)
        new_idx = len(nodes) - 1

        if (
            np.linalg.norm(new_pt - goal_cell) <= max_step_cells
            and _coarse_edge_is_collision_free(new_pt, goal_cell, blocked)
        ):
            nodes.append(goal_cell.copy())
            parents.append(new_idx)
            coarse_path: List[tuple] = []
            cur = len(nodes) - 1
            while cur >= 0:
                p = nodes[cur]
                coarse_path.append((int(round(p[0])), int(round(p[1]))))
                cur = parents[cur]
            coarse_path.reverse()
            dedup = _dedup_consecutive_points(coarse_path)
            if len(dedup) >= 2:
                return _decode_coarse_path_to_fine(dedup, start, end, grid_map, step)
            break

    if not allow_astar_fallback:
        return []
    fallback_step = int(random.choice(ASTAR_INIT_CELL_SIZES))
    return _multiresolution_astar_path(start, end, grid_map, fallback_step)


# ─────────────────────────────────────────────
# Population initialisation
# ─────────────────────────────────────────────

def _build_astar_rrt_population(
    start: tuple,
    end: tuple,
    grid_map,
    pop_size: int,
    include_astar: bool = True,
) -> np.ndarray:
    """Paper-style initialisation: A* seeds + RRT diversity.

    Parameters
    ----------
    include_astar:
        If True (default), inject A* paths at the start.
        Set to False for per-generation global search where A* paths are already
        represented from generation-0 seeding.
    """
    prefer_safety = _neutral_prefer_safety()

    rows: List[np.ndarray] = []
    base_paths: List[List[tuple]] = []
    seen = set()

    def _append_row(row: np.ndarray) -> bool:
        sig = _row_signature(row)
        if sig in seen:
            return False
        seen.add(sig)
        rows.append(np.asarray(row, dtype=float).copy())
        return True

    def _append_path(
        path: Sequence[Sequence[float]],
        num_towers: Optional[int] = None,
        record_base: bool = True,
    ) -> bool:
        row   = _encode_path_to_legacy_row(path, grid_map, num_towers=num_towers, prefer_safety=prefer_safety)
        added = _append_row(row)
        if added and record_base:
            base_paths.append([tuple(map(int, pt)) for pt in path])
        return added

    if include_astar:
        for cell_size in ASTAR_INIT_CELL_SIZES:
            _append_path(_multiresolution_astar_path(start, end, grid_map, cell_size), num_towers=MAX_TOWERS)
    else:
        astar_base = _multiresolution_astar_path(start, end, grid_map, ASTAR_INIT_CELL_SIZES[0])
        base_paths.append([tuple(map(int, pt)) for pt in astar_base])

    rrt_target   = min(max(pop_size - len(rows), 0), max(10, min(18, pop_size // 4)))
    attempts     = 0
    built_rrt    = 0
    max_attempts = max(rrt_target * 5, 32)
    while built_rrt < rrt_target and attempts < max_attempts:
        attempts += 1
        towers = random.randint(MIN_TOWERS, MAX_TOWERS)
        path   = _rrt_path(start, end, grid_map,
                            max_iters=RRT_MAX_ITERS, goal_bias=RRT_GOAL_BIAS,
                            min_step=RRT_MIN_STEP, max_step=RRT_MAX_STEP)
        if _append_path(path, num_towers=towers):
            built_rrt += 1

    if not base_paths:
        base_paths.append(_multiresolution_astar_path(start, end, grid_map, ASTAR_INIT_CELL_SIZES[0]))

    fill_attempts     = 0
    max_fill_attempts = max(pop_size * 20, 200)
    while len(rows) < pop_size and fill_attempts < max_fill_attempts:
        fill_attempts += 1
        towers    = random.randint(MIN_TOWERS, MAX_TOWERS)
        base_path = random.choice(base_paths)
        if _append_path(base_path, num_towers=towers, record_base=False):
            continue

    while len(rows) < pop_size:
        towers    = random.randint(MIN_TOWERS, MAX_TOWERS)
        base_path = random.choice(base_paths)
        row = _encode_path_to_legacy_row(base_path, grid_map, num_towers=towers, prefer_safety=prefer_safety)
        rows.append(np.asarray(row, dtype=float).copy())

    return np.asarray(rows[:pop_size], dtype=float)


def _build_weak_population(
    start: tuple,
    end: tuple,
    grid_map,
    pop_size: int,
    mode: str,
) -> np.ndarray:
    """Generation-0 seeding without any A* anchor, for the init-strength ablation.

    ``rrt_only`` keeps the randomised tree planner but drops the multi-resolution
    A* seeds and the A*-derived fill. ``random`` drops path planning altogether
    and samples interior waypoints uniformly, i.e. the "purely random seeding"
    the paper deliberately avoids. Neither mode touches the per-generation
    operators, so a comparison against the default isolates the seeding.
    """
    prefer_safety = _neutral_prefer_safety()
    # cell_size 1 keeps sampled waypoints in full-resolution pixel coordinates.
    blocked = _coarsen_obstacle_grid(grid_map, 1)

    rows: List[np.ndarray] = []
    rrt_bases: List[List[tuple]] = []
    seen = set()

    def _append(path, towers) -> bool:
        row = _encode_path_to_legacy_row(
            path, grid_map, num_towers=towers, prefer_safety=prefer_safety
        )
        sig = _row_signature(row)
        if sig in seen:
            return False
        seen.add(sig)
        rows.append(np.asarray(row, dtype=float).copy())
        return True

    attempts = 0
    max_attempts = max(pop_size * 20, 400)
    while len(rows) < pop_size and attempts < max_attempts:
        attempts += 1
        towers = random.randint(MIN_TOWERS, MAX_TOWERS)
        if mode == "rrt_only":
            path = _rrt_path(
                start, end, grid_map,
                max_iters=RRT_MAX_ITERS, goal_bias=RRT_GOAL_BIAS,
                min_step=RRT_MIN_STEP, max_step=RRT_MAX_STEP,
                allow_astar_fallback=False,
            )
            if len(path) < 2:
                continue
            if len(rrt_bases) < 8:
                rrt_bases.append([tuple(map(int, pt)) for pt in path])
        else:
            interior = [
                _sample_free_point(blocked).tolist() for _ in range(towers)
            ]
            path = [list(start)] + interior + [list(end)]
        _append(path, towers)

    # RRT can fail to connect within its budget; recycle its own successes
    # rather than falling back to A*, which would defeat the ablation.
    while len(rows) < pop_size:
        towers = random.randint(MIN_TOWERS, MAX_TOWERS)
        if mode == "rrt_only" and rrt_bases:
            path = random.choice(rrt_bases)
        else:
            path = [list(start)] + [
                _sample_free_point(blocked).tolist() for _ in range(towers)
            ] + [list(end)]
        row = _encode_path_to_legacy_row(
            path, grid_map, num_towers=towers, prefer_safety=prefer_safety
        )
        rows.append(np.asarray(row, dtype=float).copy())

    return np.asarray(rows[:pop_size], dtype=float)
