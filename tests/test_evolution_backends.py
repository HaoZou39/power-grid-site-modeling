"""Selectable implementations, original RNG preservation, and complete CPU searches."""

import json
from dataclasses import replace

import numpy as np
import pytest
import torch

from algorithms.guided_search.evolution import resolve_evolution_backend, describe_evolution_runtime
from algorithms.guided_search.search import GuidedSearch, pose_records
from config.project_config import load_default_config, resolve_guided_search_device
from experiments.problem_context import context_from_arrays
from modeling.haul_field import build_haul_field
from plugins.site_plugin import GuidedSiteConfig, PartitionedGuidedSiteConfig


def _arrays():
    y, x = np.indices((32, 40))
    mask = np.zeros((32, 40), dtype=np.float32)
    mask[14:20, 18:24] = 1
    return {"dem": (np.sin(x / 4) + y / 10).astype(np.float32), "obstacle_mask": mask,
            "landuse": np.where(mask > 0, 2, 0).astype(np.uint8),
            "road_segments": np.array([[0.1, 1.5, 39.9, 1.5]]),
            "road_segment_kinds": np.zeros(len(np.array([[0.1, 1.5, 39.9, 1.5]])), np.int8),
            "road_voronoi": np.zeros_like(mask, dtype=np.int64),
            "demand_points": np.array([[8., 16.], [28., 20.]], dtype=np.float32)}


@pytest.mark.parametrize("available,count", [(False, 0), (False, 1), (True, 0), (True, 2)])
@pytest.mark.parametrize("requested", ["auto", "cuda", "cuda:0"])
def test_device_resolution_detects_missing_gpu(monkeypatch, available, count, requested):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: available)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: count)
    device = resolve_guided_search_device(requested)
    assert device.type == ("cuda" if available and count else "cpu")
    assert resolve_evolution_backend("tensor", device) == ("tensor" if device.type == "cuda" else "numpy")
    assert resolve_evolution_backend("numpy", device) == "numpy"


def test_explicit_cpu_and_invalid_device_backend(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 1)
    assert resolve_guided_search_device("cpu") == torch.device("cpu")
    with pytest.raises(ValueError, match="index"):
        resolve_guided_search_device("cuda:1")
    with pytest.raises(ValueError, match="device"):
        resolve_guided_search_device("mps")
    with pytest.raises(ValueError, match="evolution_backend"):
        resolve_evolution_backend("unknown", torch.device("cpu"))


@pytest.mark.parametrize("requested", ["tensor", "numpy"])
def test_cpu_runtime_label_does_not_infer_gpu_from_availability(monkeypatch, requested):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda *args: pytest.fail("CPU run queried a GPU name"))
    label = describe_evolution_runtime(requested, torch.device("cpu"))
    assert "CPU NumPy 演化" in label
    assert "GPU" not in label


def test_schema_and_project_default_to_tensor():
    assert GuidedSiteConfig(experiment_name="example").evolution_backend == load_default_config().guided_search.evolution_backend
    for cls in (GuidedSiteConfig, PartitionedGuidedSiteConfig):
        assert cls(experiment_name="example", evolution_backend="numpy", device="cpu").evolution_backend == "numpy"
        with pytest.raises(ValueError, match="evolution_backend"):
            cls(experiment_name="example", evolution_backend="unknown")


def test_numpy_backend_preserves_original_seed17_population():
    from algorithms.guided_search.numpy_nsga2 import run_evolution

    def evaluate(raw):
        return np.column_stack((np.sum(raw**2, axis=1), np.sum((raw - 1)**2, axis=1))), np.maximum(raw[:, 0], 0)

    result = run_evolution(evaluate, popsize=8, generations=4, seed=17, sigma=.3, n_var=2)
    # Recorded from the original search implementation at 6740ce9.
    expected = [[-.06659085212516731, -.015553808439605313], [-.06691065463752363, .21170105881049192],
        [-.06169381983944838, .2192385409562701], [-.07774611337113307, .260822128163296],
        [-.03609847591076423, .6281001897205164], [-.04689763813486328, -.19035324004173632],
        [-.21639699597870443, .8325382649943609], [-.17296694011383426, .37978440625410037]]
    np.testing.assert_array_equal(np.stack([person.genes for person in result]), expected)


