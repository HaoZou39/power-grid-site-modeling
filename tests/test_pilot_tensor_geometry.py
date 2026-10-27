import numpy as np
import pytest
import torch

from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.tensor_evaluator import TensorRouteEvaluator
from modeling.routing.tensor_queries import TensorRouteGeometry
from modeling.routing.tensor_types import TowerBatch
from modeling.routing.types import Route
from test_pilot_tensor_runtime import native_config
from test_routing_context import make_problem


@pytest.mark.parametrize("device", ["cpu", "cuda:0"])
@pytest.mark.parametrize("manual", [False, True])
def test_batch_geometry_matches_scalar_predicates_across_workspaces(device, manual):
    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    landuse = np.zeros((32, 32), dtype=np.int32)
    landuse[12:16, 12:19] = 2
    landuse[21:24, 4:11] = 5
    zones = [[[14, 18], [18, 18], [18, 24], [14, 24]]] if manual else []
    problem = make_problem(landuse=landuse, no_tower_zones=zones, no_cross_zones=zones)
    reference = RouteEvaluator(problem)
    engine = TensorRouteEvaluator(problem, native_config(device))
    rng = np.random.default_rng(42)
    points = rng.uniform(-1, 33, (73, 2))
    points = np.vstack([points, [problem.constraints.tower_radius_m, 8], [14, 8]])
    ends = rng.uniform(-1, 33, points.shape)
    routes = [Route(rng.uniform(0, 32, (int(rng.integers(5)), 2))) for _ in range(61)]
    routes += [Route(np.empty((0, 2))), Route(np.array([[14., 8.]])),
               Route(np.array([[8., 8.], [8.8, 8.]]))]
    expected = [reference.evaluate(route).is_feasible for route in routes]
    batch = TowerBatch.from_routes(routes, device, 6)
    batch.xy[torch.arange(6, device=device)[None, :] >= batch.counts[:, None]] = float("nan")
    try:
        for workspace in [8192, engine.workspace_bytes]:
            geometry = TensorRouteGeometry(engine, workspace)
            np.testing.assert_array_equal(geometry.towers(torch.tensor(points, device=device)).cpu(),
                                          [reference.tower_allowed(p) for p in points])
            np.testing.assert_array_equal(geometry.spans(torch.tensor(points, device=device),
                                                       torch.tensor(ends, device=device)).cpu(),
                                          [reference.span_allowed(a, b) for a, b in zip(points, ends)])
            np.testing.assert_array_equal(geometry.paths(batch).cpu(), expected)
            assert geometry.path_queries == len(routes)
    finally:
        engine.close()


def test_native_evaluator_rejects_nonfinite_active_tower():
    engine = TensorRouteEvaluator(make_problem(), native_config())
    try:
        batch = TowerBatch(torch.full((1, 1, 2), float("nan"), dtype=torch.float64), torch.tensor([1]))
        with pytest.raises(ValueError, match="finite"):
            engine.evaluate_tensors(batch)
    finally:
        engine.close()


def test_geometry_precheck_tiles_paths_and_never_calls_objective_evaluation(monkeypatch):
    engine = TensorRouteEvaluator(make_problem(), native_config())
    geometry = TensorRouteGeometry(engine, 8192)
    batch = TowerBatch.from_routes([Route(np.array([[14., 8.]])) for _ in range(128)], "cpu", 12)
    seen = []
    original = geometry._paths
    def checked(piece):
        seen.append(len(piece.xy))
        return original(piece)
    def forbidden(*args, **kwargs):
        raise AssertionError("geometry precheck invoked a full objective evaluation")
    monkeypatch.setattr(geometry, "_paths", checked)
    monkeypatch.setattr(engine, "evaluate_tensors", forbidden)
    monkeypatch.setattr(geometry.reference, "evaluate", forbidden)
    try:
        assert bool(geometry.paths(batch).all())
        assert len(seen) > 1 and max(seen) < len(batch.xy)
        assert geometry.path_queries == len(batch.xy)
    finally:
        engine.close()


def test_geometry_rejects_lower_precision_and_mismatched_endpoint_shapes():
    engine = TensorRouteEvaluator(make_problem(), native_config())
    geometry = TensorRouteGeometry(engine)
    try:
        with pytest.raises(ValueError, match="float64"):
            geometry.spans(torch.zeros((1, 2)), torch.ones((1, 2)))
        with pytest.raises(ValueError, match="matching"):
            geometry.spans(torch.zeros((1, 2), dtype=torch.float64), torch.ones((2, 2), dtype=torch.float64))
    finally:
        engine.close()
