"""Automatic results keep the two newest completed runs per scene and problem type."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.infrastructure.experiment_catalog import ExperimentCatalog, ExperimentNotFound
from experiments.auto_result_retention import (
    AUTO_RESULT_KEEP_COUNT,
    note_displayed_auto_result,
    pin_auto_result,
    retain_auto_results,
    retain_published_auto_result,
    set_active_experiment_provider,
)


@pytest.fixture(autouse=True)
def _clear_active_names():
    set_active_experiment_provider(None)
    yield
    set_active_experiment_provider(None)


def _write(root: Path, name: str, summary: dict, *, snapshot: str | None = None, routing: bool = False, payload: bytes = b"") -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    if snapshot is not None:
        (directory / "site_form_snapshot.json").write_text(json.dumps({"scene_name": snapshot}), encoding="utf-8")
    if routing:
        snapshot_dir = directory / "scene_snapshot"
        snapshot_dir.mkdir()
        (snapshot_dir / "dem_1m.npy").write_bytes(payload or b"raster")
        (directory / "routes.json").write_text("{}", encoding="utf-8")
    elif payload:
        (directory / "solutions.csv").write_bytes(payload)
    return directory


def _auto(root: Path, name: str, scene: str, kind: str, when: str, **extra) -> Path:
    summary = {
        "result_origin": "auto",
        "problem_type": kind,
        "scene_name": scene,
        "completed_at": when,
        "algorithm": "guided_search" if kind == "site" else "routing_nsga2",
        "owner_id": "owner-a",
        **extra,
    }
    return _write(root, name, summary, snapshot=scene if kind == "site" else None, routing=kind == "routing", payload=b"x" * 32)


def _ids(root: Path) -> set[str]:
    return {path.name for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")}


def _retain(root: Path, scene: str, kind: str, trigger: str) -> dict:
    return retain_auto_results(root, scene_name=scene, problem_type=kind, trigger_id=trigger, owner_id="owner-a")


def test_keep_count_is_two() -> None:
    assert AUTO_RESULT_KEEP_COUNT == 2


def test_site_keeps_the_two_newest(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    root.mkdir()
    _auto(root, "site-1", "scene-a", "site", "2026-01-01T00:00:01+00:00")
    assert _ids(root) == {"site-1"}
    _auto(root, "site-2", "scene-a", "site", "2026-01-01T00:00:02+00:00")
    _retain(root, "scene-a", "site", "site-2")
    assert _ids(root) == {"site-1", "site-2"}
    _auto(root, "site-3", "scene-a", "site", "2026-01-01T00:00:03+00:00", search_scope="local")
    _retain(root, "scene-a", "site", "site-3")
    assert _ids(root) == {"site-2", "site-3"}
    _auto(root, "site-4", "scene-a", "site", "2026-01-01T00:00:04+00:00")
    report = _retain(root, "scene-a", "site", "site-4")
    assert _ids(root) == {"site-3", "site-4"}
    assert report["deleted"] == ["site-2"]
    assert report["deleted_count"] == 1
    assert report["freed_bytes"] >= 32
    assert report["failures"] == []


def test_equal_times_break_ties_by_experiment_id(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    root.mkdir()
    when = "2026-01-01T00:00:00+00:00"
    for name in ("b-run", "c-run", "a-run"):
        _auto(root, name, "scene-a", "site", when)
    _retain(root, "scene-a", "site", "a-run")
    assert _ids(root) == {"a-run", "b-run"}


def test_scenes_do_not_change_each_other(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    root.mkdir()
    for index in range(1, 5):
        _auto(root, f"a-{index}", "scene-a", "site", f"2026-02-0{index}T00:00:00+00:00")
    for index in range(1, 4):
        _auto(root, f"b-{index}", "scene-b", "site", f"2026-03-0{index}T00:00:00+00:00")
    _retain(root, "scene-a", "site", "a-4")
    assert {name for name in _ids(root) if name.startswith("a-")} == {"a-3", "a-4"}
    assert {name for name in _ids(root) if name.startswith("b-")} == {"b-1", "b-2", "b-3"}
    _retain(root, "scene-b", "site", "b-3")
    assert {name for name in _ids(root) if name.startswith("a-")} == {"a-3", "a-4"}
    assert {name for name in _ids(root) if name.startswith("b-")} == {"b-2", "b-3"}


def test_site_and_routing_quotas_are_separate(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    root.mkdir()
    for index in range(1, 5):
        _auto(root, f"site-{index}", "scene-a", "site", f"2026-04-0{index}T00:00:00+00:00")
    for index in range(1, 6):
        _auto(root, f"route-{index}", "scene-a", "routing", f"2026-05-0{index}T00:00:00+00:00")
    _retain(root, "scene-a", "site", "site-4")
    _retain(root, "scene-a", "routing", "route-5")
    assert {name for name in _ids(root) if name.startswith("site-")} == {"site-3", "site-4"}
    assert {name for name in _ids(root) if name.startswith("route-")} == {"route-4", "route-5"}
    assert not (root / "route-1" / "scene_snapshot").exists()
    assert (root / "route-5" / "scene_snapshot" / "dem_1m.npy").is_file()


def test_manual_cases_and_legacy_cases_stay(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    root.mkdir()
    for index in range(1, 6):
        _auto(root, f"auto-{index}", "scene-a", "site", f"2026-06-0{index}T00:00:00+00:00")
    _write(root, "case-new", {"is_case": True, "algorithm": "workspace_snapshot", "scene_name": "scene-a", "display_name": "新案例"})
    _write(root, "case-legacy-site", {}, snapshot="scene-a")
    (root / "case-legacy-site" / "workspace_solutions.json").write_text("{}", encoding="utf-8")
    _write(root, "case-legacy-routing", {"algorithm": "routing_workspace", "problem_type": "routing", "scene_name": "scene-a"})
    report = _retain(root, "scene-a", "site", "auto-5")
    assert {name for name in _ids(root) if name.startswith("auto-")} == {"auto-4", "auto-5"}
    assert {"case-new", "case-legacy-site", "case-legacy-routing"} <= _ids(root)
    assert {item["id"] for item in report["skipped"] if item["reason"] == "manual_case"} >= {
        "case-new", "case-legacy-site", "case-legacy-routing",
    }
    listed = {record.id for record in ExperimentCatalog(root).list_experiments(cases_only=True)}
    assert listed == {"case-new", "case-legacy-site", "case-legacy-routing"}


def test_legacy_automatic_results_use_the_same_quota(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    root.mkdir()
    for index, name in enumerate(("old-cma", "old-guided", "old-adam"), start=1):
        _write(
            root, name,
            {"algorithm": "cma_es" if index == 1 else "guided_search" if index == 2 else "multistart_adam",
             "owner_id": "owner-a",
             "completed_at": f"2026-07-0{index}T00:00:00+00:00"},
            snapshot="scene-a",
        )
    _retain(root, "scene-a", "site", "old-adam")
    assert _ids(root) == {"old-guided", "old-adam"}


def test_displayed_and_pinned_results_survive_until_released(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    root.mkdir()
    for index in range(1, 5):
        _auto(root, f"run-{index}", "scene-a", "site", f"2026-08-0{index}T00:00:00+00:00")
    note_displayed_auto_result(root, "run-1")
    _retain(root, "scene-a", "site", "run-4")
    assert _ids(root) == {"run-1", "run-3", "run-4"}
    note_displayed_auto_result(root, "run-4")
    _retain(root, "scene-a", "site", "run-4")
    assert _ids(root) == {"run-3", "run-4"}

    for index in range(1, 4):
        _auto(root, f"route-{index}", "scene-a", "routing", f"2026-09-0{index}T00:00:00+00:00")
    with pin_auto_result(root, "route-1"):
        _retain(root, "scene-a", "routing", "route-3")
        assert (root / "route-1" / "routes.json").is_file()
        assert (root / "route-1" / "scene_snapshot").is_dir()
    _retain(root, "scene-a", "routing", "route-3")
    assert not (root / "route-1").exists()
    assert (root / "route-3" / "routes.json").is_file()


def test_active_job_and_new_result_are_protected(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    root.mkdir()
    for index in range(1, 4):
        _auto(root, f"run-{index}", "scene-a", "site", f"2026-10-0{index}T00:00:00+00:00")
    set_active_experiment_provider(lambda: {"run-1"})
    _retain(root, "scene-a", "site", "run-3")
    assert "run-1" in _ids(root)
    set_active_experiment_provider(None)
    _auto(root, "run-old-clock", "scene-a", "site", "2020-01-01T00:00:00+00:00")
    _retain(root, "scene-a", "site", "run-old-clock")
    assert "run-old-clock" in _ids(root)


def test_unsafe_directories_and_cleanup_errors_stay_contained(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    root.mkdir()
    scene = tmp_path / "scenes" / "scene-a"
    scene.mkdir(parents=True)
    (scene / "dem_1m.npy").write_bytes(b"scene")
    outside = tmp_path / "secret.txt"
    outside.write_text("keep", encoding="utf-8")
    link = root / "linked-outside"
    link.symlink_to(tmp_path, target_is_directory=True)
    for index in range(1, 4):
        _auto(root, f"run-{index}", "scene-a", "site", f"2026-11-0{index}T00:00:00+00:00")
    (root / "partial").mkdir()
    (root / "partial" / "solutions.csv").write_text("still writing", encoding="utf-8")
    staging = root / ".experiment-run-live"
    (staging / "run").mkdir(parents=True)
    (staging / "run" / "run_summary.json").write_text("{}", encoding="utf-8")
    _write(root, "unknown-old", {"note": "not an optimization"})
    broken = root / "broken"
    broken.mkdir()
    (broken / "run_summary.json").write_text("{", encoding="utf-8")
    original = ExperimentCatalog.delete_experiment

    def fail_oldest(self, experiment_id: str) -> None:
        if experiment_id == "run-1":
            raise OSError("busy")
        original(self, experiment_id)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(ExperimentCatalog, "delete_experiment", fail_oldest)
    try:
        report = _retain(root, "scene-a", "site", "run-3")
    finally:
        monkeypatch.undo()
    assert "run-1" in _ids(root)
    assert {"run-2", "run-3", "partial", "unknown-old", "broken", "linked-outside"} <= _ids(root)
    assert staging.is_dir() and (staging / "run" / "run_summary.json").is_file()
    assert outside.read_text(encoding="utf-8") == "keep"
    assert (scene / "dem_1m.npy").read_bytes() == b"scene"
    assert report["failures"]
    with pytest.raises(ExperimentNotFound):
        ExperimentCatalog(root).delete_experiment("../secret.txt")
    assert outside.is_file()

    def explode(*_args, **_kwargs):
        raise RuntimeError("disk")

    monkeypatch.setattr("experiments.auto_result_retention.retain_auto_results", explode)
    try:
        retain_published_auto_result(root / "run-3", "site")
    finally:
        monkeypatch.undo()
    assert (root / "run-3" / "run_summary.json").is_file()
    assert (root / "run-2" / "run_summary.json").is_file()


def test_catalog_hides_retention_fields_without_dropping_routing_identity(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    site = _auto(root, "site-run", "scene-a", "site", "2026-12-01T00:00:00+00:00")
    routing = _auto(root, "route-run", "scene-a", "routing", "2026-12-02T00:00:00+00:00")
    catalog = ExperimentCatalog(root)
    site_summary = catalog.get_experiment("site-run").summary
    routing_summary = catalog.get_experiment("route-run").summary
    assert "result_origin" not in site_summary and "completed_at" not in site_summary
    assert "problem_type" not in site_summary and "scene_name" not in site_summary
    assert site_summary["algorithm"] == "guided_search"
    assert "result_origin" not in routing_summary and "completed_at" not in routing_summary
    assert routing_summary["problem_type"] == "routing" and routing_summary["scene_name"] == "scene-a"
    stored = json.loads((site / "run_summary.json").read_text(encoding="utf-8"))
    assert stored["result_origin"] == "auto" and stored["problem_type"] == "site"
    assert json.loads((routing / "run_summary.json").read_text(encoding="utf-8"))["result_origin"] == "auto"
