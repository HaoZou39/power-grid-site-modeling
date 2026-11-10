"""Shared immutable copies of a public scene's optimization inputs."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import pytest

from experiments.base_scene_snapshot import (
    SnapshotError,
    manifest_sha256,
    prepare_base_snapshot,
    register_ready_snapshot,
    snapshot_usage_report,
    verify_base_snapshot,
)
from experiments.base_scene_snapshot import _identity_id

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def _scene(root: Path, name: str = "demo", revision: str = "rev-1", *, farmland: bool = False, claim: bool = False) -> Path:
    scene = root / name
    scene.mkdir(parents=True, exist_ok=True)
    arrays = {
        "dem_1m.npy": np.ones((3, 4), np.float32),
        "landuse_1m.npy": np.zeros((3, 4), np.uint8),
        "obstacle_mask_1m.npy": np.zeros((3, 4), np.uint8),
        "road_segments_local.npy": np.array([[0, 1, 4, 1]], np.float32),
        "road_segment_kind.npy": np.zeros(1, np.int8),
        "road_voronoi_1m.npy": np.zeros((3, 4), np.int64),
        "demand_points.npy": np.array([[0.5, 0.5]], np.float32),
    }
    if farmland:
        arrays["protected_farmland_mask_1m.npy"] = np.zeros((3, 4), np.bool_)
    for filename, array in arrays.items():
        np.save(scene / filename, array)
    metadata = {
        "scene_revision": revision,
        "dem": {"reference_crs": "EPSG:3857", "target_transform": [1, 0, 100, 0, -1, 200], "shape": [3, 4]},
    }
    if claim:
        metadata["protected_farmland"] = {"registered": True}
    (scene / "data_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    if farmland:
        (scene / "protected_farmland_import.json").write_text("{}\n", encoding="utf-8")
    (scene / "satellite.png").write_bytes(b"not-an-input")
    return scene


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, "-c", script, *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )


def test_prepare_copies_required_arrays_and_hashes_them(tmp_path: Path) -> None:
    scene = _scene(tmp_path / "scenes")
    before = {path.name: path.read_bytes() for path in scene.iterdir() if path.is_file()}
    prepared = prepare_base_snapshot("demo", snapshot_root=tmp_path / "snaps", scene_root=tmp_path / "scenes")
    manifest = verify_base_snapshot(prepared.snapshot_id, snapshot_root=tmp_path / "snaps")
    names = {item["relative_path"] for item in manifest["files"]}
    assert names == {
        "dem_1m.npy", "landuse_1m.npy", "obstacle_mask_1m.npy", "road_segments_local.npy",
        "road_segment_kind.npy", "road_voronoi_1m.npy", "demand_points.npy", "data_metadata.json",
    }
    assert "satellite.png" not in names
    assert manifest["base_scene_id"] == "demo"
    assert manifest["base_revision"] == "rev-1"
    assert manifest["source_scene_revision"] == "rev-1"
    assert manifest["grid_shape"] == [3, 4]
    for item in manifest["files"]:
        copied = prepared.snapshot_path / item["relative_path"]
        assert copied.stat().st_ino != (scene / item["relative_path"]).stat().st_ino
        assert _digest(copied) == item["sha256"]
        assert not copied.is_symlink()
    assert {path.name: path.read_bytes() for path in scene.iterdir() if path.is_file()} == before
    assert not (prepared.snapshot_path / "run_summary.json").exists()


def test_same_input_reuses_one_snapshot_and_a_new_revision_does_not(tmp_path: Path) -> None:
    scene = _scene(tmp_path / "scenes")
    root = tmp_path / "snaps"
    first = prepare_base_snapshot("demo", snapshot_root=root, scene_root=tmp_path / "scenes")
    second = prepare_base_snapshot("demo", snapshot_root=root, scene_root=tmp_path / "scenes")
    assert second.reused is True
    assert second.snapshot_id == first.snapshot_id
    old = {path.name: path.read_bytes() for path in first.snapshot_path.iterdir()}
    dem = np.load(scene / "dem_1m.npy")
    dem[0, 0] = 9
    np.save(scene / "dem_1m.npy", dem)
    metadata = json.loads((scene / "data_metadata.json").read_text(encoding="utf-8"))
    metadata["scene_revision"] = "rev-2"
    (scene / "data_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    third = prepare_base_snapshot("demo", snapshot_root=root, scene_root=tmp_path / "scenes")
    assert third.snapshot_id != first.snapshot_id
    assert third.reused is False
    assert {path.name: path.read_bytes() for path in first.snapshot_path.iterdir()} == old


def test_publish_failures_leave_no_ready_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _scene(tmp_path / "scenes")
    root = tmp_path / "snaps"

    def no_space(source: Path, target: Path):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("experiments.base_scene_snapshot._copy_hashed", no_space)
    with pytest.raises(SnapshotError) as copy_error:
        prepare_base_snapshot("demo", snapshot_root=root, scene_root=tmp_path / "scenes")
    assert copy_error.value.code == "snapshot_io"
    monkeypatch.undo()

    original = __import__("experiments.base_scene_snapshot", fromlist=["_write_text"])._write_text

    def fail_manifest(path: Path, text: str) -> None:
        if path.name == "manifest.json":
            raise OSError(28, "No space left on device")
        original(path, text)

    monkeypatch.setattr("experiments.base_scene_snapshot._write_text", fail_manifest)
    with pytest.raises(SnapshotError) as manifest_error:
        prepare_base_snapshot("demo", snapshot_root=root, scene_root=tmp_path / "scenes")
    assert manifest_error.value.code == "snapshot_io"
    monkeypatch.undo()

    def fail_ready(path: Path, text: str) -> None:
        if path.name == "READY":
            raise OSError(28, "No space left on device")
        original(path, text)

    monkeypatch.setattr("experiments.base_scene_snapshot._write_text", fail_ready)
    with pytest.raises(SnapshotError) as ready_error:
        prepare_base_snapshot("demo", snapshot_root=root, scene_root=tmp_path / "scenes")
    assert ready_error.value.code == "snapshot_io"
    monkeypatch.undo()

    def fail_replace(source, target) -> None:
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr("experiments.base_scene_snapshot.os.replace", fail_replace)
    with pytest.raises(SnapshotError) as publish_error:
        prepare_base_snapshot("demo", snapshot_root=root, scene_root=tmp_path / "scenes")
    assert publish_error.value.code == "snapshot_io"
    assert list((root).glob("*")) == [] or all(path.name.startswith(".") for path in root.iterdir())
    assert not list((root / ".staging").glob("*"))


def test_corrupt_snapshot_is_not_replaced_or_reread_from_the_scene(tmp_path: Path) -> None:
    _scene(tmp_path / "scenes")
    root = tmp_path / "snaps"
    prepared = prepare_base_snapshot("demo", snapshot_root=root, scene_root=tmp_path / "scenes")
    target = prepared.snapshot_path / "dem_1m.npy"
    target.chmod(0o644)
    target.write_bytes(target.read_bytes() + b"x")
    with pytest.raises(SnapshotError) as error:
        prepare_base_snapshot("demo", snapshot_root=root, scene_root=tmp_path / "scenes")
    assert error.value.code == "snapshot_hash_mismatch"
    with pytest.raises(SnapshotError) as verify_error:
        verify_base_snapshot(prepared.snapshot_id, snapshot_root=root)
    assert verify_error.value.code == "snapshot_hash_mismatch"
    assert target.read_bytes().endswith(b"x")


def test_incomplete_ready_missing_manifest_and_symlink_are_rejected(tmp_path: Path) -> None:
    _scene(tmp_path / "scenes")
    root = tmp_path / "snaps"
    prepared = prepare_base_snapshot("demo", snapshot_root=root, scene_root=tmp_path / "scenes")
    bare = root / ("ab" * 32)
    bare.mkdir()
    with pytest.raises(SnapshotError) as missing_ready:
        verify_base_snapshot(bare.name, snapshot_root=root)
    assert missing_ready.value.code == "snapshot_not_ready"
    ready_only = root / ("cd" * 32)
    ready_only.mkdir()
    (ready_only / "READY").write_text(ready_only.name + "\n", encoding="utf-8")
    with pytest.raises(SnapshotError) as missing_manifest:
        verify_base_snapshot(ready_only.name, snapshot_root=root)
    assert missing_manifest.value.code == "snapshot_incomplete"
    linked = prepared.snapshot_path / "landuse_1m.npy"
    linked.unlink()
    linked.symlink_to(tmp_path / "scenes" / "demo" / "landuse_1m.npy")
    with pytest.raises(SnapshotError) as symlink_error:
        verify_base_snapshot(prepared.snapshot_id, snapshot_root=root)
    assert symlink_error.value.code == "snapshot_symlink"
    with pytest.raises(SnapshotError) as path_error:
        verify_base_snapshot("../" + prepared.snapshot_id, snapshot_root=root)
    assert path_error.value.code == "snapshot_path_invalid"


def test_manifest_illegal_path_is_rejected(tmp_path: Path) -> None:
    identity = {
        "schema_version": 1,
        "base_scene_id": "demo",
        "base_frame_id": "frame",
        "base_revision": "rev-1",
        "source_scene_revision": "rev-1",
        "source_crs": "EPSG:3857",
        "grid_shape": [3, 4],
        "grid_transform": [1, 0, 100, 0, -1, 200],
        "total_bytes": 1,
        "files": [{"relative_path": "../secret.npy", "size_bytes": 1, "sha256": "abc", "dtype": None, "shape": None}],
    }
    snapshot_id = _identity_id(identity)
    directory = tmp_path / "snaps" / snapshot_id
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(
        json.dumps({**identity, "snapshot_id": snapshot_id}, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (directory / "READY").write_text(snapshot_id + "\n", encoding="utf-8")
    with pytest.raises(SnapshotError) as error:
        verify_base_snapshot(snapshot_id, snapshot_root=tmp_path / "snaps")
    assert error.value.code == "snapshot_integrity"


def test_scene_rejection_codes(tmp_path: Path) -> None:
    root = tmp_path / "scenes"
    snaps = tmp_path / "snaps"
    with pytest.raises(SnapshotError) as missing:
        prepare_base_snapshot("demo", snapshot_root=snaps, scene_root=root)
    assert missing.value.code == "scene_not_found"
    scene = root / "demo"
    scene.mkdir(parents=True)
    with pytest.raises(SnapshotError) as unbuilt:
        prepare_base_snapshot("demo", snapshot_root=snaps, scene_root=root)
    assert unbuilt.value.code == "scene_not_ready"
    _scene(root, revision="rev-1")
    (scene / ".roads-rebuilding").write_text("busy", encoding="utf-8")
    with pytest.raises(SnapshotError) as rebuilding:
        prepare_base_snapshot("demo", snapshot_root=snaps, scene_root=root)
    assert rebuilding.value.code == "scene_rebuilding"
    (scene / ".roads-rebuilding").unlink()
    metadata = json.loads((scene / "data_metadata.json").read_text(encoding="utf-8"))
    metadata["protected_farmland"] = {"registered": True}
    (scene / "data_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(SnapshotError) as farmland:
        prepare_base_snapshot("demo", snapshot_root=snaps, scene_root=root)
    assert farmland.value.code == "farmland_incomplete"
    with pytest.raises(SnapshotError) as escaped:
        prepare_base_snapshot("../demo", snapshot_root=snaps, scene_root=root)
    assert escaped.value.code == "scene_invalid"
    metadata["protected_farmland"] = None
    (scene / "data_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    outside = tmp_path / "outside.npy"
    np.save(outside, np.ones((3, 4), np.float32))
    dem = scene / "dem_1m.npy"
    dem.unlink()
    dem.symlink_to(outside)
    with pytest.raises(SnapshotError) as linked_input:
        prepare_base_snapshot("demo", snapshot_root=snaps, scene_root=root)
    assert linked_input.value.code == "snapshot_input_invalid"


def test_farmland_mask_and_metadata_are_copied_together(tmp_path: Path) -> None:
    _scene(tmp_path / "scenes", farmland=True, claim=True)
    prepared = prepare_base_snapshot("demo", snapshot_root=tmp_path / "snaps", scene_root=tmp_path / "scenes")
    names = {item["relative_path"] for item in prepared.manifest["files"]}
    assert "protected_farmland_mask_1m.npy" in names
    assert "protected_farmland_import.json" in names
    assert "protected_farmland.png" not in names


def test_scene_lock_blocks_another_process(tmp_path: Path) -> None:
    _scene(tmp_path / "scenes")
    flag = tmp_path / "held"
    holder = subprocess.Popen(
        [PYTHON, "-c",
         "import sys, time\nfrom experiments.scene_lock import scene_write_lock\n"
         "with scene_write_lock(sys.argv[1], sys.argv[2], blocking=True):\n"
         "    open(sys.argv[3], 'w', encoding='utf-8').write('held')\n"
         "    time.sleep(2)\n",
         "demo", str(tmp_path / "scenes"), str(flag)],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    deadline = time.monotonic() + 5
    while not flag.exists() and holder.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert flag.exists()
    with pytest.raises(SnapshotError) as error:
        prepare_base_snapshot("demo", snapshot_root=tmp_path / "snaps", scene_root=tmp_path / "scenes", timeout=0.3)
    assert error.value.code == "scene_busy"
    holder.wait(timeout=5)
    assert holder.returncode == 0


def test_two_processes_create_one_snapshot(tmp_path: Path) -> None:
    _scene(tmp_path / "scenes")
    script = (
        "import json, sys\n"
        "from experiments.base_scene_snapshot import prepare_base_snapshot\n"
        "result = prepare_base_snapshot(sys.argv[1], snapshot_root=sys.argv[2], scene_root=sys.argv[3])\n"
        "print(json.dumps({'id': result.snapshot_id, 'reused': result.reused}))\n"
    )
    first = subprocess.Popen(
        [PYTHON, "-c", script, "demo", str(tmp_path / "snaps"), str(tmp_path / "scenes")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    second = subprocess.Popen(
        [PYTHON, "-c", script, "demo", str(tmp_path / "snaps"), str(tmp_path / "scenes")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    out_a, err_a = first.communicate(timeout=30)
    out_b, err_b = second.communicate(timeout=30)
    assert first.returncode == 0, err_a
    assert second.returncode == 0, err_b
    left, right = json.loads(out_a), json.loads(out_b)
    assert left["id"] == right["id"]
    assert {left["reused"], right["reused"]} == {False, True}
    verify_base_snapshot(left["id"], snapshot_root=tmp_path / "snaps")


def test_snapshot_survives_the_creating_process(tmp_path: Path) -> None:
    _scene(tmp_path / "scenes")
    script = (
        "import json, sys\n"
        "from experiments.base_scene_snapshot import prepare_base_snapshot, verify_base_snapshot\n"
        "result = prepare_base_snapshot(sys.argv[1], snapshot_root=sys.argv[2], scene_root=sys.argv[3])\n"
        "verified = verify_base_snapshot(result.snapshot_id, snapshot_root=sys.argv[2])\n"
        "print(json.dumps({'id': result.snapshot_id, 'files': len(verified['files'])}))\n"
    )
    completed = _run(script, "demo", str(tmp_path / "snaps"), str(tmp_path / "scenes"))
    assert completed.returncode == 0, completed.stderr
    recorded = json.loads(completed.stdout)
    again = prepare_base_snapshot("demo", snapshot_root=tmp_path / "snaps", scene_root=tmp_path / "scenes")
    assert again.reused is True
    assert again.snapshot_id == recorded["id"]
    assert recorded["files"] >= 8


def test_catalog_is_idempotent_and_does_not_delete_files(tmp_path: Path) -> None:
    from backend.app.infrastructure.base_snapshot_repository import BaseSnapshotRepository, SnapshotCatalogConflict

    _scene(tmp_path / "scenes")
    prepared = prepare_base_snapshot("demo", snapshot_root=tmp_path / "snaps", scene_root=tmp_path / "scenes")
    repository = BaseSnapshotRepository(f"sqlite:///{tmp_path / 'catalog.sqlite3'}")
    repository.migrate()
    digest = manifest_sha256(prepared.manifest)
    assert register_ready_snapshot(repository, prepared.snapshot_id, snapshot_root=tmp_path / "snaps") is True
    assert register_ready_snapshot(repository, prepared.snapshot_id, snapshot_root=tmp_path / "snaps") is False
    assert repository.add_reference(prepared.snapshot_id, "probe", "once") is True
    assert repository.add_reference(prepared.snapshot_id, "probe", "once") is False
    changed = dict(prepared.manifest)
    with pytest.raises(SnapshotCatalogConflict):
        repository.register_snapshot({**changed, "base_revision": "other"}, digest)
    report = snapshot_usage_report(snapshot_root=tmp_path / "snaps", references=repository.reference_counts())
    assert report["ready_candidate_count"] == 1
    assert report["integrity_checked"] is False
    assert report["reference_count"] == 1
    assert report["unreferenced_candidate_count"] == 0
    assert prepared.snapshot_path.is_dir()

    def fail_register(manifest: dict, manifest_sha: str) -> bool:
        raise RuntimeError("db down")

    repository.register_snapshot = fail_register
    with pytest.raises(RuntimeError, match="db down"):
        register_ready_snapshot(repository, prepared.snapshot_id, snapshot_root=tmp_path / "snaps")
    verify_base_snapshot(prepared.snapshot_id, snapshot_root=tmp_path / "snaps")


def test_retention_and_catalog_do_not_own_snapshots(tmp_path: Path) -> None:
    from backend.app.infrastructure.experiment_catalog import ExperimentCatalog
    from experiments.auto_result_retention import retain_auto_results

    _scene(tmp_path / "scenes")
    output = tmp_path / "outputs"
    prepared = prepare_base_snapshot("demo", snapshot_root=output / "base-snapshots", scene_root=tmp_path / "scenes")
    experiment = output / "auto-site"
    experiment.mkdir()
    (experiment / "run_summary.json").write_text(json.dumps({
        "result_origin": "auto", "problem_type": "site", "scene_name": "demo", "owner_id": "owner",
        "completed_at": "2026-01-01T00:00:00+00:00", "algorithm": "guided_search",
    }), encoding="utf-8")
    listed = {record.id for record in ExperimentCatalog(output).list_experiments()}
    assert prepared.snapshot_id not in listed
    assert "base-snapshots" not in listed
    retain_auto_results(output, scene_name="demo", owner_id="owner", problem_type="site", trigger_id="auto-site")
    assert (prepared.snapshot_path / "READY").is_file()


def test_job_create_and_launchers_are_unchanged() -> None:
    import inspect

    from backend.app.application.service import JobService

    assert "snapshot_id" not in inspect.signature(JobService.create_job).parameters
    for path in (
        ROOT / "experiments/launch_site_run.py",
        ROOT / "experiments/launch_routing_run.py",
        ROOT / "backend/app/application/service.py",
        ROOT / "backend/app/api/routes.py",
        ROOT / "backend/app/api/workspace_routes.py",
    ):
        assert "base_scene_snapshot" not in path.read_text(encoding="utf-8")


def test_postgres_catalog_matches_sqlite(tmp_path: Path) -> None:
    url = os.getenv("TEST_ACCOUNT_DATABASE_URL", "")
    if not url:
        pytest.skip("requires an isolated TEST_ACCOUNT_DATABASE_URL")
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.path.lstrip("/") != "p1_account_repair" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        pytest.fail("refusing a database that is not the local p1_account_repair instance")
    import psycopg

    from backend.app.infrastructure.base_snapshot_repository import BaseSnapshotRepository

    with psycopg.connect(url) as connection:
        connection.execute("DROP TABLE IF EXISTS base_snapshot_references, base_scene_snapshots")
    _scene(tmp_path / "scenes")
    prepared = prepare_base_snapshot("demo", snapshot_root=tmp_path / "snaps", scene_root=tmp_path / "scenes")
    repository = BaseSnapshotRepository(url)
    repository.migrate()
    assert repository.register_snapshot(prepared.manifest, manifest_sha256(prepared.manifest)) is True
    assert repository.register_snapshot(prepared.manifest, manifest_sha256(prepared.manifest)) is False
    assert repository.add_reference(prepared.snapshot_id, "probe", "once") is True
    assert repository.add_reference(prepared.snapshot_id, "probe", "once") is False
    assert repository.reference_counts() == {prepared.snapshot_id: 1}
    with psycopg.connect(url) as connection:
        connection.execute("DROP TABLE IF EXISTS base_snapshot_references, base_scene_snapshots")


def _tree_bytes(path: Path) -> dict[str, bytes]:
    return {
        item.relative_to(path).as_posix(): item.read_bytes()
        for item in path.rglob("*")
        if item.is_file() and not item.is_symlink()
    }


def test_stable_snapshot_reuses_the_same_identity(tmp_path: Path) -> None:
    _scene(tmp_path / "scenes")
    root = tmp_path / "snaps"
    first = prepare_base_snapshot("demo", snapshot_root=root, scene_root=tmp_path / "scenes")
    second = prepare_base_snapshot("demo", snapshot_root=root, scene_root=tmp_path / "scenes")
    manifest = verify_base_snapshot(first.snapshot_id, snapshot_root=root)
    identity = {key: value for key, value in manifest.items() if key != "snapshot_id"}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert first.snapshot_id == digest == second.snapshot_id
    assert second.reused is True
    assert len({item["relative_path"] for item in manifest["files"]}) == len(manifest["files"])


def test_symlink_storage_paths_do_not_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scenes = tmp_path / "scenes"
    _scene(scenes)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "marker.txt").write_bytes(b"keep-outside")
    before = _tree_bytes(outside)

    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SnapshotError) as root_error:
        prepare_base_snapshot("demo", snapshot_root=linked_root, scene_root=scenes)
    assert root_error.value.code == "snapshot_symlink"

    parent = tmp_path / "parent-link"
    parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SnapshotError) as parent_error:
        prepare_base_snapshot("demo", snapshot_root=parent / "snaps", scene_root=scenes)
    assert parent_error.value.code == "snapshot_symlink"

    env_link = tmp_path / "env-link"
    env_link.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("BASE_SNAPSHOT_ROOT", str(env_link))
    with pytest.raises(SnapshotError) as env_error:
        prepare_base_snapshot("demo", scene_root=scenes)
    assert env_error.value.code == "snapshot_symlink"
    monkeypatch.delenv("BASE_SNAPSHOT_ROOT")

    root = tmp_path / "snaps"
    root.mkdir()
    (root / ".staging").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SnapshotError) as staging_error:
        prepare_base_snapshot("demo", snapshot_root=root, scene_root=scenes)
    assert staging_error.value.code == "snapshot_symlink"
    (root / ".staging").unlink()
    (root / ".locks").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SnapshotError) as lock_error:
        prepare_base_snapshot("demo", snapshot_root=root, scene_root=scenes)
    assert lock_error.value.code == "snapshot_symlink"
    (root / ".locks").unlink()
    assert _tree_bytes(outside) == before

    prepared = prepare_base_snapshot("demo", snapshot_root=root, scene_root=scenes)
    saved = tmp_path / "saved-snapshot"
    prepared.snapshot_path.rename(saved)
    prepared.snapshot_path.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SnapshotError) as final_error:
        prepare_base_snapshot("demo", snapshot_root=root, scene_root=scenes)
    assert final_error.value.code == "snapshot_symlink"
    assert _tree_bytes(outside) == before
    prepared.snapshot_path.unlink()
    saved.rename(root / prepared.snapshot_id)
    assert verify_base_snapshot(prepared.snapshot_id, snapshot_root=root)["snapshot_id"] == prepared.snapshot_id


def test_duplicate_and_illegal_manifest_paths_are_rejected(tmp_path: Path) -> None:
    _scene(tmp_path / "scenes")
    prepared = prepare_base_snapshot("demo", snapshot_root=tmp_path / "snaps", scene_root=tmp_path / "scenes")
    original = json.loads((prepared.snapshot_path / "manifest.json").read_text(encoding="utf-8"))

    def publish(identity: dict, mutate) -> str:
        import shutil
        snapshot_id = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        directory = tmp_path / "crafted" / snapshot_id
        shutil.copytree(prepared.snapshot_path, directory)
        for child in directory.iterdir():
            child.chmod(0o644)
        mutate(directory)
        (directory / "manifest.json").write_text(
            json.dumps({**identity, "snapshot_id": snapshot_id}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (directory / "READY").write_text(snapshot_id + "\n", encoding="utf-8")
        return snapshot_id

    duplicated = {key: value for key, value in original.items() if key != "snapshot_id"}
    duplicated["files"] = [*duplicated["files"], duplicated["files"][0]]
    duplicated["total_bytes"] = sum(item["size_bytes"] for item in duplicated["files"])
    duplicated_id = publish(duplicated, lambda directory: None)
    with pytest.raises(SnapshotError) as duplicate_error:
        verify_base_snapshot(duplicated_id, snapshot_root=tmp_path / "crafted")
    assert duplicate_error.value.code == "snapshot_integrity"
    assert "重复" in str(duplicate_error.value)

    missing = {key: value for key, value in original.items() if key != "snapshot_id"}
    missing["files"] = [item for item in missing["files"] if item["relative_path"] != "dem_1m.npy"]
    missing["total_bytes"] = sum(item["size_bytes"] for item in missing["files"])
    missing_id = publish(missing, lambda directory: (directory / "dem_1m.npy").unlink())
    with pytest.raises(SnapshotError) as missing_error:
        verify_base_snapshot(missing_id, snapshot_root=tmp_path / "crafted")
    assert missing_error.value.code == "snapshot_incomplete"

    unknown = {key: value for key, value in original.items() if key != "snapshot_id"}
    unknown["files"] = [*unknown["files"], {
        "relative_path": "notes.txt",
        "size_bytes": 4,
        "sha256": hashlib.sha256(b"note").hexdigest(),
        "dtype": None,
        "shape": None,
    }]
    unknown["total_bytes"] = sum(item["size_bytes"] for item in unknown["files"])
    unknown_id = publish(unknown, lambda directory: (directory / "notes.txt").write_bytes(b"note"))
    with pytest.raises(SnapshotError) as unknown_error:
        verify_base_snapshot(unknown_id, snapshot_root=tmp_path / "crafted")
    assert unknown_error.value.code == "snapshot_integrity"
    assert "非法路径" in str(unknown_error.value)
    assert verify_base_snapshot(prepared.snapshot_id, snapshot_root=tmp_path / "snaps")["snapshot_id"] == prepared.snapshot_id


def test_usage_report_does_not_verify_snapshot_bytes(tmp_path: Path) -> None:
    _scene(tmp_path / "scenes")
    prepared = prepare_base_snapshot("demo", snapshot_root=tmp_path / "snaps", scene_root=tmp_path / "scenes")
    target = prepared.snapshot_path / "demand_points.npy"
    target.chmod(0o644)
    target.write_bytes(target.read_bytes() + b"x")
    report = snapshot_usage_report(snapshot_root=tmp_path / "snaps", references={})
    assert report["integrity_checked"] is False
    assert prepared.snapshot_id in report["ready_candidate_ids"]
    with pytest.raises(SnapshotError) as error:
        verify_base_snapshot(prepared.snapshot_id, snapshot_root=tmp_path / "snaps")
    assert error.value.code == "snapshot_hash_mismatch"