@pytest.mark.parametrize("initialization", ["uniform", "gaussian", "taguchi"])
@pytest.mark.parametrize("bounds", [None, (10., 20., 10., 20.)])
def test_cpu_fallback_keeps_guidance_bounds_and_exact_reports(monkeypatch, initialization, bounds):
    from algorithms.guided_search import tensor_nsga2

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 0)
    monkeypatch.setattr(tensor_nsga2, "run_evolution", lambda *a, **kw: pytest.fail("tensor backend ran on the CPU fallback"))
    device = resolve_guided_search_device("cuda")
    problem = context_from_arrays(_arrays(), device, road_setback_m=load_default_config().modeling.road_setback_m, water_setback_m=load_default_config().modeling.water_setback_m, highway_setback_m=load_default_config().modeling.highway_setback_m)
    model = replace(load_default_config().modeling, rect_w_m=4, rect_h_m=4)
    config = replace(load_default_config().guided_search, popsize=9, initialization=initialization, generations=2, guide_steps=1, include_demand=True)
    origin = (2., 1.5)
    progress = []
    result = GuidedSearch(config, origin, bounds).search(problem, model, lambda *entry: progress.append(entry))
    assert result.normalization["requested_evolution_backend"] == "tensor"
    assert result.normalization["evolution_backend"] == "numpy"
    assert result.normalization["device"] == "cpu"
    assert result.normalization["backend_fallback_reason"] == "cpu_device"
    assert len(result.solutions) == config.popsize
    assert all("CPU NumPy 演化" in message for _, _, message in progress)
    assert any(stage == "initialization" for _, stage, _ in progress)
    assert progress[-1][1] == "report"
    assert [p for p, _, _ in progress] == sorted(p for p, _, _ in progress)
    assert any("第 2/2 代" in message for _, _, message in progress)
    assert result.normalization["execution_description"] in progress[-1][2]
    pose = np.array([[row[k] for k in ("x", "y", "theta")] for row in result.solutions])
    again = pose_records(problem, model, origin, pose)
    for row, rescored in zip(result.solutions, again):
        for name in result.objective_names:
            assert row[name] == rescored[name]
        assert row["is_feasible"] == rescored["is_feasible"]
    if bounds:
        assert np.all((pose[:, 0] >= bounds[0]) & (pose[:, 0] <= bounds[1]))
        assert np.all((pose[:, 1] >= bounds[2]) & (pose[:, 1] <= bounds[3]))
    repeated = GuidedSearch(replace(config, evolution_backend="numpy"), origin, bounds).search(problem, model)
    assert repeated.solutions == result.solutions


@pytest.mark.parametrize("backend", ["tensor", "numpy"])
def test_cuda_uses_the_explicit_backend(cuda_device, monkeypatch, backend):
    from algorithms.guided_search import tensor_nsga2, numpy_nsga2

    called = []
    for name, module in (("tensor", tensor_nsga2), ("numpy", numpy_nsga2)):
        real = module.run_evolution
        def record(*args, _name=name, _real=real, **kwargs):
            called.append(_name)
            return _real(*args, **kwargs)
        monkeypatch.setattr(module, "run_evolution", record)
    problem = context_from_arrays(_arrays(), cuda_device, road_setback_m=load_default_config().modeling.road_setback_m, water_setback_m=load_default_config().modeling.water_setback_m, highway_setback_m=load_default_config().modeling.highway_setback_m)
    progress = []
    result = GuidedSearch(replace(load_default_config().guided_search, evolution_backend=backend, popsize=4, generations=1, guide_steps=1)).search(
        problem, replace(load_default_config().modeling, rect_w_m=4, rect_h_m=4), lambda *entry: progress.append(entry))
    assert called == [backend]
    assert result.normalization["evolution_backend"] == backend
    assert result.normalization["backend_fallback_reason"] is None
    expected = "GPU 张量演化" if backend == "tensor" else "CPU NumPy 演化，GPU 评价"
    assert all(expected in message for _, _, message in progress)
    assert torch.cuda.get_device_name(cuda_device) in result.normalization["execution_description"]
    assert progress[-1][1] == "report"


