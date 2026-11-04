"""CAD attachments persist independently from map data and optimization."""
import hashlib
import json
from pathlib import Path
import shutil
import threading

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from experiments import scene_cad_files as cad
from experiments import scene_store
from experiments.landuse_edits import CAD_METADATA_FILE
from experiments.scene_lock import SceneBusyError
from experiments.scene_version import scene_data_version
from test_road_import import road_trial


@pytest.fixture
def cad_client(tmp_path, road_trial, monkeypatch):
    scene, _ = road_trial
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    app = create_app("sqlite://:memory:", "", favorite_db_path=tmp_path / "favorites.sqlite3")
    return TestClient(app), scene


def test_upload_list_and_distinct_names_preserve_bytes_and_scene_version(cad_client):
    client, scene = cad_client
    url = "/api/v1/scenes/demo/cad-files"
    version = scene_data_version(scene)
    original = {path.name: path.read_bytes() for path in scene.iterdir() if path.is_file()}
    assert client.get(url).json() == []
    records = []
    for name, payload in (("甲.dwg", b"first drawing"), ("乙.dxf", b"second drawing")):
        response = client.post(url, files={"file": (name, payload)})
        assert response.status_code == 201, response.text
        record = response.json()
        assert record["source_name"] == name
        assert record["reused"] is False
        assert record["size_bytes"] == len(payload)
        suffix = Path(name).suffix.lower()
        assert (scene / cad.CAD_DIRECTORY / record["id"] / f"source{suffix}").read_bytes() == payload
        records.append(record)
    assert records[0]["id"] != records[1]["id"]
    listed = client.get(url).json()
    assert [item["id"] for item in listed] == [records[1]["id"], records[0]["id"]]
    assert scene_data_version(scene) == version
    assert {name: (scene / name).read_bytes() for name in original} == original


@pytest.mark.parametrize("filename,payload", [("bad.zip", b"zip"), ("empty.dwg", b""), ("drawing", b"cad")])
def test_invalid_upload_is_rejected_without_publishing(cad_client, filename, payload):
    client, scene = cad_client
    response = client.post("/api/v1/scenes/demo/cad-files", files={"file": (filename, payload)})
    assert response.status_code == 400, response.text
    assert cad.list_cad_files(scene) == []


def test_size_limit_and_missing_scene(cad_client, monkeypatch):
    client, scene = cad_client
    monkeypatch.setattr(cad, "MAX_CAD_BYTES", 8)
    assert client.post("/api/v1/scenes/demo/cad-files", files={"file": ("big.dxf", b"x" * 9)}).status_code == 413
    assert client.post("/api/v1/scenes/missing/cad-files", files={"file": ("ok.dxf", b"cad")}).status_code == 404
    assert client.get("/api/v1/scenes/missing/cad-files").status_code == 404
    assert cad.list_cad_files(scene) == []


def test_busy_and_archived_scenes_cannot_upload(cad_client, monkeypatch):
    client, scene = cad_client
    repository = client.app.state.job_service.repository
    with monkeypatch.context() as patch:
        patch.setattr(repository, "active_scene_names", lambda: {"demo"})
        response = client.post("/api/v1/scenes/demo/cad-files", files={"file": ("ok.dwg", b"cad")})
        assert response.status_code == 409, response.text
    (scene / "scene.json").write_text(json.dumps({"read_only": True}))
    assert client.post("/api/v1/scenes/demo/cad-files", files={"file": ("ok.dwg", b"cad")}).status_code == 400
    assert cad.list_cad_files(scene) == []


def test_client_filename_never_controls_storage_path(road_trial):
    scene, _ = road_trial
    record = cad.add_cad_file(scene, "..\\..\\outside.DXF", b"drawing")
    assert record["source_name"] == "outside.DXF"
    assert (scene / cad.CAD_DIRECTORY / record["id"] / "source.dxf").read_bytes() == b"drawing"
    assert not (scene.parent / "outside.DXF").exists()


def test_failed_publish_leaves_no_partial_attachment(road_trial, monkeypatch):
    scene, _ = road_trial
    def fail(*args):
        raise OSError("publish failed")
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="publish failed"):
        cad.add_cad_file(scene, "drawing.dwg", b"drawing")
    assert list((scene / cad.CAD_DIRECTORY).iterdir()) == []


