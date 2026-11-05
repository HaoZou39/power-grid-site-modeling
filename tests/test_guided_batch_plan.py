"""One-shot Guided Search batch planning. Memory figures are injected; no scene is built."""

import json
from dataclasses import replace

import numpy as np
import pytest
import torch

from algorithms.guided_search.batch_planner import (
    BatchPlan,
    MemorySnapshot,
    batch_limits,
    footprint_window,
    plan_guided_batches,
    stage_bytes,
    write_resolved_batch_plan,
)
from algorithms.guided_search.search import GuidedSearch, pose_records
from config.project_config import load_default_config, save_config
from experiments.launch_site_run import apply_site_form
from modeling.context import SiteProblemContext
from modeling.haul_field import build_haul_field
from modeling.masks import compute_soft_footprint

GiB = 1024**3
GPU = MemorySnapshot(30 * GiB, 40 * GiB, "simulated")
HOST = MemorySnapshot(200 * GiB, 250 * GiB)


def _plan(width, height, *, gpu=GPU, host=HOST, population=10000, guide=8192, evaluation=8192, report=8192, device=None):
    return plan_guided_batches(
        width, height, population=population, guide_limit=guide, evaluation_limit=evaluation,
        report_limit=report, device=device or torch.device("cuda:0"),
        gpu_memory=lambda _device: gpu, host_memory=lambda: host,
    )


def _problem(device):
    height = width = 32
    dem = np.zeros((height, width), dtype=np.float64)
    dem[8:12, 8:12] = 1.0
    obstacle = np.zeros((height, width), dtype=np.float32)
    segments = np.array([[0.0, 4.5, 31.0, 4.5]], dtype=np.float64)
    demand = np.array([[8.0, 20.0], [24.0, 18.0]], dtype=np.float32)
    problem = SiteProblemContext(
        dem=dem, obstacle_mask=obstacle, road_segments=segments,
        dem_tensor=torch.tensor(dem, dtype=torch.float32, device=device)[None, None],
        obstacle_tensor=torch.zeros((1, 1, height, width), dtype=torch.float32, device=device),
        road_segments_tensor=torch.tensor(segments, dtype=torch.float32, device=device),
        road_voronoi_tensor=torch.zeros((height, width), dtype=torch.long, device=device),
        demand_points=demand, demand_weights=np.ones(len(demand), dtype=np.float32),
        demand_points_tensor=torch.tensor(demand, dtype=torch.float32, device=device),
        demand_weights_tensor=torch.ones(len(demand), dtype=torch.float32, device=device),
        device=device,
    )
    field = build_haul_field(dem, obstacle == 0, segments, None)
    modeling = replace(load_default_config().modeling, rect_w_m=4.0, rect_h_m=4.0, soft_mask_sharpness=8.0, device="cuda")
    return problem, field, modeling


def test_window_matches_the_soft_footprint() -> None:
    pose = torch.zeros((1, 3))
    for width, height in ((77.0, 51.5), (500.0, 300.0)):
        weights = compute_soft_footprint(pose, width, height, (2000, 2000))["weights"]
        assert weights.shape[-2:] == (footprint_window(width, height),) * 2
    assert footprint_window(77, 51.5) == 97
    assert footprint_window(500, 300) == 588


def test_stage_coefficients_differ_and_guide_is_the_largest() -> None:
    costs = stage_bytes(97)
    assert costs["guide"] > costs["evaluation"] > costs["report_gpu"]
    assert costs["report_cpu"] != costs["report_gpu"]
    assert len({costs["guide"], costs["evaluation"], costs["report_gpu"], costs["report_cpu"]}) == 4


def test_simulated_small_and_large_buildings_stay_inside_the_caps() -> None:
    small = _plan(77, 51.5)
    large = _plan(500, 300)
    assert (small.guide_batch_size, small.evaluation_batch_size, small.report_batch_size) == (8192, 8192, 8192)
    assert (large.guide_batch_size, large.evaluation_batch_size, large.report_batch_size) == (304, 521, 913)
    for plan, limit in ((small, (8192, 8192, 8192)), (large, (8192, 8192, 8192))):
        actual = (plan.guide_batch_size, plan.evaluation_batch_size, plan.report_batch_size)
        assert all(1 <= value <= cap and value <= plan.population for value, cap in zip(actual, limit))
    assert large.guide_batch_size <= small.guide_batch_size
    assert large.evaluation_batch_size <= small.evaluation_batch_size
    assert large.report_batch_size <= small.report_batch_size
    assert large.footprint_window > small.footprint_window


