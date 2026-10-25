"""Unified import transactions and preservation of road provenance."""
import json
from io import BytesIO
from pathlib import Path
import zipfile

import numpy as np
from pyproj import CRS
import pytest
import shapefile

from test_road_import import road_trial
from experiments import scene_data_import as importer
from experiments import scene_store
from experiments import protected_farmland as farmland


def _zip_source(source):
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for suffix in ('shp', 'shx', 'dbf', 'prj', 'cpg'):
            path = source.with_suffix('.' + suffix)
            if path.is_file(): archive.write(path, 'roads.' + suffix)
    return stream.getvalue()


def _farm_zip(tmp_path):
    source = tmp_path / 'farmland.shp'
    with shapefile.Writer(str(source), shapeType=shapefile.POLYGON) as writer:
        writer.field('id', 'N')
        writer.poly([[[100, 197], [100, 200], [104, 200], [104, 197], [100, 197]]])
        writer.record(1)
    source.with_suffix('.prj').write_text(CRS.from_epsg(3857).to_wkt())
    return ('farm.zip', _zip_source(source))


def _inputs(tmp_path, road_trial):
    scene, roads = road_trial
    return scene, _farm_zip(tmp_path), ('roads.zip', _zip_source(roads))


@pytest.mark.parametrize('upload_farm,upload_roads', [(True, False), (False, True), (True, True)])
def test_three_import_combinations(tmp_path, road_trial, upload_farm, upload_roads):
    scene, farm, roads = _inputs(tmp_path, road_trial)
    old_roads = (scene / 'road_segments_local.npy').read_bytes()
    old_farm = (scene / farmland.MASK_NAME).read_bytes()
    result = importer.preview_scene_data(scene, farm if upload_farm else None, roads if upload_roads else None, 'gaode')
    directory = importer.preview_directory(scene, result['token'])
    assert scene not in directory.parents
    assert (scene / 'road_segments_local.npy').read_bytes() == old_roads
    assert (scene / farmland.MASK_NAME).read_bytes() == old_farm
    committed = importer.commit_scene_data(scene, result['token'], backup_root=tmp_path / 'backups')
    assert committed['saved']
    if upload_roads:
        assert (scene / importer.ROAD_SOURCE).is_file()
        assert json.loads((scene / 'scene.json').read_text())['road_source']['provider'] == 'gaode'
        assert np.load(scene / 'road_segment_kind.npy').shape == (3,)
    else:
        assert (scene / 'road_segments_local.npy').read_bytes() == old_roads
    if upload_farm:
        assert json.loads((scene / farmland.META_NAME).read_text())['content_sha256']
        assert farmland.layer_info(scene)['osm_overlap_cells'] == result['access_overlap_cells']
    else:
        assert (scene / farmland.MASK_NAME).read_bytes() == old_farm
    with pytest.raises(ValueError, match='已经发布'):
        importer.commit_scene_data(scene, result['token'], backup_root=tmp_path / 'backups')


def test_joint_publication_failure_restores_roads_farmland_and_source(tmp_path, road_trial, monkeypatch):
    scene, farm, roads = _inputs(tmp_path, road_trial)
    result = importer.preview_scene_data(scene, farm, roads, 'gaode')
    before = {path.name: path.read_bytes() for path in scene.iterdir() if path.is_file()}
    publish = scene_store._publish_road_file
    failed = False
    def fail_after_roads(source, destination):
        nonlocal failed
        if destination.name == farmland.META_NAME and not failed:
            failed = True
            raise OSError('farmland write failed')
        return publish(source, destination)
    monkeypatch.setattr(scene_store, '_publish_road_file', fail_after_roads)
    with pytest.raises(OSError, match='farmland write failed'):
        importer.commit_scene_data(scene, result['token'], backup_root=tmp_path / 'backups')
    assert {path.name: path.read_bytes() for path in scene.iterdir() if path.is_file()} == before
    assert not (scene / scene_store.ROAD_REBUILD_MARKER).exists()


def test_joint_failed_rollback_blocks_scene_and_reports_backup(tmp_path, road_trial, monkeypatch):
    scene, farm, roads = _inputs(tmp_path, road_trial)
    result = importer.preview_scene_data(scene, farm, roads, 'gaode')
    publish = scene_store._publish_road_file
    failed = False
    def fail_publication_and_recovery(source, destination):
        nonlocal failed
        if destination.name == farmland.META_NAME:
            failed = True
            raise OSError('farmland write failed')
        if failed and destination.name == 'road_segments_local.npy':
            raise OSError('rollback failed')
        return publish(source, destination)
    monkeypatch.setattr(scene_store, '_publish_road_file', fail_publication_and_recovery)
    with pytest.raises(RuntimeError, match='回滚失败.*备份目录'):
        importer.commit_scene_data(scene, result['token'], backup_root=tmp_path / 'backups')
    assert (scene / scene_store.ROAD_REBUILD_MARKER).exists()
    with pytest.raises(RuntimeError): scene_store.ensure_scene_readable(scene)


