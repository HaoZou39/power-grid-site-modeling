"""One batch publish matches sequential edits and does not publish twice."""

from __future__ import annotations

import threading
import time
import tracemalloc
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from experiments.haul_field_cache import scene_source_signature
from experiments.landuse_edits import (
    LanduseRevisionConflict,
    create_landuse_edit,
    delete_landuse_edit,
    landuse_edit_snapshot,
    replace_landuse_edits,
    update_landuse_edit,
)
from experiments.scene_lock import CoordinateSceneError
from experiments.scene_version import scene_data_version, write_scene_revision


def _scene(directory: Path, shape: tuple[int, int] = (8, 9)) -> np.ndarray:
    directory.mkdir(parents=True, exist_ok=True)
    landuse = np.zeros(shape, dtype=np.uint8)
    landuse[2:6, 2:6] = 4
    np.save(directory / "landuse_1m.npy", landuse)
    np.save(directory / "obstacle_mask_1m.npy", np.zeros(shape, dtype=np.uint8))
    return landuse


def _signature_inputs(directory: Path) -> None:
    shape = np.load(directory / "landuse_1m.npy").shape
    np.save(directory / "dem_1m.npy", np.zeros(shape, dtype=np.float32))
    np.save(directory / "road_segments_local.npy", np.array([[0.0, 0.0, 1.0, 1.0]]))
    np.save(directory / "road_segment_kind.npy", np.array([0], dtype=np.int8))
    np.save(directory / "protected_farmland_mask_1m.npy", np.zeros(shape, dtype=bool))


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}


def _products(directory: Path) -> tuple[np.ndarray, np.ndarray, bytes]:
    return (
        np.load(directory / "landuse_1m.npy"),
        np.load(directory / "obstacle_mask_1m.npy"),
        (directory / "obstacle_overlay.png").read_bytes(),
    )


def _item(edit_id: str, class_id: int, points: list[tuple[float, float]]) -> dict:
    return {"id": edit_id, "class_id": class_id, "points": points}


def test_batch_matches_sequential_edits_and_keeps_ids_and_order(tmp_path: Path) -> None:
    sequential = tmp_path / "scenes" / "sequential"
    batched = tmp_path / "scenes" / "batched"
    original = _scene(sequential)
    _scene(batched)
    big = [(1, 1), (7, 1), (7, 7), (1, 7)]
    overlap = [(3, 3), (5, 3), (5, 5), (3, 5)]
    first = create_landuse_edit("sequential", 1, big, tmp_path / "scenes")
    second = create_landuse_edit("sequential", 5, overlap, tmp_path / "scenes")
    updated = update_landuse_edit("sequential", second[1]["id"], [(3, 3), (5, 3), (5, 5)], tmp_path / "scenes")
    added = create_landuse_edit("sequential", 3, [(0, 0), (2, 0), (2, 2)], tmp_path / "scenes")
    final = delete_landuse_edit("sequential", added[2]["id"], tmp_path / "scenes")

    published = replace_landuse_edits("batched", scene_data_version(batched)["scene_revision"], final, tmp_path / "scenes")
    assert published["changed"] is True
    assert [item["id"] for item in published["items"]] == [item["id"] for item in final]
    assert published["items"] == final
    assert np.array_equal(*[np.load(path / "landuse_1m.npy") for path in (sequential, batched)])
    assert np.array_equal(*[np.load(path / "obstacle_mask_1m.npy") for path in (sequential, batched)])
    assert (sequential / "obstacle_overlay.png").read_bytes() == (batched / "obstacle_overlay.png").read_bytes()
    assert not np.array_equal(np.load(batched / "landuse_1m.npy"), original)
    assert published["scene_revision"] == scene_data_version(batched)["scene_revision"]
    assert published["scene_revision"] != scene_data_version(tmp_path / "scenes" / "sequential")["scene_revision"]


def test_overlap_follows_list_order_and_empty_batch_restores_the_base(tmp_path: Path) -> None:
    directory = tmp_path / "scenes" / "demo"
    _scene(directory)
    field = _item("field", 1, [(1, 1), (7, 1), (7, 7), (1, 7)])
    water = _item("water", 5, [(3, 3), (6, 3), (6, 6), (3, 6)])
    water_on_field = replace_landuse_edits("demo", scene_data_version(directory)["scene_revision"], [field, water], tmp_path / "scenes")
    assert np.load(directory / "landuse_1m.npy")[4, 4] == 5
    field_on_water = replace_landuse_edits("demo", water_on_field["scene_revision"], [water, field], tmp_path / "scenes")
    assert np.load(directory / "landuse_1m.npy")[4, 4] == 1
    cleared = replace_landuse_edits("demo", field_on_water["scene_revision"], [], tmp_path / "scenes")
    assert cleared["changed"] is True
    assert cleared["items"] == []
    assert np.array_equal(np.load(directory / "landuse_1m.npy"), _scene(tmp_path / "unused"))
    assert np.all(np.load(directory / "obstacle_mask_1m.npy") == 0)