def test_less_free_memory_never_increases_a_batch() -> None:
    wide = _plan(500, 300)
    tight_gpu = _plan(500, 300, gpu=MemorySnapshot(12 * GiB, 40 * GiB, "simulated"))
    assert tight_gpu.guide_batch_size <= wide.guide_batch_size
    assert tight_gpu.evaluation_batch_size <= wide.evaluation_batch_size
    assert tight_gpu.report_batch_size <= wide.report_batch_size
    assert tight_gpu.guide_batch_size < wide.guide_batch_size
    costs = stage_bytes(wide.footprint_window)
    reserve = 8 * GiB
    usable = costs["report_cpu_workspace"] + 2 * costs["report_cpu"]
    tight_host = _plan(500, 300, host=MemorySnapshot(reserve + usable, 32 * GiB))
    assert tight_host.guide_batch_size == wide.guide_batch_size
    assert tight_host.evaluation_batch_size == wide.evaluation_batch_size
    assert tight_host.report_batch_size == 2


def test_population_and_explicit_limit_both_cap_the_plan() -> None:
    capped = _plan(77, 51.5, population=50, evaluation=32)
    assert (capped.guide_batch_size, capped.evaluation_batch_size, capped.report_batch_size) == (50, 32, 50)


def test_low_memory_refuses_a_single_candidate() -> None:
    with pytest.raises(RuntimeError, match="cannot fit one candidate"):
        _plan(500, 300, gpu=MemorySnapshot(10 * GiB, 40 * GiB, "simulated"))
    costs = stage_bytes(588)
    reserve = 10 * GiB
    with pytest.raises(RuntimeError, match="guide batch cannot fit one candidate"):
        _plan(500, 300, gpu=MemorySnapshot(reserve + costs["guide"] - 1, 40 * GiB, "simulated"))


def test_cpu_plan_does_not_query_memory_and_keeps_the_limits() -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("memory was queried")

    plan = plan_guided_batches(
        77, 51.5, population=10000, guide_limit=8192, evaluation_limit=8192, report_limit=8192,
        device=torch.device("cpu"), gpu_memory=forbidden, host_memory=forbidden,
    )
    assert plan.memory_query == "cpu"
    assert plan.gpu_name is None and plan.free_gpu_bytes is None
    assert (plan.guide_batch_size, plan.evaluation_batch_size, plan.report_batch_size) == (8192, 8192, 8192)
    small = plan_guided_batches(
        4, 4, population=4, guide_limit=8192, evaluation_limit=8192, report_limit=8192,
        device=torch.device("cpu"), gpu_memory=forbidden, host_memory=forbidden,
    )
    assert (small.guide_batch_size, small.evaluation_batch_size, small.report_batch_size) == (4, 4, 4)


def test_form_override_and_direct_config_use_the_same_limits() -> None:
    base = load_default_config()
    form = {
        "experiment_name": "batch", "seed": 7, "popsize": 100, "generations": 1, "sigma0": 1,
        "rect_w_m": 77, "rect_h_m": 51.5, "device": "cuda", "demand_on_buildable_only": False,
        "evaluation_batch_size": 32,
    }
    configured = apply_site_form(base, form, "guided_search").guided_search
    direct = replace(base.guided_search, evaluation_batch_size=32, guide_batch_size=9999)
    assert batch_limits(configured) == (8192, 32, 8192)
    assert batch_limits(direct) == (8192, 32, 8192)
    assert batch_limits(base.guided_search) == (8192, 8192, 8192)


