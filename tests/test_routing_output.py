from dataclasses import asdict, replace
import json

import numpy as np
import pytest

from config.project_config import load_default_config
from experiments.launch_routing_run import launch_routing_run
from modeling.routing.types import RoutingFrame
from plugins.routing_plugin import RoutingRunConfig


def routing_task(tmp_path, monkeypatch, **overrides):
    root = tmp_path / "scenes"; root.mkdir(exist_ok=True)
    scene = root / "routing-test"; scene.mkdir(exist_ok=True)
    monkeypatch.setenv("SCENE_ROOT", str(root))
    frame = RoutingFrame("EPSG:32651", (1, 0, 221000, 0, -1, 3046000), 32, 32)
    for name, array in {"dem_1m.npy": np.zeros((32, 32)), "landuse_1m.npy": np.zeros((32, 32), dtype=np.int32),
        "road_segments_local.npy": np.empty((0, 4)), "road_segment_kind.npy": np.empty(0, dtype=np.int8)}.items():
        np.save(scene / name, array)
    (scene / "data_metadata.json").write_text(json.dumps({"dem": {"reference_crs": frame.crs,
        "target_transform": frame.transform, "shape": [32, 32]}}))
    start, end = frame.to_wgs84([2, 8]), frame.to_wgs84([28, 8])
    config = replace(load_default_config().routing, popsize=8, max_evaluations=32, reference_count=2, expansion_interval=1)
    data = {"scene_name": scene.name, "experiment_name": "routing-check", "start": dict(zip(["lng", "lat"], start)),
        "end": dict(zip(["lng", "lat"], end)), "max_span_m": 30, "tower_radius_m": .4,
        "max_turn_deg": 90, "road_setback_m": 0, "highway_setback_m": 0, "algorithm": asdict(config)}
    return RoutingRunConfig.model_validate({**data, **overrides}), scene


def test_run_roundtrip_and_independent_input_snapshot(tmp_path, monkeypatch):
    task, scene = routing_task(tmp_path, monkeypatch)
    output = launch_routing_run(task, lambda *_: None, output_root=tmp_path / "runs")
    summary = json.loads((output / "run_summary.json").read_text())
    routes = json.loads((output / "routes.json").read_text())
    assert summary["problem_type"] == "routing" and summary["n_pareto"] > 0
    assert summary["evaluation_count"] == task.algorithm.max_evaluations
    assert routes["routes"][0]["points"][0]["role"] == "start"
    source = scene / "landuse_1m.npy"; snapshot = output / "scene_snapshot" / source.name
    before = snapshot.read_bytes()
    assert snapshot.stat().st_ino != source.stat().st_ino
    np.save(source, np.ones((32, 32), dtype=np.int32))
    assert snapshot.read_bytes() == before
    assert "NaN" not in (output / "routes.json").read_text()
    assert "Infinity" not in (output / "routes.json").read_text()


def test_cancel_before_publication_preserves_finished_experiment(tmp_path, monkeypatch):
    from backend.app.domain.jobs import JobCancelled
    task, _ = routing_task(tmp_path, monkeypatch)
    output = launch_routing_run(task, lambda *_: None, output_root=tmp_path / "runs")
    before = (output / "routes.json").read_bytes()
    def cancel(_progress, stage, _message):
        if stage == "publishing":
            raise JobCancelled("test")
    with pytest.raises(JobCancelled):
        launch_routing_run(task.model_copy(update={"overwrite_existing": True}), cancel, output_root=tmp_path / "runs")
    assert (output / "routes.json").read_bytes() == before
    assert not list(output.parent.glob(".experiment-run-*"))


def test_invalid_input_and_same_name_do_not_replace_results(tmp_path, monkeypatch):
    task, _ = routing_task(tmp_path, monkeypatch)
    root = tmp_path / "runs"
    output = launch_routing_run(task, lambda *_: None, output_root=root)
    with pytest.raises(ValueError):
        launch_routing_run(task, lambda *_: None, output_root=root)
    assert (output / "run_summary.json").is_file()


def test_registered_farmland_cannot_silently_disappear(tmp_path, monkeypatch):
    from experiments.protected_farmland import META_NAME
    task, scene = routing_task(tmp_path, monkeypatch)
    (scene / META_NAME).write_text("{}")
    with pytest.raises(FileNotFoundError, match="protected_farmland_mask"):
        launch_routing_run(task, lambda *_: None, output_root=tmp_path / "runs")
