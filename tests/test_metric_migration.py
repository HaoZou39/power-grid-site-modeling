import hashlib
import json

import numpy as np
import pytest

from backend.app.infrastructure.favorite_repository import FavoritePointRepository
from data_tools.metric_grid import metric_grid
from experiments.migrate_metric_scene import migrate_metric_scene, publish_metric_scene
from experiments.scene_version import scene_data_version


def _scene(path, crs="EPSG:3857"):
    path.mkdir(parents=True)
    for name, array in {"dem_1m":np.zeros((8,8),np.float32), "landuse_1m":np.zeros((8,8),np.uint8),
        "obstacle_mask_1m":np.zeros((8,8),np.uint8), "road_voronoi_1m":np.zeros((8,8),np.int64),
        "road_segments_local":np.array([[0,0,7,0]],np.float32),"road_segment_kind":np.zeros(1,np.int8),
        "demand_points":np.array([[4,4]],np.float32)}.items():
        np.save(path/(name+".npy"),array)
    grid=metric_grid(27.5,120.2,8) if crs != "EPSG:3857" else {"crs":crs,"transform":[1,0,100,0,-1,200]}
    (path/"data_metadata.json").write_text(json.dumps({"dem":{"reference_crs":grid["crs"],
        "target_transform":grid["transform"],"shape":[8,8]},"scene_revision":"original"}))
    (path/"scene.json").write_text(json.dumps({"id":path.name,"title":"显示名, 带空格"}))


@pytest.mark.parametrize("kind", ["farmland","roads"])
def test_migration_requires_original_vectors_for_imported_layers(tmp_path,kind):
    source=tmp_path/"legacy"
    _scene(source)
    if kind == "farmland":
        np.save(source/"protected_farmland_mask_1m.npy",np.zeros((8,8),bool))
    else:
        (source/"scene.json").write_text('{"road_source":{"provider":"gaode"}}')
    with pytest.raises(ValueError,match="原始"):
        migrate_metric_scene(source,tmp_path/"staged",lambda *args:None)
    assert not (tmp_path/"staged").exists()


def test_publication_keeps_legacy_arrays_and_copies_geographic_favorites_once(tmp_path):
    source=tmp_path/"scenes"/"old"
    staged=tmp_path/"validation"/"old-utm-v2"
    _scene(source)
    _scene(staged,"EPSG:32651")
    source_record = json.loads((source / "scene.json").read_text())
    source_record["metric_migration_pending"] = True
    (source / "scene.json").write_text(json.dumps(source_record))
    manifest={"source_scene":source.name,"source_version":scene_data_version(source),"target_version":scene_data_version(staged)}
    (staged/"migration.json").write_text(json.dumps(manifest))
    before=hashlib.sha256((source/"dem_1m.npy").read_bytes()).hexdigest()
    db=tmp_path/"favorites.sqlite3"
    favorites=FavoritePointRepository(db)
    original=favorites.create(source.name,120.2,27.5,30,60,17)
    evidence=tmp_path/"evidence"
    target=publish_metric_scene(source,staged,source.parent,evidence,favorites_path=db,default=True)
    assert staged.is_dir() and target.is_dir()
    assert json.loads((source/"scene.json").read_text())["read_only"]
    assert not json.loads((source / "scene.json").read_text()).get("metric_migration_pending", False)
    assert json.loads((target/"scene.json").read_text())["default"]
    assert hashlib.sha256((source/"dem_1m.npy").read_bytes()).hexdigest()==before
    copied=favorites.list_for_scene(target.name)
    assert len(copied)==1 and favorites.list_for_scene(source.name)==[original]
    assert (copied[0].longitude,copied[0].latitude,copied[0].width_m,copied[0].height_m,copied[0].bearing_deg)==(120.2,27.5,30,60,17)
    assert favorites.copy_to_scene(source.name,target.name)==0
    assert (evidence/"favorites-before.sqlite3").is_file()
    with pytest.raises(FileExistsError):
        publish_metric_scene(source,staged,source.parent,evidence,favorites_path=db)


def test_publication_refuses_source_changes_since_migration(tmp_path):
    source = tmp_path / "scenes" / "old"
    staged = tmp_path / "validation" / "old-utm-v2"
    _scene(source)
    _scene(staged, "EPSG:32651")
    (staged / "migration.json").write_text(json.dumps({
        "source_scene": source.name, "source_version": scene_data_version(source),
        "target_version": scene_data_version(staged),
    }))
    metadata = source / "data_metadata.json"
    record = json.loads(metadata.read_text())
    record["scene_revision"] = "changed"
    metadata.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="来源"):
        publish_metric_scene(source, staged, source.parent, tmp_path / "evidence")
    assert not (source.parent / staged.name).exists()
    assert "read_only" not in json.loads((source / "scene.json").read_text())


def test_failed_favorites_copy_removes_only_new_publication(tmp_path, monkeypatch):
    source = tmp_path / "scenes" / "old"
    staged = tmp_path / "validation" / "old-utm-v2"
    _scene(source)
    _scene(staged, "EPSG:32651")
    (staged / "migration.json").write_text(json.dumps({
        "source_scene": source.name, "source_version": scene_data_version(source),
        "target_version": scene_data_version(staged),
    }))
    db = tmp_path / "favorites.sqlite3"
    FavoritePointRepository(db)
    def fail_copy(*args):
        raise OSError("injected favorites write failure")
    monkeypatch.setattr(FavoritePointRepository, "copy_to_scene", fail_copy)
    before = (source / "dem_1m.npy").read_bytes()
    with pytest.raises(OSError, match="injected"):
        publish_metric_scene(source, staged, source.parent, tmp_path / "evidence", favorites_path=db)
    assert staged.is_dir()
    assert not (source.parent / staged.name).exists()
    assert (source / "dem_1m.npy").read_bytes() == before
    assert "read_only" not in json.loads((source / "scene.json").read_text())
