"""PILOT A*/RRT construction and variable-count fill without legacy chromosomes."""

import math
from collections import Counter

import numpy as np
from algorithms.common.nsga2 import Individual, select_population
from modeling.routing.compiled_evaluator import CompiledRouteEvaluator
from modeling.routing.geometry import DISTANCE_TOL_M
from ..repair import repair_reference_spans
from .astar import metric_astar
from .rrt import compiled_rrt_path, corridor_extension_allowed, rrt_path


# Tensor evolution expands these seeds on the device. Keep this orchestration
# limit out of the research configuration: it controls the CPU-to-device handoff.
TENSOR_INITIAL_SEED_CAP = 48


def resample_path(points, count):
    points = np.asarray(points, dtype=float)
    if len(points) == 0:
        return np.zeros((0, 2))
    if len(points) == 1 or count <= 1:
        return np.repeat(points[:1], max(int(count), 1), axis=0)
    cumulative = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    if cumulative[-1] <= DISTANCE_TOL_M:
        return np.repeat(points[:1], count, axis=0)
    targets = np.linspace(0., cumulative[-1], int(count))
    return np.column_stack([np.interp(targets, cumulative, points[:, axis]) for axis in (0, 1)])


def sample_route(path, count, state):
    radius = state.core.resample_radius * state.scale
    points = resample_path(path, count + 2)
    points[1:-1] = state.project_many(points[1:-1], radius)
    points[0], points[-1] = state.problem.start, state.problem.end
    dedup = points[np.r_[True, np.linalg.norm(np.diff(points, axis=0), axis=1) > DISTANCE_TOL_M]]
    if len(dedup) != count + 2:
        points = resample_path(dedup, count + 2)
        points[1:-1] = state.project_many(points[1:-1], radius)
        points[0], points[-1] = state.problem.start, state.problem.end
    else:
        points = dedup
    return repair_reference_spans(state.adapter.route(points), state.evaluator, state.config, state.adapter.numpy_rng)


def rrt_seed(state, lower, *, corridor=False, reuse=True):
    if reuse:
        cached = state.take_planner_seed(corridor=corridor)
        if cached is not None:
            return cached
    cfg, problem = state.config.pilot, state.problem
    upper = np.array([problem.frame.width, problem.frame.height], dtype=float)
    def sample_free():
        for _ in range(cfg.rrt_free_sample_attempts):
            point = np.array([state.adapter.python_rng.uniform(0, size) for size in upper])
            if state.adapter.tower_allowed(point):
                return point
        return None
    state.count("rrt_attempts")
    stats = {"rrt_iterations": 0}
    if (type(state.evaluator) is CompiledRouteEvaluator and not problem.no_tower_zones
            and (corridor or not problem.no_cross_zones)):
        path = compiled_rrt_path(state.adapter, upper, max_iters=cfg.rrt_iterations_per_span * (lower + 1),
            goal_bias=cfg.rrt_goal_bias, min_step=cfg.rrt_min_step_ratio * problem.constraints.max_span_m,
            max_step=problem.constraints.max_span_m, free_attempts=cfg.rrt_free_sample_attempts,
            corridor=corridor, checkpoint=state.checkpoint, stats=stats)
    else:
        path = rrt_path(problem.start, problem.end, upper,
            max_iters=cfg.rrt_iterations_per_span * (lower + 1), goal_bias=cfg.rrt_goal_bias,
            min_step=cfg.rrt_min_step_ratio * problem.constraints.max_span_m, max_step=problem.constraints.max_span_m,
            python_rng=state.adapter.python_rng, numpy_rng=state.adapter.numpy_rng,
            sample_free=sample_free, extension_allowed=(
                (lambda path, target, fixed_endpoint=False: corridor_extension_allowed(
                    state.evaluator, path, target, fixed_endpoint=fixed_endpoint))
                if corridor else state.adapter.extension_allowed),
            checkpoint=state.checkpoint, stats=stats)
    state.count("rrt_iterations", stats["rrt_iterations"])
    if path is not None:
        state.count("rrt_successes")
        state.store_planner_seed(path, corridor=corridor)
        if reuse:
            return state.take_planner_seed(corridor=corridor)
    return path


