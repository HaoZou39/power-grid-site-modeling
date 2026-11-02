"""CAD publication, manual-edit precedence and shared constraint inputs."""
import json
from pathlib import Path
import shutil

import ezdxf
import numpy as np
import pytest

from experiments import cad_landuse, landuse_edits, scene_store
from experiments.constraint_mask import compose_hard_mask, policy_from_form
from experiments.scene_version import write_scene_revision
from test_scene_cad_files import cad_client, road_trial


def _uploaded(client, tmp_path):
    doc = ezdxf.new()
    for name, points in [("建筑", [(100.1, 198.1), (101.8, 198.1), (101.8, 199.8), (100.1, 199.8)]),
                         ("农田", [(102.1, 197.1), (103.8, 197.1), (103.8, 199.8), (102.1, 199.8)])]:
        doc.layers.new(name)
        doc.modelspace().add_lwpolyline(points, close=True, dxfattribs={"layer": name})
    path = tmp_path / "full.dxf"
    doc.saveas(path)
    response = client.post("/api/v1/scenes/demo/cad-files", files={"file": (path.name, path.read_bytes())})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _preview(client, cad_id):
    response = client.post(f"/api/v1/scenes/demo/cad-files/{cad_id}/preview", json={
        "source_crs": "EPSG:3857", "layer_kinds": {"建筑": "building", "农田": "field"}})
    assert response.status_code == 200, response.text
    return response.json()


def _confirm(client, preview):
    response = client.post("/api/v1/scenes/demo/cad-files/confirm", json={"token": preview["token"]})
    assert response.status_code == 200, response.text
    return response


def test_api_inspect_preview_confirm_and_constraint_policy(cad_client, tmp_path):
    client, scene = cad_client
    cad_id = _uploaded(client, tmp_path)
    before = (scene / "landuse_1m.npy").read_bytes()
    inspection = client.post(f"/api/v1/scenes/demo/cad-files/{cad_id}/inspect")
    assert inspection.status_code == 200, inspection.text
    assert {layer["suggested_kind"] for layer in inspection.json()["layers"]} == {"building", "field"}
    preview = _preview(client, cad_id)
    assert client.get(f"/api/v1/scenes/demo/cad-files/preview/{preview['token']}.png").status_code == 200
    assert (scene / "landuse_1m.npy").read_bytes() == before
    _confirm(client, preview)
    landuse = np.load(scene / "landuse_1m.npy")
    assert landuse[1, 1] == 2 and landuse[1, 3] == 1
    blocked = compose_hard_mask(landuse, [], policy_from_form({"field_policy": "blocked"}))
    allowed = compose_hard_mask(landuse, [], policy_from_form({"field_policy": "allowed"}))
    assert blocked[1, 3] and not allowed[1, 3]
    assert blocked[1, 1] and allowed[1, 1]
    assert client.get("/api/v1/scenes/demo/cad-files").json()[0]["active"]
    assert client.post("/api/v1/scenes/demo/cad-files/confirm", json={"token": preview["token"]}).status_code == 400


def test_manual_edits_before_and_after_cad_still_work(cad_client, tmp_path):
    client, scene = cad_client
    landuse_edits.create_landuse_edit("demo", 5, [(0.1, 0.1), (0.8, 0.1), (0.8, 0.8)], scene.parent)
    _confirm(client, _preview(client, _uploaded(client, tmp_path)))
    assert np.load(scene / "landuse_1m.npy")[0, 0] == 5
    landuse_edits.create_landuse_edit("demo", 3, [(3.1, 2.1), (3.8, 2.1), (3.8, 2.8)], scene.parent)
    result = np.load(scene / "landuse_1m.npy")
    assert result[2, 3] == 3 and result[1, 1] == 2
    landuse_edits.clear_landuse_edits("demo", scene.parent)
    assert (scene / landuse_edits.BASE_FILE).is_file()
    assert np.load(scene / "landuse_1m.npy")[0, 0] == 2
    response = client.delete("/api/v1/scenes/demo/cad-landuse")
    assert response.status_code == 200, response.text
    assert not np.load(scene / "landuse_1m.npy").any()
    assert not (scene / landuse_edits.CAD_LAYER_FILE).exists()


def test_stale_preview_cannot_replace_changed_scene(cad_client, tmp_path):
    client, scene = cad_client
    preview = _preview(client, _uploaded(client, tmp_path))
    write_scene_revision(scene)
    response = client.post("/api/v1/scenes/demo/cad-files/confirm", json={"token": preview["token"]})
    assert response.status_code == 400 and "场景已变化" in response.text
    assert not np.load(scene / "landuse_1m.npy").any()


def test_failed_landuse_publish_restores_all_files(cad_client, tmp_path, monkeypatch):
    client, scene = cad_client
    cad_id = _uploaded(client, tmp_path)
    preview = _preview(client, cad_id)
    old = {path.name: path.read_bytes() for path in scene.iterdir() if path.is_file()}
    def fail(*args):
        raise RuntimeError("overlay failure")
    monkeypatch.setattr(landuse_edits, "write_obstacle_overlay", fail)
    with pytest.raises(RuntimeError, match="overlay failure"):
        cad_landuse.confirm_cad(scene, preview["token"])
    assert {path.name: path.read_bytes() for path in scene.iterdir() if path.is_file()} == old
    assert not (scene / landuse_edits.CAD_LAYER_FILE).exists()


def test_rebuild_reprojects_active_cad_from_source(cad_client, tmp_path, monkeypatch):
    client, scene = cad_client
    _confirm(client, _preview(client, _uploaded(client, tmp_path)))
    sources = {}
    for key in ("dem_path", "landuse_path", "osm_roads_path", "reference_geotiff_path"):
        sources[key] = tmp_path / key
        sources[key].write_text("source")
    metadata = json.loads((scene / scene_store.SCENE_METADATA).read_text())
    metadata["dem"]["target_transform"][2] = 101
    def prepared(config, target, on_step, **kwargs):
        target.mkdir(parents=True)
        for name in scene_store.SCENE_ARRAYS:
            shutil.copyfile(scene / name, target / name)
        np.save(target / "landuse_1m.npy", np.zeros((3, 4), np.uint8))
        return {}, metadata
    monkeypatch.setattr("experiments.problem_context.write_scene_products", prepared)
    scene_store.prepare_scene_from_sources("demo", sources, lambda *args: None, title="Demo", source_site_id="demo", root=scene.parent)
    result = np.load(scene / "landuse_1m.npy")
    assert result[1, 0] == 2 and result[1, 1] == 1
    assert not np.load(scene / landuse_edits.BASE_FILE).any()
