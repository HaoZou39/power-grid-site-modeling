"""Shared tensor constrained ranking; tiled comparisons never change dominance."""

import torch

TILE_PAIRS = 1 << 26
DENSE_RANK_MAX = 2048

def pareto_dominance(objectives: torch.Tensor, rows: torch.Tensor | None = None) -> torch.Tensor:
    """`[len(rows), N]`：rows 中的个体是否支配每一个个体。rows 缺省为全部。"""
    left = objectives if rows is None else objectives[rows]
    not_worse = torch.ones((len(left), len(objectives)), dtype=torch.bool, device=objectives.device)
    better = torch.zeros_like(not_worse)
    for column in range(objectives.shape[1]):
        values = objectives[:, column]
        not_worse &= left[:, column, None] <= values[None, :]
        better |= left[:, column, None] < values[None, :]
    return not_worse & better


def dominance_matrix(objectives: torch.Tensor, violation: torch.Tensor) -> torch.Tensor:
    """Rows dominate columns; equal positive violations still compare objectives."""
    cv = violation.clamp_min(0)
    return (cv[:, None] < cv[None, :]) | ((cv[:, None] == cv[None, :]) & pareto_dominance(objectives))


def nondominated_rank(objectives: torch.Tensor, violation: torch.Tensor, *, tile_pairs: int = TILE_PAIRS) -> torch.Tensor:
    # Different CV groups are totally ordered. Peel all groups concurrently,
    # then offset their local fronts, avoiding one GPU sync per distinct CV.
    if not len(violation):
        return torch.empty(0, dtype=torch.long, device=violation.device)
    cv = violation.clamp_min(0)
    if len(cv) <= DENSE_RANK_MAX and tile_pairs >= len(cv) * len(cv):
        return _dense_nondominated_rank(objectives, cv)
    order = torch.argsort(cv, stable=True)
    ordered_cv = cv[order]
    starts = torch.cat((torch.ones(1, device=cv.device, dtype=torch.bool), ordered_cv[1:] != ordered_cv[:-1]))
    group = torch.empty_like(order)
    group[order] = starts.long().cumsum(0) - 1
    # Each individual is compared as a dominator twice: once for the initial
    # in-degree and once when its front is peeled, in row tiles of TILE_PAIRS.
    degree = _dominated_counts(objectives, group, torch.arange(len(cv), device=cv.device), tile_pairs)
    front = degree == 0
    rank = torch.zeros_like(order)
    level = 0
    while bool(front.any()):
        members = front.nonzero().squeeze(1)
        rank[members] = level
        degree -= _dominated_counts(objectives, group, members, tile_pairs)
        degree[members] = -1
        front = degree == 0
        level += 1
    heights = torch.zeros_like(order).scatter_reduce_(0, group, rank + 1, reduce="amax")
    offsets = heights.cumsum(0) - heights
    return rank + offsets[group]


def _dense_nondominated_rank(objectives: torch.Tensor, cv: torch.Tensor) -> torch.Tensor:
    """Peel all CV groups from one exact dominance matrix.

    The tiled implementation recomputes the same pairwise comparisons once
    for the initial degree and again for every front.  For bounded populations
    the dense matrix is cheaper and keeps the constrained group ordering exact.
    """
    order = torch.argsort(cv, stable=True)
    ordered_cv = cv[order]
    starts = torch.cat((torch.ones(1, device=cv.device, dtype=torch.bool),
                        ordered_cv[1:] != ordered_cv[:-1]))
    group = torch.empty_like(order)
    group[order] = starts.long().cumsum(0) - 1
    same_group = group[:, None] == group[None, :]
    dominates = pareto_dominance(objectives) & same_group
    degree = dominates.sum(0, dtype=torch.int64)
    local_rank = torch.zeros_like(order)
    levels = torch.zeros(int(group.max()) + 1, device=cv.device, dtype=torch.long)
    front = degree == 0
    while bool(front.any()):
        members = front.nonzero().flatten()
        local_rank[members] = levels[group[members]]
        touched = torch.zeros_like(levels)
        touched.scatter_(0, group[members], 1)
        levels += touched
        degree -= dominates[members].sum(0, dtype=torch.int64)
        degree[members] = -1
        front = degree == 0
    offsets = levels.cumsum(0) - levels
    return local_rank + offsets[group]


def _dominated_counts(objectives: torch.Tensor, group: torch.Tensor, rows: torch.Tensor, tile_pairs: int) -> torch.Tensor:
    """How many of `rows` dominate each individual within the same CV group."""
    counts = torch.zeros(len(objectives), dtype=torch.int64, device=objectives.device)
    step = max(1, tile_pairs // len(objectives))
    for start in range(0, len(rows), step):
        tile = rows[start:start + step]
        counts += (pareto_dominance(objectives, tile) & (group[tile, None] == group[None, :])).sum(0)
    return counts


def crowding_distance(objectives: torch.Tensor, rank: torch.Tensor) -> torch.Tensor:
    """Stable objective sorting within every front, including zero-span boundaries."""
    count, width = objectives.shape
    if not count:
        return objectives.new_empty(0)
    order = torch.argsort(objectives, dim=0, stable=True)
    order = order.gather(0, torch.argsort(rank[order], dim=0, stable=True))
    levels = rank[order]
    positions = torch.arange(count, device=objectives.device)[:, None].expand(-1, width)
    first = torch.cat((torch.ones((1, width), device=rank.device, dtype=torch.bool), levels[1:] != levels[:-1]))
    last = torch.cat((levels[:-1] != levels[1:], torch.ones((1, width), device=rank.device, dtype=torch.bool)))
    starts = torch.where(first, positions, 0).cummax(0).values
    ends = torch.where(last, positions, count - 1).flip((0,)).cummin(0).values.flip((0,))
    values = objectives.gather(0, order)
    span = values.gather(0, ends) - values.gather(0, starts)
    previous = values.gather(0, (positions - 1).clamp_min(0))
    following = values.gather(0, (positions + 1).clamp_max(count - 1))
    distances = torch.where((torch.isfinite(span) & (span > 0)), (following - previous) / torch.where((torch.isfinite(span) & (span > 0)), span, 1), 0)
    distances = torch.where(first | last, torch.inf, distances)
    return torch.zeros_like(objectives).scatter_(0, order, distances).sum(1)


def tournament(rank: torch.Tensor, crowding: torch.Tensor, pairs: torch.Tensor) -> torch.Tensor:
    left, right = pairs[..., 0], pairs[..., 1]
    wins = (rank[left] < rank[right]) | ((rank[left] == rank[right]) & (crowding[left] > crowding[right]))
    return torch.where(wins, left, right)
