"""Guided-search dominance and population size. These tests do not load a scene."""

import numpy as np
import pytest
import torch

from algorithms.common.search import SiteSearch
from algorithms.guided_search.search import Individual, GuidedSearch, dominates, run_evolution


def _person(objectives: list[float], violation: float) -> Individual:
    return Individual(np.zeros(1), np.asarray(objectives, dtype=np.float64), violation)


def test_feasible_pose_dominates_an_infeasible_pose() -> None:
    feasible = _person([10.0, 10.0], 0.0)
    infeasible = _person([0.0, 0.0], 4.0)
    assert dominates(feasible, infeasible)
    assert not dominates(infeasible, feasible)


def test_tradeoff_poses_do_not_dominate_each_other() -> None:
    left = _person([1.0, 3.0], 0.0)
    right = _person([3.0, 1.0], 0.0)
    assert not dominates(left, right)
    assert not dominates(right, left)


def test_smaller_violation_wins_when_both_are_infeasible() -> None:
    milder = _person([9.0, 9.0], 1.0)
    worse = _person([0.0, 0.0], 5.0)
    assert dominates(milder, worse)


def test_population_size_stays_fixed_and_infeasible_side_is_removed() -> None:
    def evaluate(raw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        x = raw[:, 0]
        objectives = np.stack([x**2, (x + 1.0) ** 2], axis=1)
        return objectives, np.maximum(x, 0.0)

    population = run_evolution(evaluate, popsize=16, generations=12, seed=1, sigma=0.8, n_var=1)
    assert len(population) == 16
    assert all(person.violation <= 0.0 for person in population)


def test_lookup_matches_the_single_site_haul() -> None:
    from algorithms.guided_search.search import haul_objectives
    from modeling.construction_cost import TerrainHaulCost

    dem = np.zeros((6, 6), dtype=np.float64)
    dem[1, 2] = 1.0
    buildable = np.ones((6, 6), dtype=np.uint8)
    segments = np.array([[0.0, 0.5, 5.9, 0.5]], dtype=np.float64)
    site = np.array([[2.5, 3.5]])
    origin = (2.5, 0.5)
    values, blocked = haul_objectives(dem, buildable, segments, origin, site)
    measured = TerrainHaulCost().measures(origin, (2.5, 3.5), segments, dem=dem, buildable=buildable)
    assert blocked[0] == 0.0
    assert abs(values[0, 0] - measured["road_m"]) < 1e-6
    assert abs(values[0, 1] - measured["offroad_m"]) < 1e-6
    assert abs(values[0, 2] - measured["access_rise_m"]) < 1e-6

    buildable[2, :] = 0
    blocked_values, blocked_flag = haul_objectives(dem, buildable, segments, None, site)
    assert blocked_flag[0] == 1.0
    assert np.all(blocked_values[0] == 0.0)


def test_one_search_builds_the_haul_field_once(cuda_device, monkeypatch: pytest.MonkeyPatch) -> None:
    from config.project_config import ModelingConfig, GuidedSearchConfig
    from modeling import haul_field as haul_field_module
    from modeling.context import SiteProblemContext

    calls = {"count": 0}
    real_build = haul_field_module.build_haul_field

    def _counting_build(*args, **kwargs):
        calls["count"] += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(haul_field_module, "build_haul_field", _counting_build)
    height = width = 32
    dem = np.zeros((height, width), dtype=np.float64)
    obstacle = np.zeros((height, width), dtype=np.float32)
    segments = np.array([[0.0, 4.5, 31.0, 4.5]], dtype=np.float64)
    demand = np.array([[8.0, 16.0], [24.0, 20.0]], dtype=np.float32)
    problem = SiteProblemContext(
        dem=dem,
        obstacle_mask=obstacle,
        road_segments=segments,
        dem_tensor=torch.tensor(dem, dtype=torch.float32, device=cuda_device)[None, None],
        obstacle_tensor=torch.zeros((1, 1, height, width), dtype=torch.float32, device=cuda_device),
        road_segments_tensor=torch.tensor(segments, dtype=torch.float32, device=cuda_device),
        road_voronoi_tensor=torch.zeros((height, width), dtype=torch.long, device=cuda_device),
        demand_points=demand,
        demand_weights=np.ones(len(demand), dtype=np.float32),
        demand_points_tensor=torch.tensor(demand, dtype=torch.float32, device=cuda_device),
        demand_weights_tensor=torch.ones(len(demand), dtype=torch.float32, device=cuda_device),
        device=cuda_device,
    )
    config = GuidedSearchConfig(popsize=4, generations=1, seed=1, sigma0=0.3)
    GuidedSearch(config, None).search(problem, ModelingConfig(rect_w_m=4.0, rect_h_m=4.0, device="cuda"))
    assert calls["count"] == 1


def test_haul_objectives_do_not_mix_length_and_rise() -> None:
    from algorithms.guided_search.search import haul_objectives

    dem = np.zeros((6, 6), dtype=np.float64)
    dem[1, 2] = 1.0
    buildable = np.ones((6, 6), dtype=np.uint8)
    segments = np.array([[0.0, 0.5, 5.9, 0.5]], dtype=np.float64)
    values, blocked = haul_objectives(dem, buildable, segments, (2.5, 0.5), np.array([[2.5, 3.5]]))
    assert blocked[0] == 0.0
    assert abs(values[0, 1] - 3.0) < 1e-6
    assert values[0, 2] > 0.0


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