def test_cuda_and_cpu_evaluation_keep_the_same_objectives(cuda_device):
    from modeling.numpy_evaluator import NumpySiteEvaluator

    arrays = _arrays()
    field = build_haul_field(arrays["dem"], arrays["obstacle_mask"] == 0, arrays["road_segments"])
    model = replace(load_default_config().modeling, rect_w_m=4, rect_h_m=4)
    raw = np.random.default_rng(3).normal(size=(12, 3))
    values = []
    for device in (torch.device("cpu"), cuda_device):
        evaluator = NumpySiteEvaluator(context_from_arrays(arrays, device, road_setback_m=load_default_config().modeling.road_setback_m, water_setback_m=load_default_config().modeling.water_setback_m, highway_setback_m=load_default_config().modeling.highway_setback_m), model, field, include_demand=True)
        values.append(evaluator(raw))
    np.testing.assert_allclose(values[0][0], values[1][0], rtol=1e-5, atol=1e-5)
    np.testing.assert_array_equal(values[0][1], values[1][1])


def test_no_gpu_job_writes_normal_outputs(tmp_path, monkeypatch):
    from experiments import scene_store
    from experiments.launch_site_run import launch_site_run

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 0)
    root = tmp_path / "scenes"
    scene = root / scene_store.DEFAULT_SCENE
    scene.mkdir(parents=True)
    names = {"dem": "dem_1m.npy", "landuse": "landuse_1m.npy", "obstacle_mask": "obstacle_mask_1m.npy", "road_segments": "road_segments_local.npy", "road_segment_kinds": "road_segment_kind.npy",
             "road_voronoi": "road_voronoi_1m.npy", "demand_points": "demand_points.npy"}
    for key, filename in names.items():
        np.save(scene / filename, _arrays()[key])
    (scene / scene_store.SCENE_METADATA).write_text(json.dumps({"dem": {"reference_crs": "EPSG:3857",
        "target_transform": [1, 0, 100, 0, -1, 200], "shape": [32, 40]}, "demand": {"n_demand_points": 2}}))
    monkeypatch.setattr(scene_store, "scenes_root", lambda _: root)
    form = GuidedSiteConfig(experiment_name="cpu-job", popsize=4, generations=1, rect_w_m=4, rect_h_m=4).model_dump()
    progress = []
    directory = launch_site_run(form, "guided_search", lambda *entry: progress.append(entry), output_root=tmp_path / "outputs")
    normalization = json.loads((directory / "normalization.json").read_text())
    assert normalization["evolution_backend"] == "numpy"
    assert "CPU NumPy 演化" in normalization["execution_description"]
    assert any(stage == "figures" and "CPU NumPy 演化" in message for _, stage, message in progress)
    assert json.loads((directory / "run_summary.json").read_text())["n_solutions"] == 4
    assert (directory / "solutions.csv").is_file()
    assert (directory / "pareto_solutions.csv").is_file()
    assert (directory / "all_candidates_points_map.png").is_file()


def test_cpu_partitions_inherit_the_backend_and_save_actual_runtime():
    from experiments.partitioned_search import plan_search_partitions, run_partitioned_guided_search

    problem = context_from_arrays(_arrays(), torch.device("cpu"), road_setback_m=load_default_config().modeling.road_setback_m, water_setback_m=load_default_config().modeling.water_setback_m, highway_setback_m=load_default_config().modeling.highway_setback_m)
    model = replace(load_default_config().modeling, rect_w_m=4, rect_h_m=4)
    config = replace(load_default_config().guided_search, popsize=4, generations=1, guide_steps=1)
    field = build_haul_field(problem.dem, problem.obstacle_mask == 0, problem.road_segments)
    partitions = plan_search_partitions(problem.dem.shape, 4, 4, 4, config.seed)
    result = run_partitioned_guided_search(problem, model, config, None, field, partitions, 2, lambda *a: None)
    assert result.normalization["requested_evolution_backend"] == "tensor"
    assert result.normalization["evolution_backend"] == "numpy"
    assert result.normalization["device"] == "cpu"
    assert len(result.partitions) == 4
    assert len(result.solutions) > 0
