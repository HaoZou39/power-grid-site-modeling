from dataclasses import replace

import numpy as np
import pytest
import torch

from algorithms.routing.pilot_reference.tensor_geometry import PilotTensorGeometry
from algorithms.routing.pilot_reference.tensor_repair import repair_towers, repair_spans, sample_routes
from algorithms.routing.pilot_reference.hybrid import sample_route
from algorithms.routing.repair import repair_towers as cpu_towers, repair_reference_spans as cpu_spans
from modeling.routing.tensor_evaluator import TensorRouteEvaluator
from modeling.routing.tensor_queries import TensorRouteGeometry
from modeling.routing.tensor_types import TowerBatch
from modeling.routing.types import Route
from test_pilot_components import state_for
from test_pilot_tensor_runtime import native_config
from test_routing_context import make_problem


def repair_geometry(device, *, span=40., attempts=None, water=False):
    landuse = np.zeros((32, 32), dtype=np.int32)
    if water:
        landuse[6:10, 12:18] = 5
    else:
        landuse[12:16, 12:19] = 2
    problem = make_problem(landuse=landuse)
    problem = replace(problem, constraints=replace(problem.constraints, max_span_m=span))
    state = state_for(problem)
    if attempts is not None:
        state.config = replace(state.config, repair_attempts=attempts)
    engine = TensorRouteEvaluator(problem, native_config(device))
    geometry = PilotTensorGeometry(TensorRouteGeometry(engine), state.config)
    return state, engine, geometry


class AlternatingNoise:
    def __init__(self, vertical):
        self.vertical, self.calls = vertical, 0

    def normal(self, mean, sigma, size):
        result = np.array([0., 0. if self.calls % 2 == 0 else self.vertical]) * sigma
        self.calls += 1
        return result


@pytest.mark.parametrize("device", ["cpu", "cuda:0"])
def test_point_repair_matches_first_valid_cpu_proposal_without_random_walk(device):
    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    state, engine, geometry = repair_geometry(device)
    routes = [Route(np.array([[14., 14.], [16., 14.]])), Route(np.array([[14., 8.]]))]
    batch = TowerBatch.from_routes(routes, device, 3)
    noise = torch.zeros((state.config.repair_attempts, len(batch), 3, 2), device=device, dtype=torch.float64)
    noise[1, :, :, 1] = .5
    expected = [cpu_towers(route, state.evaluator, state.config, AlternatingNoise(.5)) for route in routes]
    try:
        result = repair_towers(batch, geometry, torch.Generator(device=device).manual_seed(1), noise=noise)
        for a, b in zip(result.routes(), expected):
            np.testing.assert_array_equal(a.towers, b.towers)
        np.testing.assert_array_equal(batch.routes()[0].towers, routes[0].towers)
    finally:
        geometry.close()
        engine.close()


@pytest.mark.parametrize("device", ["cpu", "cuda:0"])
@pytest.mark.parametrize("attempts", [2, 6])
def test_longest_span_repair_order_and_effort_match_cpu(device, attempts):
    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    state, engine, geometry = repair_geometry(device, span=10., attempts=attempts, water=True)
    route = Route(np.empty((0, 2)))
    expected = cpu_spans(route, state.evaluator, state.config, AlternatingNoise(2.))
    batch = TowerBatch.from_routes([route], device)
    capacity = batch.xy.shape[1] + attempts
    noise = torch.zeros((attempts, attempts, 1, capacity, 2), device=device, dtype=torch.float64)
    noise[:, 1, :, :, 1] = 2.
    try:
        actual = repair_spans(batch, geometry, torch.Generator(device=device).manual_seed(1), noise=noise).routes()[0]
        np.testing.assert_array_equal(actual.towers, expected.towers)
        assert len(actual.towers) <= attempts
        if attempts == 2:
            assert not state.evaluator.evaluate(actual).is_feasible
    finally:
        geometry.close()
        engine.close()


@pytest.mark.parametrize("device", ["cpu", "cuda:0"])
def test_complete_sampling_matches_cpu_when_repairs_need_no_random_draws(device):
    if device.startswith("cuda") and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    state, engine, geometry = repair_geometry(device)
    routes = [Route(np.empty((0, 2))), Route(np.array([[8., 8.], [20., 8.]]))]
    counts = torch.tensor([2, 4], device=device)
    batch = TowerBatch.from_routes(routes, device)
    expected = [sample_route(state.adapter.path(route), n, state) for route, n in zip(routes, counts.cpu().tolist())]
    try:
        actual = sample_routes(batch, counts, geometry, torch.Generator(device=device).manual_seed(1)).routes()
        for a, b in zip(actual, expected):
            np.testing.assert_allclose(a.towers, b.towers, rtol=0, atol=1e-10)
    finally:
        geometry.close()
        engine.close()


def test_span_repair_does_not_repair_blocked_tower_without_an_excess_span():
    state, engine, geometry = repair_geometry("cpu")
    route = Route(np.array([[14., 14.]]))
    batch = TowerBatch.from_routes([route], "cpu")
    try:
        actual = repair_spans(batch, geometry, torch.Generator().manual_seed(1)).routes()[0]
        np.testing.assert_array_equal(actual.towers, route.towers)
        assert not state.evaluator.evaluate(actual).is_feasible
    finally:
        geometry.close()
        engine.close()


def test_repair_preflight_rejects_before_copying_and_noise_shape_is_checked(monkeypatch):
    import algorithms.routing.pilot_reference.tensor_repair as module
    state, engine, geometry = repair_geometry("cpu")
    batch = TowerBatch.from_routes([Route(np.array([[14., 14.]]))], "cpu")
    copies = []
    original = TowerBatch.clone
    def clone(value):
        copies.append(1)
        return original(value)
    def rejected(*args):
        raise MemoryError("test working budget exceeded")
    try:
        with pytest.raises(ValueError, match="noise"):
            repair_towers(batch, geometry, torch.Generator(), noise=torch.zeros((1, 1, 1, 2)))
        monkeypatch.setattr(TowerBatch, "clone", clone)
        monkeypatch.setattr(module, "require_workspace", rejected)
        with pytest.raises(MemoryError):
            repair_towers(batch, geometry, torch.Generator())
        assert not copies
    finally:
        geometry.close()
        engine.close()