def test_unchanged_batch_does_not_publish_or_invalidate_the_haul_identity(tmp_path: Path) -> None:
    directory = tmp_path / "scenes" / "demo"
    _scene(directory)
    _signature_inputs(directory)
    farmland = (directory / "protected_farmland_mask_1m.npy").read_bytes()
    revision = scene_data_version(directory)["scene_revision"]
    item = _item("pond", 5, [(2, 2), (6, 2), (6, 6), (2, 6)])
    first = replace_landuse_edits("demo", revision, [item], tmp_path / "scenes")
    signature = scene_source_signature(directory, uses_landuse=True)
    files = _snapshot(directory)
    second = replace_landuse_edits("demo", first["scene_revision"], first["items"], tmp_path / "scenes")
    assert second["changed"] is False
    assert second["scene_revision"] == first["scene_revision"]
    assert second["items"] == first["items"]
    assert _snapshot(directory) == files
    assert scene_source_signature(directory, uses_landuse=True) == signature
    assert (directory / "protected_farmland_mask_1m.npy").read_bytes() == farmland
    changed = replace_landuse_edits("demo", second["scene_revision"], [], tmp_path / "scenes")
    assert changed["changed"] is True
    assert scene_source_signature(directory, uses_landuse=True) != signature
    assert (directory / "protected_farmland_mask_1m.npy").read_bytes() == farmland


def test_stale_revision_invalid_geometry_and_duplicate_ids_write_nothing(tmp_path: Path) -> None:
    directory = tmp_path / "scenes" / "demo"
    _scene(directory)
    revision = scene_data_version(directory)["scene_revision"]
    item = _item("pond", 5, [(2, 2), (6, 2), (6, 6), (2, 6)])
    published = replace_landuse_edits("demo", revision, [item], tmp_path / "scenes")
    files = _snapshot(directory)
    with pytest.raises(LanduseRevisionConflict) as conflict:
        replace_landuse_edits("demo", revision, [], tmp_path / "scenes")
    assert conflict.value.scene_revision == published["scene_revision"]
    assert _snapshot(directory) == files

    fresh = tmp_path / "scenes" / "fresh"
    _scene(fresh)
    before = _snapshot(fresh)
    with pytest.raises(ValueError, match="area"):
        replace_landuse_edits("fresh", scene_data_version(fresh)["scene_revision"], [
            _item("bad", 1, [(1, 1), (2, 2), (3, 3)]),
        ], tmp_path / "scenes")
    with pytest.raises(ValueError, match="class_id"):
        replace_landuse_edits("fresh", scene_data_version(fresh)["scene_revision"], [
            _item("bad", 4, [(1, 1), (4, 1), (4, 4)]),
        ], tmp_path / "scenes")
    with pytest.raises(ValueError, match="unique"):
        replace_landuse_edits("fresh", scene_data_version(fresh)["scene_revision"], [item, dict(item)], tmp_path / "scenes")
    assert _snapshot(fresh) == before
    assert not (fresh / "landuse_base_1m.npy").exists()
    assert not (fresh / "landuse_edits.json").exists()


def test_read_only_scene_and_batch_limits_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "scenes" / "demo"
    _scene(directory)
    (directory / "scene.json").write_text('{"read_only": true}', encoding="utf-8")
    before = _snapshot(directory)
    with pytest.raises(ValueError, match="封存"):
        replace_landuse_edits("demo", scene_data_version(directory)["scene_revision"], [
            _item("pond", 5, [(2, 2), (5, 2), (5, 5)]),
        ], tmp_path / "scenes")
    assert _snapshot(directory) == before

    monkeypatch.setattr("experiments.landuse_edits._validate_ring", lambda points, shape: [[float(point[0]), float(point[1])] for point in points])
    writable = tmp_path / "scenes" / "open"
    _scene(writable)
    too_many = [_item(f"e{index}", 1, [(0, 0), (1, 0), (1, 1)]) for index in range(129)]
    with pytest.raises(ValueError, match="128"):
        replace_landuse_edits("open", scene_data_version(writable)["scene_revision"], too_many, tmp_path / "scenes")
    huge = [_item("huge", 1, [(0, 0)] * 8001)]
    with pytest.raises(ValueError, match="8000"):
        replace_landuse_edits("open", scene_data_version(writable)["scene_revision"], huge, tmp_path / "scenes")
    assert not (writable / "landuse_edits.json").exists()


