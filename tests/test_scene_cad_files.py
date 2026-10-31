"""CAD attachments persist independently from map data and optimization."""
import json
from pathlib import Path
import shutil

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from experiments import scene_cad_files as cad
from experiments import scene_store
from experiments.scene_version import scene_data_version
from test_road_import import road_trial


@pytest.fixture
def cad_client(tmp_path, road_trial, monkeypatch):
    scene, _ = road_trial
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    app = create_app("sqlite://:memory:", "", favorite_db_path=tmp_path / "favorites.sqlite3")
    return TestClient(app), scene


def test_upload_list_and_same_name_preserve_bytes_and_scene_version(cad_client):
    client, scene = cad_client
    url = "/api/v1/scenes/demo/cad-files"
    version = scene_data_version(scene)
    original = {path.name: path.read_bytes() for path in scene.iterdir() if path.is_file()}
    assert client.get(url).json() == []
    records = []
    for payload in (b"first drawing", b"second drawing"):
        response = client.post(url, files={"file": ("苍南莒溪镇.DWG", payload)})
        assert response.status_code == 201, response.text
        record = response.json()
        assert record["source_name"] == "苍南莒溪镇.DWG"
        assert record["size_bytes"] == len(payload)
        assert (scene / cad.CAD_DIRECTORY / record["id"] / "source.dwg").read_bytes() == payload
        records.append(record)
    assert records[0]["id"] != records[1]["id"]
    assert client.get(url).json() == list(reversed(records))
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