def test_search_uses_the_supplied_plan_for_each_stage(monkeypatch) -> None:
    device = torch.device("cpu")
    problem, field, modeling = _problem(device)
    plan = BatchPlan(
        rect_w_m=4.0, rect_h_m=4.0, footprint_window=10, footprint_pixels=100, device="cpu",
        gpu_name=None, free_gpu_bytes=None, total_gpu_bytes=None, usable_gpu_bytes=None,
        free_host_bytes=None, usable_host_bytes=None, population=4,
        guide_batch_size=2, evaluation_batch_size=3, report_batch_size=1,
        guide_batch_limit=8192, evaluation_batch_limit=8192, report_batch_limit=8192,
        bytes_per_candidate=stage_bytes(10), memory_query="cpu",
    )
    seen = {}

    import algorithms.guided_search.guide as guide_module
    import algorithms.guided_search.search as search_module
    from modeling.tensor_evaluator import TensorSiteEvaluator

    real_guide = guide_module.guide_initial_population
    real_records = search_module.pose_records
    real_evaluator = TensorSiteEvaluator

    def guide_spy(*args, **kwargs):
        seen["guide"] = args[2].guide_batch_size
        return real_guide(*args, **kwargs)

    def records_spy(*args, **kwargs):
        seen["report"] = kwargs["report_batch"]
        return real_records(*args, **kwargs)

    def evaluator_spy(*args, **kwargs):
        seen["evaluation"] = kwargs["batch_size"]
        return real_evaluator(*args, **kwargs)

    monkeypatch.setattr(search_module, "resolve_evolution_backend", lambda _requested, _device: "tensor")
    monkeypatch.setattr(guide_module, "guide_initial_population", guide_spy)
    monkeypatch.setattr(search_module, "pose_records", records_spy)
    monkeypatch.setattr("modeling.tensor_evaluator.TensorSiteEvaluator", evaluator_spy)
    config = replace(load_default_config().guided_search, popsize=4, generations=1, guide_steps=1, seed=1)
    result = GuidedSearch(config).search(problem, modeling, field=field, batch_plan=plan)
    assert seen == {"guide": 2, "evaluation": 3, "report": 1}
    assert len(result.solutions) == 4
    assert result.normalization["batch_plan"]["report_batch_size"] == 1


def test_changing_the_batch_keeps_the_results() -> None:
    device = torch.device("cpu")
    problem, field, modeling = _problem(device)
    from algorithms.guided_search.guide import guide_initial_population
    from modeling.tensor_evaluator import TensorSiteEvaluator

    config = replace(load_default_config().guided_search, popsize=5, guide_steps=1, seed=2)
    whole = guide_initial_population(problem, modeling, replace(config, guide_batch_size=5), field)
    chunked = guide_initial_population(problem, modeling, replace(config, guide_batch_size=2), field)
    np.testing.assert_allclose(chunked, whole)

    evaluator_one = TensorSiteEvaluator(problem, modeling, field, batch_size=1)
    evaluator_all = TensorSiteEvaluator(problem, modeling, field, batch_size=len(whole))
    raw = torch.tensor(whole, dtype=torch.float64)
    one = evaluator_one(raw)
    full = evaluator_all(raw)
    torch.testing.assert_close(one[0], full[0])
    torch.testing.assert_close(one[1], full[1])

    pose = torch.tensor([[16.0, 16.0, 0.2], [12.0, 20.0, -0.4], [18.0, 10.0, 0.7]])
    single = pose_records(problem, modeling, None, pose.numpy(), field=field, report_batch=1)
    together = pose_records(problem, modeling, None, pose.numpy(), field=field, report_batch=3)
    assert len(single) == len(together) == 3
    for left, right in zip(single, together):
        assert left["is_feasible"] == right["is_feasible"]
        for name in ("dem_soft", "obstacle_soft", "road_distance", "demand_distance", "obstacle_hard_count"):
            assert left[name] == pytest.approx(right[name])


def test_plan_is_written_into_resolved_config(tmp_path) -> None:
    config = replace(
        load_default_config(),
        modeling=replace(load_default_config().modeling, rect_w_m=500, rect_h_m=300),
    )
    path = tmp_path / "resolved_config.json"
    save_config(config, path)
    plan = _plan(500, 300)
    write_resolved_batch_plan(path, plan.as_record())
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["modeling"]["rect_w_m"] == 500 and raw["modeling"]["rect_h_m"] == 300
    assert raw["guided_search"]["guide_batch_size"] == 304
    assert raw["guided_search"]["evaluation_batch_size"] == 521
    recorded = raw["batch_plan"]
    assert recorded["report_batch_size"] == 913
    assert recorded["footprint_window"] == 588
    assert recorded["gpu_name"] == "simulated"
    assert recorded["free_gpu_bytes"] == 30 * GiB
    assert recorded["rect_w_m"] == 500 and recorded["rect_h_m"] == 300