def test_concurrent_data_change_rejects_confirmation(tmp_path, road_trial):
    scene, farm, roads = _inputs(tmp_path, road_trial)
    result = importer.preview_scene_data(scene, farm, roads, 'gaode')
    np.save(scene / 'road_segment_kind.npy', np.array([2], np.int8))
    with pytest.raises(ValueError, match='已经变化'):
        importer.commit_scene_data(scene, result['token'])


def test_no_upload_is_rejected(road_trial):
    with pytest.raises(ValueError, match='至少'):
        importer.preview_scene_data(road_trial[0])


def test_restore_uses_scene_registered_osm_and_keeps_farmland(tmp_path, road_trial):
    scene, farm, roads = _inputs(tmp_path, road_trial)
    result = importer.preview_scene_data(scene, farm, roads, 'gaode')
    directory = importer.preview_directory(scene, result['token'])
    original = tmp_path / 'original_osm.geojson'
    original.write_bytes((directory / 'roads/roads_wgs84.geojson').read_bytes())
    (scene / 'scene.json').write_text(json.dumps({'id': scene.name, 'source_files': {'osm_roads_path': str(original)}}))
    importer.commit_scene_data(scene, result['token'], backup_root=tmp_path / 'backups')
    old_farm = (scene / farmland.MASK_NAME).read_bytes()
    restored = importer.restore_osm_roads(scene, backup_root=tmp_path / 'backups')
    assert restored['road']['provider'] == 'osm'
    assert not (scene / importer.ROAD_SOURCE).exists()
    assert 'road_source' not in json.loads((scene / 'scene.json').read_text())
    assert (scene / farmland.MASK_NAME).read_bytes() == old_farm
    assert (Path(restored['backup']) / importer.ROAD_SOURCE).is_file()


def test_full_rebuild_retains_imported_road_source(tmp_path, road_trial, monkeypatch):
    import shutil
    scene, farm, roads = _inputs(tmp_path, road_trial)
    result = importer.preview_scene_data(scene, farm, roads, 'gaode')
    importer.commit_scene_data(scene, result['token'], backup_root=tmp_path / 'backups')
    expected = (scene / importer.ROAD_SOURCE).read_bytes()
    sources = {}
    for key in ('dem_path', 'landuse_path', 'osm_roads_path', 'reference_geotiff_path'):
        path = tmp_path / key
        path.write_text('original')
        sources[key] = path
    metadata = json.loads((scene / scene_store.SCENE_METADATA).read_text())
    def prepared(config, target, on_step):
        assert config.data.osm_roads_path.read_bytes() == expected
        target.mkdir(parents=True)
        for name in scene_store.SCENE_ARRAYS:
            shutil.copyfile(scene / name, target / name)
        return {}, json.loads(json.dumps(metadata))
    monkeypatch.setattr('experiments.problem_context.write_scene_products', prepared)
    notices = []
    rebuilt = scene_store.prepare_scene_from_sources(scene.name, sources, lambda *item: notices.append(item),
        title='Demo', source_site_id='demo', root=scene.parent)
    assert rebuilt == scene
    assert (scene / importer.ROAD_SOURCE).read_bytes() == expected
    assert json.loads((scene / 'scene.json').read_text())['road_source']['provider'] == 'gaode'
    assert '已保留导入的高德道路' in notices[-1][-1]
    assert json.loads((scene / scene_store.SCENE_METADATA).read_text())['road']['provider'] == 'gaode'


def test_unified_api_preview_confirm_and_old_routes_removed(tmp_path, road_trial, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app.main import create_app
    scene, farm, roads = _inputs(tmp_path, road_trial)
    monkeypatch.setenv('SCENE_ROOT', str(scene.parent))
    client = TestClient(create_app('sqlite://:memory:', '', favorite_db_path=tmp_path / 'favorites.sqlite3'))
    base = '/api/v1/scenes/demo'
    response = client.post(base + '/data-import/preview', files={'farmland': farm, 'roads': roads}, data={'provider': 'gaode'})
    assert response.status_code == 200, response.text
    token = response.json()['token']
    assert client.get(base + f'/data-import/preview/{token}/farmland.png').status_code == 200
    assert len(client.get(base + f'/data-import/preview/{token}/roads').json()['kinds']) == 3
    assert client.post(base + '/data-import/confirm', json={'token': token}).status_code == 200
    assert client.get(base + '/road-segments').json()['kinds'] == [0, 0, 0]
    assert client.post(base + '/protected-farmland/preview', files={'file': farm}).status_code == 404
    (scene / 'road_segment_kind.npy').unlink()
    missing = client.get(base + '/road-segments')
    assert missing.status_code == 404
    assert 'road_segment_kind.npy' in missing.json()['detail']['message']


def test_overlap_tracks_current_access_kinds(tmp_path, road_trial):
    scene, farm, roads = _inputs(tmp_path, road_trial)
    result = importer.preview_scene_data(scene, farm, roads, 'gaode')
    importer.commit_scene_data(scene, result['token'], backup_root=tmp_path / 'backups')
    assert farmland.layer_info(scene)['osm_overlap_cells'] > 0
    kinds = np.load(scene / 'road_segment_kind.npy')
    np.save(scene / 'road_segment_kind.npy', np.full_like(kinds, 3))
    assert farmland.layer_info(scene)['osm_overlap_cells'] == 0
