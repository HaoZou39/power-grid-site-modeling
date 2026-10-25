import json
import numpy as np
import pytest

from experiments.scene_version import scene_data_version
from experiments.landuse_edits import create_landuse_edit, delete_landuse_edit
from experiments.scene_store import publish_road_bundle
from experiments.protected_farmland import delete_layer


def _scene(path):
    path.mkdir()
    np.save(path/"landuse_1m.npy", np.zeros((8,8), np.uint8))
    np.save(path/"obstacle_mask_1m.npy", np.zeros((8,8), np.uint8))
    (path/"data_metadata.json").write_text(json.dumps({"dem":{"reference_crs":"EPSG:32651",
        "target_transform":[1,0,100,0,-1,200],"shape":[8,8]}}))


def test_revision_survives_reload_and_changes_on_land_and_farmland_edits(tmp_path):
    scene = tmp_path/"demo"
    _scene(scene)
    original = scene_data_version(scene)
    items = create_landuse_edit("demo", 5, [(2,2),(6,2),(6,6),(2,6)], tmp_path)
    edited = scene_data_version(scene)
    assert original["frame_id"] == edited["frame_id"]
    assert original["scene_revision"] != edited["scene_revision"]
    assert edited == scene_data_version(scene)
    delete_landuse_edit("demo", items[0]["id"], tmp_path)
    undone = scene_data_version(scene)
    assert undone["scene_revision"] != edited["scene_revision"]
    delete_layer(scene)
    assert scene_data_version(scene)["scene_revision"] != undone["scene_revision"]


def test_partial_import_publishes_revision_with_the_same_backup_transaction(tmp_path):
    scene = tmp_path/"demo"
    _scene(scene)
    original = (scene/"data_metadata.json").read_bytes()
    staged = tmp_path/"staged"
    staged.mkdir()
    (staged/"layer.txt").write_text("new")
    before = scene_data_version(scene)
    backup = publish_road_bundle(scene, staged, tmp_path/"backups", "product", files=("layer.txt",))
    assert (backup/"data_metadata.json").read_bytes() == original
    assert scene_data_version(scene)["scene_revision"] != before["scene_revision"]


def test_readonly_scene_cannot_publish_or_edit_landuse(tmp_path):
    scene = tmp_path/"demo"
    _scene(scene)
    (scene/"scene.json").write_text('{"read_only":true}')
    with pytest.raises(ValueError, match="封存"):
        create_landuse_edit("demo", 5, [(2,2),(6,2),(6,6),(2,6)], tmp_path)
    assert not (scene/"landuse_base_1m.npy").exists()
    staged = tmp_path/"staged"
    staged.mkdir()
    with pytest.raises(ValueError, match="封存"):
        publish_road_bundle(scene, staged, tmp_path/"backups", "product", files=())
