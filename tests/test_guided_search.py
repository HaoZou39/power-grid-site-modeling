"""Guided-search dominance and population size. These tests do not load a scene."""

import numpy as np
import pytest
import torch

from algorithms.common.search import SiteSearch
from algorithms.guided_search.search import GuidedSearch, run_evolution


def test_population_size_stays_fixed_and_infeasible_side_is_removed() -> None:
    def evaluate(raw):
        x = raw[:, 0]
        return torch.stack([x**2, (x + 1.0)**2], dim=1), x.clamp_min(0)

    population = run_evolution(evaluate, popsize=16, generations=12, seed=1, sigma=0.8, n_var=1)
    assert population.genes.shape == (16, 1)
    assert torch.all(population.violation <= 0)


def test_lookup_matches_the_single_site_haul() -> None:
    from algorithms.guided_search.search import haul_objectives
    from modeling.haul_field import build_haul_field, query_route

    dem = np.zeros((6, 6), dtype=np.float64)
    dem[1, 2] = 1.0
    buildable = np.ones((6, 6), dtype=np.uint8)
    segments = np.array([[0.0, 0.5, 5.9, 0.5]], dtype=np.float64)
    site = np.array([[2.5, 3.5]])
    origin = (2.5, 0.5)
    field = build_haul_field(dem, buildable, segments, origin)
    values, blocked = haul_objectives(dem, buildable, segments, origin, site, field=field)
    measured = query_route(field, (2.5, 3.5))
    assert blocked[0] == 0.0
    assert values[0] == pytest.approx(
        [
            measured["road_haul_m"],
            measured["offroad_haul_m"],
            measured["haul_rise_m"],
        ],
        abs=1e-6,
    )

    buildable[2, :] = 0
    blocked_values, blocked_flag = haul_objectives(dem, buildable, segments, None, site)
    assert blocked_flag[0] == 1.0
    assert np.all(blocked_values[0] == 0.0)


def test_one_search_builds_the_haul_field_once(cuda_device, monkeypatch: pytest.MonkeyPatch) -> None:
    from config.project_config import ModelingConfig, GuidedSearchConfig
    from modeling import haul_field as haul_field_module

    calls = {"count": 0}
    real_build = haul_field_module.build_haul_field

    def _counting_build(*args, **kwargs):
        calls["count"] += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(haul_field_module, "build_haul_field", _counting_build)
    config = GuidedSearchConfig(popsize=4, generations=1, seed=1, sigma0=0.3)
    GuidedSearch(config, None).search(_tiny_problem(cuda_device), ModelingConfig(rect_w_m=4.0, rect_h_m=4.0, device="cuda"))
    assert calls["count"] == 1


def test_rescoring_the_search_poses_reproduces_their_rows(cuda_device) -> None:
    from algorithms.guided_search.search import pose_records
    from config.project_config import GuidedSearchConfig, ModelingConfig

    problem = _tiny_problem(cuda_device)
    modeling = ModelingConfig(rect_w_m=4.0, rect_h_m=4.0, device="cuda")
    origin = (2.0, 30.0)
    rows = GuidedSearch(GuidedSearchConfig(popsize=4, generations=1, seed=1, sigma0=0.3), origin).search(problem, modeling).solutions
    again = pose_records(problem, modeling, origin, np.array([[row["x"], row["y"], row["theta"]] for row in rows]))
    for row, other in zip(rows, again):
        for key in ("dem_soft", "road_distance", "demand_distance", "road_haul_m", "offroad_haul_m", "haul_rise_m"):
            assert other[key] == pytest.approx(row[key], rel=1e-5, abs=1e-6), key
        assert other["is_feasible"] == row["is_feasible"]
        assert other["raw_x"] == ""


def _tiny_problem(device):
    from modeling.context import SiteProblemContext

    height = width = 32
    dem = np.zeros((height, width), dtype=np.float64)
    obstacle = np.zeros((height, width), dtype=np.float32)
    segments = np.array([[0.0, 4.5, 31.0, 4.5]], dtype=np.float64)
    demand = np.array([[8.0, 16.0], [24.0, 20.0]], dtype=np.float32)
    return SiteProblemContext(
        dem=dem,
        obstacle_mask=obstacle,
        road_segments=segments,
        dem_tensor=torch.tensor(dem, dtype=torch.float32, device=device)[None, None],
        obstacle_tensor=torch.zeros((1, 1, height, width), dtype=torch.float32, device=device),
        road_segments_tensor=torch.tensor(segments, dtype=torch.float32, device=device),
        road_voronoi_tensor=torch.zeros((height, width), dtype=torch.long, device=device),
        demand_points=demand,
        demand_weights=np.ones(len(demand), dtype=np.float32),
        demand_points_tensor=torch.tensor(demand, dtype=torch.float32, device=device),
        demand_weights_tensor=torch.ones(len(demand), dtype=torch.float32, device=device),
        device=device,
    )