def test_failed_publish_restores_files_and_blocks_readers_until_then(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "scenes" / "demo"
    _scene(directory)
    (directory / "data_metadata.json").write_text('{"scene_revision": "original", "dem": {"shape": [8, 9]}}', encoding="utf-8")
    before = _snapshot(directory)
    revision = scene_data_version(directory)["scene_revision"]
    entered = threading.Event()
    release = threading.Event()

    def fail_after_grids(scene_dir: Path, metadata: dict | None = None) -> dict:
        entered.set()
        assert release.wait(2)
        raise RuntimeError("metadata disk full")

    monkeypatch.setattr("experiments.scene_version.write_scene_revision", fail_after_grids)
    seen: list[tuple[list, str]] = []

    def publish() -> None:
        with pytest.raises(RuntimeError, match="disk full"):
            replace_landuse_edits("demo", revision, [_item("pond", 5, [(2, 2), (6, 2), (6, 6), (2, 6)])], tmp_path / "scenes")

    worker = threading.Thread(target=publish)
    worker.start()
    assert entered.wait(2)
    reader = threading.Thread(target=lambda: seen.append(landuse_edit_snapshot("demo", tmp_path / "scenes")))
    reader.start()
    time.sleep(0.05)
    assert reader.is_alive()
    release.set()
    worker.join(2)
    reader.join(2)
    assert seen == [([], "original")]
    assert _snapshot(directory) == before
    assert list(directory.glob("*.bak")) == []


def test_a_second_client_cannot_publish_over_the_lock_or_a_stale_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "scenes" / "demo"
    _scene(directory)
    revision = scene_data_version(directory)["scene_revision"]
    entered = threading.Event()
    release = threading.Event()
    real_write = write_scene_revision

    def wait_then_write(scene_dir: Path, metadata: dict | None = None) -> dict:
        entered.set()
        assert release.wait(2)
        return real_write(scene_dir, metadata)

    monkeypatch.setattr("experiments.scene_version.write_scene_revision", wait_then_write)
    outcome: dict[str, object] = {}

    def first() -> None:
        outcome["first"] = replace_landuse_edits("demo", revision, [
            _item("first", 5, [(1, 1), (4, 1), (4, 4)]),
        ], tmp_path / "scenes")

    def second() -> None:
        try:
            replace_landuse_edits("demo", revision, [_item("second", 1, [(4, 4), (7, 4), (7, 7)])], tmp_path / "scenes")
        except Exception as exc:
            outcome["second"] = exc

    first_thread = threading.Thread(target=first)
    first_thread.start()
    assert entered.wait(2)
    second_thread = threading.Thread(target=second)
    second_thread.start()
    second_thread.join(2)
    assert isinstance(outcome["second"], CoordinateSceneError)
    release.set()
    first_thread.join(2)
    assert np.load(directory / "landuse_1m.npy")[2, 2] == 5
    assert np.load(directory / "landuse_1m.npy")[6, 6] != 1
    published = outcome["first"]
    assert isinstance(published, dict)
    with pytest.raises(LanduseRevisionConflict):
        replace_landuse_edits("demo", revision, [], tmp_path / "scenes")
    assert landuse_edit_snapshot("demo", tmp_path / "scenes")[0] == published["items"]


def test_batch_http_contract_keeps_single_edit_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "scenes" / "demo"
    _scene(directory)
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path / "scenes"))
    client = TestClient(create_app("sqlite://:memory:", ""))
    listed = client.get("/api/v1/scenes/demo/landuse-edits")
    assert listed.status_code == 200
    revision = listed.json()["scene_revision"]
    created = client.post("/api/v1/scenes/demo/landuse-edits", json={
        "class_id": 1, "points": [[1, 1], [3, 1], [3, 3]],
    })
    assert created.status_code == 200
    kept = created.json()["items"][0]
    current = client.get("/api/v1/scenes/demo/landuse-edits").json()["scene_revision"]
    body = {
        "expected_scene_revision": current,
        "items": [
            kept,
            {"id": "pond", "class_id": 5, "points": [[3, 3], [6, 3], [6, 6], [3, 6]]},
        ],
    }
    published = client.post("/api/v1/scenes/demo/landuse-edits/batch", json=body)
    assert published.status_code == 200
    payload = published.json()
    assert payload["changed"] is True
    assert [item["id"] for item in payload["items"]] == [kept["id"], "pond"]
    assert np.load(directory / "landuse_1m.npy")[4, 4] == 5
    same = client.post("/api/v1/scenes/demo/landuse-edits/batch", json={
        "expected_scene_revision": payload["scene_revision"],
        "items": payload["items"],
    })
    assert same.status_code == 200
    assert same.json()["changed"] is False
    assert same.json()["scene_revision"] == payload["scene_revision"]
    conflict = client.post("/api/v1/scenes/demo/landuse-edits/batch", json=body)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["scene_revision"] == payload["scene_revision"]
    assert client.post("/api/v1/scenes/demo/landuse-edits/batch", json={
        "expected_scene_revision": payload["scene_revision"],
        "items": [kept, kept],
    }).status_code == 422
    assert client.put(
        f"/api/v1/scenes/demo/landuse-edits/{kept['id']}",
        json={"points": [[1, 1], [4, 1], [4, 4]]},
    ).status_code == 200
    assert client.delete(f"/api/v1/scenes/demo/landuse-edits/{kept['id']}").status_code == 200