def _plant(scene: Path, cad_id: str, name: str, payload: bytes, *, sha: bool = True) -> dict:
    record = {"id": cad_id, "source_name": name, "size_bytes": len(payload),
              "uploaded_at": "2020-01-01T00:00:00+00:00", "active": False}
    if sha:
        record["sha256"] = hashlib.sha256(payload).hexdigest()
    directory = scene / cad.CAD_DIRECTORY / cad_id
    directory.mkdir(parents=True)
    (directory / ("source" + Path(name).suffix.lower())).write_bytes(payload)
    (directory / "metadata.json").write_text(json.dumps(record) + "\n", encoding="utf-8")
    return record


def test_same_bytes_reuse_existing_attachment(cad_client):
    client, scene = cad_client
    url = "/api/v1/scenes/demo/cad-files"
    first = client.post(url, files={"file": ("苍南莒溪镇.dwg", b"same drawing")})
    assert first.status_code == 201, first.text
    again = client.post(url, files={"file": ("苍南莒溪镇.DWG", b"same drawing")})
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["reused"] is True
    assert again.json()["source_name"] == "苍南莒溪镇.dwg"
    assert len(client.get(url).json()) == 1
    assert (scene / cad.CAD_DIRECTORY / first.json()["id"] / "source.dwg").read_bytes() == b"same drawing"


def test_same_name_different_bytes_requires_confirmation_and_cancel_keeps_original(cad_client):
    client, scene = cad_client
    url = "/api/v1/scenes/demo/cad-files"
    first = client.post(url, files={"file": ("苍南.dwg", b"original")}).json()
    conflict = client.post(url, files={"file": ("苍南.DWG", b"replacement")})
    assert conflict.status_code == 409, conflict.text
    detail = conflict.json()["detail"]
    assert detail["code"] == "cad_name_conflict"
    assert [item["id"] for item in detail["matches"]] == [first["id"]]
    assert (scene / cad.CAD_DIRECTORY / first["id"] / "source.dwg").read_bytes() == b"original"
    assert len(list((scene / cad.CAD_DIRECTORY).iterdir())) == 1


def test_replace_updates_only_the_chosen_id_and_drops_its_preview(road_trial):
    scene, _ = road_trial
    version = scene_data_version(scene)
    original = {path.name: path.read_bytes() for path in scene.iterdir() if path.is_file()}
    first = _plant(scene, "a" * 32, "同名.dwg", b"first")
    second = _plant(scene, "b" * 32, "同名.dwg", b"second")
    other = scene.parent / "other-scene" / cad.CAD_DIRECTORY / ("c" * 32)
    other.mkdir(parents=True)
    (other / "source.dwg").write_bytes(b"other-scene")
    kept = scene / "hand_feasible.txt"
    kept.write_bytes(b"hand-drawn zones stay")
    preview = scene.parent / ".import-previews" / scene.name / ("d" * 32)
    preview.mkdir(parents=True)
    (preview / "summary.json").write_text(json.dumps({"cad_id": first["id"], "sha256": first["sha256"]}), encoding="utf-8")
    with pytest.raises(cad.CadNameConflict) as caught:
        cad.add_cad_file(scene, "同名.DWG", b"third")
    assert {item["id"] for item in caught.value.matches} == {first["id"], second["id"]}
    updated = cad.replace_cad_file(scene, first["id"], "同名.dwg", b"third")
    assert updated["id"] == first["id"]
    assert "reused" not in updated
    assert (scene / cad.CAD_DIRECTORY / first["id"] / "source.dwg").read_bytes() == b"third"
    assert (scene / cad.CAD_DIRECTORY / second["id"] / "source.dwg").read_bytes() == b"second"
    assert not preview.exists()
    with pytest.raises(ValueError, match="已变化"):
        cad.assert_preview_current(scene, {"cad_id": first["id"], "sha256": first["sha256"]})
    assert (other / "source.dwg").read_bytes() == b"other-scene"
    assert kept.read_bytes() == b"hand-drawn zones stay"
    assert scene_data_version(scene) == version
    assert {name: (scene / name).read_bytes() for name in original} == original


def test_replace_failure_keeps_the_original_bytes(road_trial, monkeypatch):
    scene, _ = road_trial
    record = cad.add_cad_file(scene, "drawing.dwg", b"original")

    def fail(self, target):
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="replace failed"):
        cad.replace_cad_file(scene, record["id"], "drawing.dwg", b"changed")
    assert (scene / cad.CAD_DIRECTORY / record["id"] / "source.dwg").read_bytes() == b"original"