@pytest.mark.parametrize("origin", [None, (2.0, 4.5)])
@pytest.mark.parametrize("include_demand", [False, True])
def test_tensor_evaluation_matches_full_report(cuda_device, origin, include_demand):
    from algorithms.cma_es.cma_es import evaluate_raw_pose_batch
    from config.project_config import ModelingConfig
    from modeling.context import building_hard_mask
    from modeling.evaluator import compute_hard_constraints
    from modeling.haul_field import build_haul_field, query_exact
    from modeling.tensor_evaluator import TensorSiteEvaluator

    problem = _tiny_problem(cuda_device)
    problem.dem[12:19, 14:22] = 3
    problem.dem_tensor[0, 0, 12:19, 14:22] = 3
    problem.obstacle_mask[20:25, 10:18] = 1
    model = ModelingConfig(rect_w_m=4, rect_h_m=4, device="cuda")
    field = build_haul_field(problem.dem, problem.obstacle_mask == 0, problem.road_segments, origin)
    raw = np.random.default_rng(5).normal(size=(31, 3)) * 2
    pose, objectives = evaluate_raw_pose_batch(problem, model, raw.astype(np.float32))
    hard = compute_hard_constraints(problem.dem, building_hard_mask(problem), torch.tensor(pose, device=cuda_device, dtype=torch.float32), 4, 4, cuda_device)
    haul, blocked = query_exact(field, pose[:, :2])
    names = ("dem_soft", "demand_distance") if include_demand else ("dem_soft",)
    expected = np.concatenate((np.stack([objectives[name] for name in names], 1), haul), 1)
    for batch_size in (1, 7, 64):
        evaluator = TensorSiteEvaluator(problem, model, field, include_demand=include_demand, batch_size=batch_size)
        values, violation = evaluator(torch.tensor(raw, device=cuda_device))
        np.testing.assert_allclose(values.cpu(), expected, rtol=2e-6, atol=2e-6)
        np.testing.assert_array_equal(violation.cpu(), hard["constraint_violation"].cpu().numpy() + blocked)


def test_haul_objectives_do_not_mix_length_and_rise() -> None:
    from algorithms.guided_search.search import haul_objectives
    from modeling.haul_field import build_haul_field, query_route

    dem = np.zeros((6, 6), dtype=np.float64)
    dem[1, 2] = 1.0
    buildable = np.ones((6, 6), dtype=np.uint8)
    segments = np.array([[0.0, 0.5, 5.9, 0.5]], dtype=np.float64)
    origin = (2.5, 0.5)
    site = (2.5, 3.5)
    field = build_haul_field(dem, buildable, segments, origin)
    values, blocked = haul_objectives(dem, buildable, segments, origin, np.array([site]), field=field)
    route = query_route(field, site)
    assert blocked[0] == 0.0
    assert values[0, 1] == pytest.approx(route["offroad_haul_m"])
    assert values[0, 2] == pytest.approx(route["haul_rise_m"])
    assert values[0, 1] != values[0, 2]


def test_decision_search_drops_straight_road_distance() -> None:
    from algorithms.guided_search.search import guided_objective_names
    from modeling.haul_field import haul_column_names

    without_origin = guided_objective_names(False)
    with_origin = guided_objective_names(True)
    with_demand = guided_objective_names(False, True)
    assert without_origin == ("dem_soft",) + haul_column_names(False)
    assert with_origin == ("dem_soft",) + haul_column_names(True)
    assert with_demand == ("dem_soft", "demand_distance") + haul_column_names(False)
    assert "demand_distance" not in without_origin
    assert "road_distance" not in haul_column_names(True)
    assert "road_distance" not in without_origin
    assert "road_distance" not in with_origin


def test_generation_sigma_shrinks_only_in_the_last_window() -> None:
    from algorithms.guided_search.search import generation_sigma

    assert generation_sigma(0, 4, 1.0, 2, 0.2) == 1.0
    assert generation_sigma(1, 4, 1.0, 2, 0.2) == 1.0
    assert generation_sigma(2, 4, 1.0, 2, 0.2) == 1.0
    assert generation_sigma(3, 4, 1.0, 2, 0.2) == pytest.approx(0.2)
    assert generation_sigma(1, 4, 1.0, 0, 0.2) == 1.0


def test_front_step_shrinks_only_after_the_front_stalls() -> None:
    from algorithms.guided_search.search import FrontStep

    step = FrontStep(1.0, shrink=0.8, patience=3, floor=0.05)
    for row in (np.array([[1.0, 2.0]]), np.array([[0.5, 2.0]]), np.array([[0.4, 1.5]])):
        step.observe(row)
    assert step.sigma == 1.0
    stalled = np.array([[0.4, 1.5]])
    for _ in range(3):
        step.observe(stalled)
    assert step.sigma == pytest.approx(0.8)
    for _ in range(3):
        step.observe(stalled)
    assert step.sigma == pytest.approx(0.64)


def test_guided_search_is_a_site_search_and_the_base_has_no_search() -> None:
    assert issubclass(GuidedSearch, SiteSearch)
    assert GuidedSearch(object(), (0.0, 0.0)).algorithm_name == "guided_search"
    with pytest.raises(TypeError):
        SiteSearch()