def test_five_single_edits_publish_five_times_and_one_batch_publishes_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shape = (256, 256)
    single = tmp_path / "scenes" / "single"
    batch = tmp_path / "scenes" / "batch"
    _scene(single, shape)
    _scene(batch, shape)
    rings = [
        [(20, 20), (80, 20), (80, 80), (20, 80)],
        [(40, 40), (100, 40), (100, 100), (40, 100)],
        [(120, 20), (200, 20), (200, 90), (120, 90)],
        [(30, 140), (110, 140), (110, 220), (30, 220)],
        [(140, 140), (220, 140), (220, 220), (140, 220)],
    ]
    classes = [1, 5, 3, 2, 5]
    calls = {"apply": 0, "array": 0, "png": 0, "revision": 0}
    import experiments.landuse_edits as edits
    import experiments.scene_version as versions

    real_apply = edits._apply
    real_array = edits._atomic_save_array
    real_png = edits.write_obstacle_overlay
    real_revision = versions.write_scene_revision

    def count_apply(*args, **kwargs):
        calls["apply"] += 1
        return real_apply(*args, **kwargs)

    def count_array(*args, **kwargs):
        calls["array"] += 1
        return real_array(*args, **kwargs)

    def count_png(*args, **kwargs):
        calls["png"] += 1
        return real_png(*args, **kwargs)

    def count_revision(*args, **kwargs):
        calls["revision"] += 1
        return real_revision(*args, **kwargs)

    monkeypatch.setattr(edits, "_apply", count_apply)
    monkeypatch.setattr(edits, "_atomic_save_array", count_array)
    monkeypatch.setattr(edits, "write_obstacle_overlay", count_png)
    monkeypatch.setattr(versions, "write_scene_revision", count_revision)
    tracemalloc.start()
    started = time.perf_counter()
    for class_id, ring in zip(classes, rings):
        create_landuse_edit("single", class_id, ring, tmp_path / "scenes")
    single_seconds = time.perf_counter() - started
    _single_current, single_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    single_calls = dict(calls)
    calls.update({"apply": 0, "array": 0, "png": 0, "revision": 0})
    items = [_item(f"edit-{index}", class_id, ring) for index, (class_id, ring) in enumerate(zip(classes, rings))]
    tracemalloc.start()
    started = time.perf_counter()
    replace_landuse_edits("batch", scene_data_version(batch)["scene_revision"], items, tmp_path / "scenes")
    batch_seconds = time.perf_counter() - started
    _batch_current, batch_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert single_calls == {"apply": 5, "array": 11, "png": 5, "revision": 5}
    assert calls == {"apply": 1, "array": 3, "png": 1, "revision": 1}
    assert np.array_equal(np.load(single / "landuse_1m.npy"), np.load(batch / "landuse_1m.npy"))
    assert np.array_equal(np.load(single / "obstacle_mask_1m.npy"), np.load(batch / "obstacle_mask_1m.npy"))
    print(
        f"PERF single_s={single_seconds:.3f} batch_s={batch_seconds:.3f} "
        f"single_peak={single_peak} batch_peak={batch_peak} "
        f"single_calls={single_calls} batch_calls={calls}"
    )