def test_delete_removes_one_attachment_and_protects_the_active_landuse_source(cad_client):
    client, scene = cad_client
    url = "/api/v1/scenes/demo/cad-files"
    first = client.post(url, files={"file": ("甲.dwg", b"keep-me")}).json()
    second = client.post(url, files={"file": ("乙.dwg", b"remove-me")}).json()
    kept = scene / "hand_feasible.txt"
    kept.write_bytes(b"hand-drawn zones stay")
    version = scene_data_version(scene)
    assert client.delete(f"{url}/{second['id']}").status_code == 204
    assert [item["id"] for item in client.get(url).json()] == [first["id"]]
    assert (scene / cad.CAD_DIRECTORY / first["id"] / "source.dwg").read_bytes() == b"keep-me"
    assert kept.read_bytes() == b"hand-drawn zones stay"
    assert scene_data_version(scene) == version
    (scene / CAD_METADATA_FILE).write_text(json.dumps({"cad_id": first["id"]}), encoding="utf-8")
    blocked = client.delete(f"{url}/{first['id']}")
    assert blocked.status_code == 400, blocked.text
    assert "撤销 CAD 分类" in blocked.json()["detail"]["message"]
    replaced = client.post(f"{url}/{first['id']}/replace", files={"file": ("甲.dwg", b"new-bytes")})
    assert replaced.status_code == 400, replaced.text
    assert (scene / cad.CAD_DIRECTORY / first["id"] / "source.dwg").read_bytes() == b"keep-me"
    assert client.delete(f"{url}/{'e' * 32}").status_code == 404
    assert client.delete(f"{url}/not-a-cad-id").status_code == 400


def test_legacy_attachment_without_hash_still_lists_and_matches_same_bytes(cad_client):
    client, scene = cad_client
    record = _plant(scene, "f" * 32, "legacy.dwg", b"legacy", sha=False)
    listed = client.get("/api/v1/scenes/demo/cad-files")
    assert listed.status_code == 200, listed.text
    assert listed.json() == [{"id": record["id"], "source_name": "legacy.dwg", "size_bytes": 6,
                              "uploaded_at": record["uploaded_at"], "active": False, "reused": False}]
    again = client.post("/api/v1/scenes/demo/cad-files", files={"file": ("legacy.DWG", b"legacy")})
    assert again.status_code == 200, again.text
    assert again.json()["id"] == record["id"]
    assert again.json()["reused"] is True
    cad.assert_preview_current(scene, {"cad_id": record["id"]})


def test_concurrent_uploads_do_not_leave_a_partial_or_duplicate_attachment(road_trial):
    scene, _ = road_trial
    barrier = threading.Barrier(2)
    outcomes = []

    def upload():
        barrier.wait()
        try:
            outcomes.append(cad.add_cad_file(scene, "并发.dwg", b"same-bytes"))
        except SceneBusyError as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=upload) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(outcomes) == 2
    records = cad.list_cad_files(scene)
    assert len(records) == 1
    assert (scene / cad.CAD_DIRECTORY / records[0]["id"] / "source.dwg").read_bytes() == b"same-bytes"
    assert [path.name for path in (scene / cad.CAD_DIRECTORY).iterdir() if path.name.startswith(".")] == []


def test_scene_rebuild_retains_cad_attachments(tmp_path, road_trial, monkeypatch):
    scene, _ = road_trial
    record = cad.add_cad_file(scene, "drawing.dwg", b"retained drawing")
    sources = {}
    for key in ("dem_path", "landuse_path", "osm_roads_path", "reference_geotiff_path"):
        path = tmp_path / key
        path.write_text("source")
        sources[key] = path
    metadata = json.loads((scene / scene_store.SCENE_METADATA).read_text())
    def prepared(config, target, on_step, **kwargs):
        target.mkdir(parents=True)
        for name in scene_store.SCENE_ARRAYS:
            shutil.copyfile(scene / name, target / name)
        return {}, metadata
    monkeypatch.setattr("experiments.problem_context.write_scene_products", prepared)
    scene_store.prepare_scene_from_sources("demo", sources, lambda *args: None,
                                          title="Demo", source_site_id="demo", root=scene.parent)
    assert cad.list_cad_files(scene) == [record]
    assert (scene / cad.CAD_DIRECTORY / record["id"] / "source.dwg").read_bytes() == b"retained drawing"
