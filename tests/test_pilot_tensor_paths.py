from dataclasses import replace

import numpy as np
import pytest
import torch

from algorithms.routing.pilot_reference.hybrid import resample_path
from algorithms.routing.pilot_reference.tensor_geometry import PilotTensorGeometry
from modeling.routing.tensor_evaluator import TensorRouteEvaluator
from modeling.routing.tensor_queries import TensorRouteGeometry
from modeling.routing.tensor_types import TowerBatch
from modeling.routing.types import Route
from test_pilot_components import state_for
from test_pilot_tensor_runtime import native_config
from test_routing_context import make_problem


def path_geometry(device="cpu", manual=False, workspace=None):
    landuse = np.zeros((32, 32), dtype=np.int32)
    landuse[12:16, 12:19] = 2
    zones = [[[20, 18], [24, 18], [24, 23], [20, 23]]] if manual else []
    problem = make_problem(landuse=landuse, no_tower_zones=zones)
    problem = replace(problem, constraints=replace(problem.constraints, max_span_m=40.))
    state = state_for(problem)
    engine = TensorRouteEvaluator(problem, native_config(device))
    geometry = PilotTensorGeometry(TensorRouteGeometry(engine, workspace), state.config)
    return state, engine, geometry


@pytest.mark.parametrize("device", ["cpu", "cuda:0"])
@pytest.mark.parametrize("manual", [False, True])
def test_projection_clearance_radius_and_ties_match_cpu(device, manual):
    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    state, engine, geometry = path_geometry(device, manual, 8192)
    points = np.array([[14., 14.], [12.5, 13.], [18., 15.], [20., 20.], [2., 8.], [50., 50.]])
    radii = np.array([4., 6., 5., 7., 4., 2.])
    try:
        tensor = torch.tensor(points, device=device)
        np.testing.assert_array_equal(geometry.clearance(tensor).cpu(), [state.clearance(p) for p in points])
        for bias in [0., state.core.mutation_clearance_bias, state.core.vns_clearance_bias]:
            expected = np.array([state.project(p, r, prefer_clearance=bias) for p, r in zip(points, radii)])
            actual = geometry.project(tensor, torch.tensor(radii, device=device), prefer_clearance=bias)
            np.testing.assert_array_equal(actual.cpu(), expected)
            for source, repaired in zip(points, actual.cpu().numpy()):
                moved = not np.array_equal(source, repaired)
                legal = state.adapter.tower_allowed(repaired)
                assert legal if moved or state.adapter.tower_allowed(source) else not legal
        expected = [state.neighborhood_radius(np.array([state.problem.start, p, state.problem.end]), 1) for p in points]
        np.testing.assert_allclose(geometry.radii(tensor).cpu(), expected, rtol=0, atol=1e-12)
    finally:
        engine.close()


@pytest.mark.parametrize("device", ["cpu", "cuda:0"])
def test_table_projection_matches_the_reference_neighborhood(device):
    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    state, engine, geometry = path_geometry(device, False, 8192)
    rng = np.random.default_rng(11)
    points = rng.uniform([-1, -1], [34, 34], (80, 2))
    points = np.vstack([points, [[14., 14.], [0., 0.], [8.2, 12.4], [31., 31.]]])
    radii = rng.uniform(2., 12., len(points))
    tensor = torch.tensor(points, device=device)
    radius = torch.tensor(radii, device=device)
    try:
        for bias in (0., state.core.mutation_clearance_bias, state.core.vns_clearance_bias):
            reference = geometry._project_reference(tensor, radius, prefer_clearance=bias)
            table = geometry._project_table(tensor, radius, prefer_clearance=bias)
            np.testing.assert_array_equal(table.cpu(), reference.cpu())
    finally:
        engine.close()


