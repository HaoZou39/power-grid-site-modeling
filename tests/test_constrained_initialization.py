"""Check the sampled and guided centers without running evolution."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from algorithms.guided_search.guide import guide_initial_population
from algorithms.guided_search.initialization import resolve_initialization_method, sample_initial_population
from config.project_config import load_default_config
from experiments.constraint_mask import compose_constraint_masks, policy_from_form
from modeling.pose import decode_raw_pose


CONCAVE = [(8, 8), (48, 8), (48, 24), (28, 24), (28, 52), (8, 52)]
HOLE = [(14.2, 16.2), (20.8, 16.2), (20.8, 22.8), (14.2, 22.8)]
ISLANDS = [[(4.2, 4.4), (18.7, 4.4), (4.2, 18.7)],
           [(40.1, 40.3), (58.2, 40.3), (58.2, 58.4)]]
TINY = [(30.2, 30.2), (30.7, 30.2), (30.7, 30.7), (30.2, 30.7)]


def _problem(feasible, exclusions, device="cpu"):
    landuse = np.zeros((64, 64), dtype=np.uint8)
    hard, _ = compose_constraint_masks(landuse, exclusions, policy_from_form({}), feasible)
    return SimpleNamespace(
        dem=np.zeros_like(hard), building_obstacle_mask=hard, device=torch.device(device),
        initialization_feasible_zones=tuple(tuple(ring) for ring in feasible),
        initialization_exclusion_zones=tuple(tuple(ring) for ring in exclusions),
    )


def _decoded(raw, problem, model, bounds=None):
    return decode_raw_pose(torch.as_tensor(raw, dtype=torch.float32, device=problem.device),
                           problem.dem.shape, model.rect_w_m, model.rect_h_m, bounds).cpu().numpy()


def _assert_centers(pose, problem):
    cells = pose[:, :2].astype(np.intp)
    assert not problem.building_obstacle_mask[cells[:, 1], cells[:, 0]].any()
    points = [Point(x, y) for x, y in pose[:, :2]]
    if problem.initialization_feasible_zones:
        feasible = unary_union([Polygon(ring) for ring in problem.initialization_feasible_zones])
        assert all(feasible.covers(point) for point in points)
    for ring in problem.initialization_exclusion_zones:
        forbidden = Polygon(ring)
        assert not any(forbidden.covers(point) for point in points)


@pytest.mark.parametrize("method", ["uniform", "taguchi", "gaussian"])
@pytest.mark.parametrize("feasible,exclusions", [([CONCAVE], [HOLE]), (ISLANDS, []),
                                                 ([], [HOLE]), ([TINY], [])])
def test_ten_thousand_centers_stay_inside_the_actual_allowed_domain(method, feasible, exclusions):
    problem = _problem(feasible, exclusions)
    model = replace(load_default_config().modeling, rect_w_m=4, rect_h_m=4)
    config = replace(load_default_config().guided_search, popsize=10000, initialization=method, guide_steps=0)
    raw = guide_initial_population(problem, model, config, None)
    assert raw.shape == (10000, 3) and np.isfinite(raw).all()
    _assert_centers(_decoded(raw, problem, model), problem)
    repeated = guide_initial_population(problem, model, config, None)
    np.testing.assert_array_equal(raw, repeated)
    uniform = guide_initial_population(problem, model, replace(config, initialization="uniform"), None)
    np.testing.assert_array_equal(raw, uniform)


def test_fractional_partition_bounds_and_forbidden_cells():
    problem = _problem([CONCAVE], [HOLE])
    model = replace(load_default_config().modeling, rect_w_m=4, rect_h_m=4)
    bounds = (11.25, 25.6, 14.4, 34.7)
    raw = guide_initial_population(problem, model, replace(load_default_config().guided_search, popsize=100, guide_steps=0), None, bounds)
    pose = _decoded(raw, problem, model, bounds)
    _assert_centers(pose, problem)
    assert np.all((pose[:, 0] >= bounds[0]) & (pose[:, 0] <= bounds[1]))
    assert np.all((pose[:, 1] >= bounds[2]) & (pose[:, 1] <= bounds[3]))


def test_fractional_cells_are_selected_by_area():
    mask = np.zeros((3, 3), dtype=bool)
    mask[0, 0] = mask[1, 1] = True
    bounds = (.75, 2., .75, 2.)
    raw = sample_initial_population(10000, 123, allowed_mask=mask, pose_bounds=bounds)
    xy = .75 + 1.25 * torch.sigmoid(torch.from_numpy(raw[:, :2])).numpy()
    cells = xy.astype(np.intp)
    assert mask[cells[:, 1], cells[:, 0]].all()
    assert abs(np.mean(cells[:, 0] == 0) - .0625 / 1.0625) < .01


def test_empty_domain_fails_instead_of_filling_with_outside_points():
    mask = np.zeros((8, 8), dtype=bool)
    with pytest.raises(ValueError, match="no allowed initialization centers"):
        sample_initial_population(100, 123, allowed_mask=mask, pose_bounds=(1., 6., 1., 6.))
    with pytest.raises(ValueError, match="could not fill initialization"):
        sample_initial_population(100, 123, allowed_mask=~mask, pose_bounds=(1., 6., 1., 6.),
                                  center_filter=lambda raw: np.zeros(len(raw), dtype=bool), max_sampling_batches=2)


def test_constraint_free_rectangle_keeps_explicit_taguchi():
    mask = np.ones((8, 8), dtype=bool)
    bounds = (1., 6., 1., 6.)
    assert resolve_initialization_method("taguchi", mask, bounds) == "taguchi"
    assert resolve_initialization_method("taguchi", mask, bounds, has_regions=True) == "uniform"
    np.testing.assert_array_equal(sample_initial_population(100, 123, "taguchi", allowed_mask=mask, pose_bounds=bounds),
                                  sample_initial_population(100, 123, "taguchi"))


def test_adam_cannot_push_initial_centers_outside_the_domain(monkeypatch):
    from algorithms.guided_search import guide

    problem = _problem(ISLANDS, [])
    model = replace(load_default_config().modeling, rect_w_m=4, rect_h_m=4)
    config = replace(load_default_config().guided_search, popsize=100, guide_steps=8, guide_lr=5)
    calls = []

    def force_outside(problem, modeling, raw, *args):
        _assert_centers(_decoded(raw.detach(), problem, modeling), problem)
        calls.append(len(raw))
        return -1000 * (raw[:, 0] + raw[:, 1]), {}

    monkeypatch.setattr(guide, "pack_haul_guidance", lambda *args: {})
    monkeypatch.setattr(guide, "guidance_scales", lambda *args: {})
    monkeypatch.setattr(guide, "guidance_loss", force_outside)
    raw = guide.guide_initial_population(problem, model, config, None)
    assert calls == [100] * 8
    _assert_centers(_decoded(raw, problem, model), problem)


def test_cuda_decoded_initial_centers_stay_in_polygons(cuda_device):
    problem = _problem(ISLANDS, [], cuda_device)
    model = replace(load_default_config().modeling, rect_w_m=4, rect_h_m=4)
    raw = guide_initial_population(problem, model, replace(load_default_config().guided_search, popsize=10000, guide_steps=0), None)
    assert raw.shape == (10000, 3)
    _assert_centers(_decoded(raw, problem, model), problem)


def test_form_passes_original_polygons_to_initialization(tmp_path, monkeypatch):
    from experiments import scene_store
    from experiments.launch_site_run import constrained_problem
    from experiments.problem_context import context_from_arrays

    mask = np.zeros((64, 64), dtype=np.float32)
    landuse = mask.astype(np.uint8)
    problem = context_from_arrays({"dem": mask, "obstacle_mask": mask, "landuse": landuse,
        "road_segments": np.array([[.1, 1.5, 63.9, 1.5]]),
        "road_voronoi": mask.astype(np.int64), "demand_points": np.array([[32., 32.]])}, "cpu")
    np.save(tmp_path / "landuse_1m.npy", landuse)
    monkeypatch.setattr(scene_store, "load_scene", lambda *args, **kwargs: (problem, {"scene_dir": str(tmp_path)}))
    form = {"feasible_zones": [{"points": CONCAVE}], "exclusion_zones": [{"points": HOLE}]}
    constrained, _ = constrained_problem(form, "cpu")
    assert constrained.initialization_feasible_zones == (tuple(CONCAVE),)
    assert constrained.initialization_exclusion_zones == (tuple(HOLE),)
    model = replace(load_default_config().modeling, rect_w_m=4, rect_h_m=4)
    raw = guide_initial_population(constrained, model, replace(load_default_config().guided_search, guide_steps=0), None)
    _assert_centers(_decoded(raw, constrained, model), constrained)


def test_historical_comparison_rejects_uniform_fallback_before_running(tmp_path, monkeypatch):
    from experiments import compare_initialization as comparison
    from config.project_config import load_project_config

    base = load_project_config("config/default_config.json")
    base = replace(base, modeling=replace(base.modeling, rect_w_m=4, rect_h_m=4))
    monkeypatch.setattr(comparison, "load_project_config", lambda _: base)
    monkeypatch.setattr(comparison, "constrained_problem", lambda *args: (_problem([CONCAVE], []), {}))
    output = tmp_path / "must-not-publish"
    with pytest.raises(ValueError, match="three-method comparison"):
        comparison.compare(comparison.InitializationComparisonConfig(output_dir=output))
    assert not output.exists()