def build_population(state, bounds, window, target, *, include_astar, include_rrt, fallback=(),
                     expand_initial=False, anchor_for_fill=False, category="initial", corridor=None):
    def record_count(name, amount=1):
        state.count(name if category == "initial" else "global_" + name, amount)
    use_corridor = (category == "initial") if corridor is None else bool(corridor)
    rows, bases, seen, provenance = [], [], set(), []
    sources = Counter()
    rng = state.adapter.python_rng

    def append(path, count, source, *, record_base=True):
        if not window.remaining:
            return False
        route = sample_route(path, count, state)
        key = route.towers.tobytes()
        if key in seen:
            record_count("initial_duplicate_candidates")
            return False
        candidate = state.score(route, window)
        if candidate is None:
            return False
        state.mark(candidate, category + "_" + source)
        seen.add(key)
        if expand_initial and candidate.evaluation.is_feasible:
            bounds.upper = max(bounds.upper, len(route.towers))
        if not bounds.lower <= len(route.towers) <= bounds.upper:
            record_count("initial_out_of_range_trials")
            return False
        rows.append(candidate)
        sources[source] += 1
        provenance.append((source, count))
        if record_base:
            bases.append(np.asarray(path).copy())
        if candidate.evaluation.is_feasible:
            record_count("hybrid_unique_feasible")
        return True

    initial_upper = bounds.upper
    if include_astar:
        for multiplier in state.core.astar_scales:
            if not window.remaining or len(rows) >= target:
                break
            path = metric_astar(state, state.config.navigation_step_m * multiplier, corridor=use_corridor)
            if path is not None:
                append(path, initial_upper, "astar")
    elif anchor_for_fill and window.remaining:
        path = metric_astar(state, state.config.navigation_step_m * state.core.astar_scales[0])
        if path is not None:
            bases.append(path)

    cfg = state.config.pilot
    rrt_target = min(max(target - len(rows), 0), max(cfg.rrt_seed_min,
                     min(cfg.rrt_seed_max, target // cfg.rrt_population_divisor))) if include_rrt else 0
    attempts, built = 0, 0
    while built < rrt_target and attempts < max(rrt_target * cfg.rrt_attempt_factor, cfg.rrt_min_attempts) and window.remaining:
        state.checkpoint("正在生成混合初始化 RRT 种子")
        attempts += 1
        count = rng.randint(bounds.lower, bounds.upper)
        if category == "initial":
            path = rrt_seed(state, bounds.lower, corridor=use_corridor, reuse=False)
        else:
            path = rrt_seed(state, bounds.lower, corridor=use_corridor)
        if path is not None and append(path, count, "rrt"):
            built += 1
    record_count("rrt_appended_candidates", built)
    if not bases:
        bases.extend(state.adapter.path(c.route) for c in fallback)
    fill = 0
    while len(rows) < target and bases and window.remaining and fill < max(target * state.core.fill_attempt_factor,
                                                                         state.core.fill_min_attempts):
        state.checkpoint("正在按不同塔数填充混合种群")
        fill += 1
        count = rng.randint(bounds.lower, bounds.upper)
        path = rng.choice(bases)
        append(path, count, "fill", record_base=False)
    record_count("hybrid_fill_attempts", fill)
    if not rows:
        rows = [c for c in fallback if bounds.lower <= len(c.route.towers) <= bounds.upper][:target]
        provenance = [("reference_fallback", len(c.route.towers)) for c in rows]
        sources["reference_fallback"] += len(rows)
    if not rows:
        raise RuntimeError("PILOT initialization has no fully evaluated candidate")
    while len(rows) < target:
        # Preserve bounded random-count/source draws, but reuse only completed states.
        rng.randint(bounds.lower, bounds.upper)
        if bases:
            rng.choice(bases)
        candidate = rows[len(rows) % len(provenance)]
        rows.append(candidate)
        record_count("initial_reused_slots")
        sources["evaluated_reuse"] += 1
    if category == "initial":
        state.diagnostics["initial_sources"] = dict(sources)
    else:
        total = state.diagnostics.setdefault("global_sources", {})
        for name, value in sources.items():
            total[name] = total.get(name, 0) + value
    return rows[:target]


def initialize_hybrid(initial, state, *, corridor=True, target=None):
    target = state.config.popsize if target is None else min(state.config.popsize, target)
    window = state.budget.window("initialization", max(0, state.config.pilot.initialization_budget_factor * state.config.popsize
                                                      - len(state.budget.records)))
    fallback = [state.lookup(state.adapter.route(np.vstack([state.problem.start, p.genes, state.problem.end])))
                for p in initial.population]
    rows = build_population(state, initial.bounds, window, target,
        include_astar="astar" in state.config.pilot.enabled_mechanisms,
        include_rrt="rrt" in state.config.pilot.enabled_mechanisms, fallback=fallback, expand_initial=True,
        corridor=corridor)
    initial.bounds.initial_upper = initial.bounds.upper
    initial.population = select_population([Individual(c.route.towers, c.evaluation.objectives, c.evaluation.violation)
                                            for c in rows], target)
    initial.candidates = [(c.route, c.evaluation) for c in rows]
    state.diagnostics.update(initial_seed_population_size=len(rows),
        initial_seed_unique_population=len({c.key for c in rows}),
        initial_population_size=len(rows), initial_unique_population=len({c.key for c in rows}))
