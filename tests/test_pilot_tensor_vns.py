import numpy as np
import torch

from algorithms.routing.pilot_reference.refinement import vns as cpu_vns
from algorithms.routing.pilot_reference.tensor_refinement import vns
from modeling.routing.types import Route
from test_pilot_components import state_for
from test_pilot_tensor_variation import tensor_state, scored


def test_fixed_vns_lanes_match_each_cpu_acceptance_and_stop_at_budget(tensor_state):
    state = tensor_state
    genes = [np.array([[8., 12.], [18., 11.]]), np.array([[10., 10.], [19., 12.]])]
    parents = scored(state, genes)
    original = parents.routes.xy.clone()
    # Includes improving, worsening and equal proposals around a static base.
    pattern = np.array([[0.,-.3], [0.,.2], [0.,0.], [.15,-.2], [-.2,.2], [0.,-.4]])
    normals = np.tile(pattern, (8, 1))
    noise = np.broadcast_to(normals[None, :, None], (2, len(normals), 2, 2)).copy()
    state.geometry.radii = lambda points: points.new_full((len(points),), 6.)
    state.geometry.project = lambda points, *args, **kwargs: points.clone()
    indices = torch.tensor([[0, 1], [0, 1]], device=state.device)
    for exhaustive in [False, True]:
        expected, traces = [], []
        for lane in range(2):
            cpu = state_for()
            first = cpu.score(Route(genes[lane]), cpu.budget.window("initialization", 1))
            cpu.neighborhood_radius = lambda *args: 6.
            cpu.project = lambda point, *args, **kwargs: point.copy()
            cpu.adapter.python_rng.shuffle = lambda sequence: None
            reference_radius = 6./cpu.scale
            tries = (max(cpu.core.vns_exhaustive_min_tries, round(reference_radius)) if exhaustive else
                     max(cpu.core.vns_fast_min_tries, round(cpu.core.vns_fast_try_factor*reference_radius)))
            draws = iter(noise[:, :tries, lane].reshape(-1, 2))
            cpu.adapter.numpy_rng = type("FixedNoise", (), {"normal": lambda _, loc, sigma, **kw: next(draws)*sigma})()
            trace = []
            compare = cpu.better
            def checked(a, b, **kwargs):
                result = compare(a, b, **kwargs)
                trace.append(result)
                return result
            cpu.better = checked
            expected.append(cpu_vns(first, cpu, cpu.budget.window("local_search", 256), exhaustive=exhaustive))
            traces.append(trace)
        for limit in [256, 3, 0]:
            accepted = [[], []]
            compare = state.better
            before = len(state.budget.records)
            def checked_batch(a, b, **kwargs):
                result = compare(a, b, **kwargs)
                assert not bool((result & (b.ids < 0)).any())
                for lane in range(2):
                    if b.ids[lane] >= before:
                        accepted[lane].append(bool(result[lane]))
                return result
            state.better = checked_batch
            window = state.budget.window("local_search", limit)
            try:
                actual = vns(parents, state, window, exhaustive=exhaustive, indices=indices,
                             noise=torch.tensor(noise, dtype=torch.float64, device=state.device))
            finally:
                state.better = compare
            assert window.used <= limit
            assert bool((actual.ids >= 0).all())
            assert bool((actual.ids < len(state.budget.records)).all())
            assert torch.equal(parents.routes.xy, original)
            if limit == 256:
                assert accepted == traces
                assert any(any(t) for t in traces) and any(not all(t) for t in traces)
                for observed, reference in zip(actual.routes.routes(), expected):
                    np.testing.assert_allclose(observed.towers, reference.route.towers, atol=1e-12, rtol=1e-12)
            elif limit == 0:
                assert torch.equal(actual.ids, parents.ids)
