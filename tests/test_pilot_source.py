from types import SimpleNamespace

import numpy as np

from pilot_reference import original_constants, original_functions, source_manifest


def test_original_source_is_frozen_and_has_no_production_imports():
    manifest = source_manifest()
    assert len(manifest["files"]) == 6
    assert manifest["git_commit"] == "4e9d2c859ff9e1f4caed9a76ad14f08f66d4b3e0"


def test_original_adaptive_radius_has_hand_calculated_limits():
    radius = original_functions("path_operators.py", ["_adaptive_neighborhood_radius"], {
        "_path_internal_point_clearances": lambda _: np.array([0., 5., 100.])})["_adaptive_neighborhood_radius"]
    assert [radius([0] * 5, i) for i in [1, 2, 3]] == [3., 6.5, 14.]


def test_original_candidate_comparison_preserves_nondominated_tradeoffs_as_rejections():
    better = original_functions("preference.py", ["_candidate_is_better"], {
        "PreferenceGuidance": object, "_utility_model_scores": lambda *a, **kw: None})["_candidate_is_better"]
    assert better([3., 10., 2., 5.], [0.], [2., 9., 1., 4.], [0.])
    assert not better([3., 10., 2., 5.], [0.], [2., 11., 1., 4.], [0.])
    assert better([3.] * 4, [2.], [100.] * 4, [1.])
    assert not better([3.] * 4, [0.], [1.] * 4, [1.])


def test_original_rrt_goal_bias_extensions_and_backtracking():
    constants = original_constants()
    class NumpyTape:
        random = SimpleNamespace(uniform=lambda left, right: 2.)
        def __getattr__(self, name):
            return getattr(np, name)
    bindings = {**constants, "np": NumpyTape(),
        "random": SimpleNamespace(random=lambda: 0.),
        "_coarsen_obstacle_grid": lambda grid, step: np.zeros((16, 32), dtype=bool),
        "_coarse_edge_is_collision_free": lambda *a: True,
        "_dedup_consecutive_points": lambda pts: pts,
        "_decode_coarse_path_to_fine": lambda path, start, end, grid, step: [(x * step, y * step) for x, y in path],
        "_multiresolution_astar_path": lambda *a, **kw: (_ for _ in ()).throw(AssertionError("unexpected A* fallback"))}
    rrt = original_functions("path_planners.py", ["_rrt_path"], bindings)["_rrt_path"]
    actual = rrt((0, 0), (120, 0), np.zeros((96, 192)), max_iters=20, goal_bias=1., min_step=12., max_step=12.)
    assert actual == [(i * 12, 0) for i in range(11)]


def test_original_rrt_blocked_endpoint_fallback_is_distinguishable_from_success():
    bindings = {**original_constants(), "random": SimpleNamespace(),
        "_coarsen_obstacle_grid": lambda *a: np.ones((4, 4), dtype=bool),
        "_multiresolution_astar_path": lambda *a, **kw: ["A* fallback"]}
    rrt = original_functions("path_planners.py", ["_rrt_path"], bindings)["_rrt_path"]
    assert rrt((0, 0), (12, 12), None) == ["A* fallback"]
    assert rrt((0, 0), (12, 12), None, allow_astar_fallback=False) == []


def test_original_crossover_checks_nearest_pairs_in_both_directions():
    a = [(0, 0), (2, 0), (4, 0), (6, 0)]
    b = [(0, 0), (2, 1), (4, 1), (6, 0)]
    trace = []
    def metrics(path, grid):
        trace.append(list(path))
        return [1.] * 4, [0.]
    namespace = original_functions("preference.py", ["_candidate_is_better"], {
        "PreferenceGuidance": object, "_utility_model_scores": lambda *a, **kw: None})
    namespace.update(original_constants())
    namespace.update(PreferenceGuidance=object, compute_path_metrics=metrics,
        _neutral_prefer_safety=lambda: 0., _edge_is_collision_free=lambda *a: True,
        _path_is_collision_free=lambda *a: True, _sanitize_path_candidate=lambda path, *a, **kw: path)
    operators = original_functions("path_operators.py", ["_select_better_path_bundle", "_path_crossover_operator"], namespace)
    path, _, _ = operators["_path_crossover_operator"](a, b, None)
    assert path == a
    assert trace == [a, b,
        [(0, 0), (2, 0), (2, 1), (4, 1), (6, 0)],
        [(0, 0), (2, 1), (2, 0), (4, 0), (6, 0)],
        [(0, 0), (2, 0), (4, 0), (4, 1), (6, 0)],
        [(0, 0), (2, 1), (4, 1), (4, 0), (6, 0)]]
