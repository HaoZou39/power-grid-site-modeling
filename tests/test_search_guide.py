"""Gradient guidance before the evolution stage. The lookup checks stay valid without a full scene."""

import numpy as np
import pytest
import torch

from algorithms.guided_search.guide import (
    best_on_objective,
    guidance_loss,
    guidance_terms,
    local_polish,
    pack_haul_guidance,
    worst_objective_index,
)
from algorithms.guided_search.search import GuidedSearch, haul_objectives, guided_objective_names
from config.project_config import ModelingConfig, GuidedSearchConfig
from modeling.context import SiteProblemContext, soft_obstacle_tensor
from modeling.evaluator import evaluate_site_objectives
from modeling.haul_field import HaulField, build_haul_field
from modeling.pose import decode_raw_pose
from plugins.site_plugin import GuidedSiteConfig


def _problem(device: torch.device, origin: tuple[float, float] | None):
    height = width = 32
    dem = np.zeros((height, width), dtype=np.float64)
    dem[8:12, 8:12] = 1.0
    obstacle = np.zeros((height, width), dtype=np.float32)
    segments = np.array([[0.0, 4.5, 31.0, 4.5]], dtype=np.float64)
    demand = np.array([[8.0, 20.0], [24.0, 18.0]], dtype=np.float32)
    problem = SiteProblemContext(
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
    field = build_haul_field(dem, obstacle == 0, segments, origin)
    modeling = ModelingConfig(rect_w_m=4.0, rect_h_m=4.0, soft_mask_sharpness=8.0, device="cuda")
    return problem, field, modeling


def test_one_guidance_step_does_not_raise_the_loss(cuda_device: torch.device) -> None:
    problem, field, modeling = _problem(cuda_device, (4.0, 4.5))
    packed = pack_haul_guidance(field, cuda_device)
    raw = torch.zeros((2, 3), dtype=torch.float32, device=cuda_device, requires_grad=True)
    before, scales = guidance_loss(problem, modeling, raw, packed, None)
    terms = guidance_terms(problem, modeling, raw, packed, scales)
    assert set(terms) == {"dem_soft", "road_haul_m", "offroad_haul_m", "haul_rise_m", "obstacle_soft"}
    optimizer = torch.optim.Adam([raw], lr=0.01)
    optimizer.zero_grad()
    before.sum().backward()
    optimizer.step()
    after, _scales = guidance_loss(problem, modeling, raw, packed, scales)
    assert float(after.sum().detach()) <= float(before.sum().detach()) + 1e-4


def test_guidance_without_an_origin_omits_road_haul(cuda_device: torch.device) -> None:
    problem, field, modeling = _problem(cuda_device, None)
    packed = pack_haul_guidance(field, cuda_device)
    raw = torch.zeros((1, 3), dtype=torch.float32, device=cuda_device)
    _loss, scales = guidance_loss(problem, modeling, raw, packed, None)
    terms = guidance_terms(problem, modeling, raw, packed, scales)
    assert "road_haul_m" not in terms
    assert "demand_distance" not in terms
    assert "road_distance" not in terms


@pytest.mark.parametrize("initialization", ["gaussian", "uniform", "taguchi"])
def test_guided_search_reports_exact_haul_names(cuda_device: torch.device, initialization: str) -> None:
    problem, _field, modeling = _problem(cuda_device, (4.0, 4.5))
    config = GuidedSearchConfig(popsize=4, initialization=initialization, generations=1, seed=3, sigma0=0.2, guide_steps=1, guide_lr=0.01, refine_sigma=0.05)
    result = GuidedSearch(config, (4.0, 4.5)).search(problem, modeling)
    assert result.objective_names == guided_objective_names(True)
    assert "demand_distance" not in result.objective_names
    assert result.normalization["popsize"] == 4
    assert result.normalization["initialization"] == initialization
    assert result.normalization["generations"] == 1
    assert result.normalization["seed"] == 3
    assert len(result.solutions) == 4
    sites = np.array([[item["x"], item["y"]] for item in result.solutions], dtype=np.float64)
    values, blocked = haul_objectives(problem.dem, problem.obstacle_mask == 0, problem.road_segments, (4.0, 4.5), sites)
    for index, item in enumerate(result.solutions):
        if blocked[index] == 1.0:
            assert item["is_feasible"] is False
            continue
        assert abs(item["offroad_haul_m"] - values[index, 1]) < 1e-4
        assert abs(item["haul_rise_m"] - values[index, 2]) < 1e-4
        assert abs(item["road_haul_m"] - values[index, 0]) < 1e-4


def test_unregistered_haul_name_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from algorithms.guided_search import guide

    monkeypatch.setattr(guide, "haul_column_names", lambda _include: ("not_a_field",))
    grid = np.zeros((2, 2), dtype=np.float64)
    field = HaulField(
        dem=grid,
        buildable=np.ones((2, 2), dtype=np.uint8),
        segments=np.zeros((1, 4), dtype=np.float64),
        origin=None,
        offroad_m=grid,
        access_rise_m=grid,
        road_m=None,
        reachable=np.ones((2, 2), dtype=bool),
        road_cells=np.zeros((2, 2), dtype=bool),
    )
    with pytest.raises(KeyError):
        pack_haul_guidance(field, torch.device("cpu"))


def test_best_neighbor_is_the_smallest_objective() -> None:
    values = np.array([[3.0, 1.0], [0.5, 4.0], [2.0, 0.2]], dtype=np.float64)
    assert best_on_objective(values, 0) == 1
    assert best_on_objective(values, 1) == 2
    assert worst_objective_index(values).tolist() == [0, 1, 0]


def test_disabled_local_search_returns_the_same_genes() -> None:
    genes = np.ones((4, 3), dtype=np.float64)
    updated = local_polish(genes, _fail_evaluate, None, None, GuidedSearchConfig(), None)
    assert GuidedSearchConfig().local_steps == 0
    assert np.allclose(updated, genes)


def test_one_local_gradient_step_does_not_raise_the_emphasized_objective(cuda_device: torch.device) -> None:
    problem, field, modeling = _problem(cuda_device, None)

    def evaluate(raw: np.ndarray):
        pose = decode_raw_pose(torch.tensor(raw, dtype=torch.float32, device=cuda_device), problem.dem.shape, modeling.rect_w_m, modeling.rect_h_m)
        objectives = evaluate_site_objectives(
            problem.dem_tensor,
            soft_obstacle_tensor(problem),
            problem.road_segments_tensor,
            problem.road_voronoi_tensor,
            problem.demand_points_tensor,
            problem.demand_weights_tensor,
            pose,
            modeling.rect_w_m,
            modeling.rect_h_m,
            modeling.soft_mask_sharpness,
        )
        haul, blocked = haul_objectives(problem.dem, problem.obstacle_mask == 0, problem.road_segments, None, pose.detach().cpu().numpy()[:, :2], field)
        names = guided_objective_names(False)
        stacked = np.stack([objectives[name].detach().cpu().numpy() for name in names if name in objectives], axis=1)
        return np.concatenate([stacked, haul], axis=1), blocked

    start = np.zeros((2, 3), dtype=np.float64)
    start[1, 0] = 0.5
    before, _violation = evaluate(start)
    config = GuidedSearchConfig(local_steps=1, local_lr=1e-4, local_lr_end=1e-4, local_mode="gradient", local_beta=0.0)
    updated = local_polish(start, evaluate, problem, modeling, config, field)
    after, _violation = evaluate(updated)
    for index, column in enumerate(worst_objective_index(before)):
        assert after[index, column] <= before[index, column] + 1e-4


def _fail_evaluate(_raw: np.ndarray):
    raise AssertionError("disabled local search must not evaluate")


def test_decision_form_does_not_expose_guidance_knobs() -> None:
    assert "guide_steps" not in GuidedSiteConfig.model_fields
    assert "guide_lr" not in GuidedSiteConfig.model_fields
    assert "refine_sigma" not in GuidedSiteConfig.model_fields