@pytest.mark.parametrize("device", ["cpu", "cuda:0"])
def test_resampling_variable_counts_matches_cpu_and_preserves_input(device):
    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    state, engine, geometry = path_geometry(device)
    routes = [Route(np.empty((0, 2))), Route(np.array([[8., 5.], [21., 14.]])),
              Route(np.array([[2., 8.], [8., 8.], [8., 8.], [28., 8.]]))]
    counts = torch.tensor([5, 0, 7], device=device)
    batch = TowerBatch.from_routes(routes, device, 6)
    batch.xy[~batch.valid] = float("nan")
    before = batch.xy.clone()
    try:
        actual = geometry.resample(batch, counts)
        for index, (route, count) in enumerate(zip(routes, counts.cpu().tolist())):
            expected = resample_path(state.adapter.path(route), count + 2)[1:-1]
            np.testing.assert_allclose(actual.routes()[index].towers, expected, rtol=0, atol=1e-10)
        assert torch.equal(torch.isnan(before), torch.isnan(batch.xy))
        assert torch.equal(torch.nan_to_num(before), torch.nan_to_num(batch.xy))
        assert actual.counts.tolist() == [5, 0, 7]
    finally:
        engine.close()


def test_deduplicate_drops_the_tower_that_coincides_with_an_endpoint():
    state, engine, geometry = path_geometry()
    end = state.problem.end
    batch = TowerBatch.from_routes([Route(np.array([[8., 8.], end])), Route(np.array([end]))], "cpu", 4)
    try:
        for route, result in zip([Route(np.array([[8., 8.]])), Route(np.empty((0, 2)))],
                                 geometry.deduplicate(batch).routes()):
            np.testing.assert_array_equal(result.towers, route.towers)
    finally:
        engine.close()


@pytest.mark.parametrize("device", ["cpu", "cuda:0"])
def test_sanitize_projects_and_compacts_like_cpu_with_exact_endpoints(device):
    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    state, engine, geometry = path_geometry(device)
    routes = [Route(np.array([[2., 8.], [8., 8.], [8., 8.], [28., 8.]])),
              Route(np.array([[14., 14.], [20., 10.]])), Route(np.empty((0, 2)))]
    batch = TowerBatch.from_routes(routes, device, 6)
    try:
        actual = geometry.sanitize(batch)
        for route, result in zip(routes, actual.routes()):
            expected = state.adapter.route(state.sanitize(state.adapter.path(route)))
            np.testing.assert_array_equal(result.towers, expected.towers)
            np.testing.assert_array_equal(state.adapter.path(result)[[0, -1]], [state.problem.start, state.problem.end])
    finally:
        engine.close()


def test_batch_merge_handles_different_capacities_without_changing_parents():
    first = TowerBatch.from_routes([Route(np.array([[4., 8.]])), Route(np.empty((0, 2)))], "cpu", 1)
    second = TowerBatch.from_routes([Route(np.array([[6., 9.], [12., 10.]])), Route(np.array([[14., 8.]]))], "cpu", 3)
    result = first.where(torch.tensor([True, False]), second)
    assert result.counts.tolist() == [1, 1]
    assert result.xy.shape == (2, 3, 2)
    np.testing.assert_array_equal(result.routes()[0].towers, [[4., 8.]])
    np.testing.assert_array_equal(result.routes()[1].towers, [[14., 8.]])
    assert first.xy.shape[1] == 1 and second.xy.shape[1] == 3


def test_valid_projection_never_builds_a_clearance_field_and_empty_paths_work():
    state, engine, geometry = path_geometry()
    try:
        points = torch.tensor([[2., 8.], [14., 8.]], dtype=torch.float64)
        assert torch.equal(geometry.project(points, 5.), points)
        assert geometry._clearance is None
        empty = TowerBatch.from_routes([], "cpu", 0)
        assert len(geometry.resample(empty, torch.empty(0, dtype=torch.int64))) == 0
        assert len(geometry.sanitize(empty)) == 0
    finally:
        engine.close()
