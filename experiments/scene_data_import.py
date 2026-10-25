"""Preview optional road/farmland uploads and publish them as one scene transaction."""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np

from config.project_config import DEFAULT_CONFIG_PATH, load_project_config
from data_tools.io_utils import write_json
from experiments import protected_farmland as farmland_tool
from experiments.coordinate_scene import scene_write_lock
from experiments.import_road_shapefile import RoadImportConfig, _road_signature, preview_road_source
from experiments.scene_store import (
    ROAD_PRODUCT_FILES, SCENE_METADATA, _resolve_source_path, _validate_road_arrays,
    ensure_scene_readable, publish_road_bundle, scene_frame_info,
)

ROAD_SOURCE = "road_source_wgs84.geojson"
FARMLAND_FILES = (farmland_tool.MASK_NAME, farmland_tool.OVERLAY_NAME, farmland_tool.META_NAME)


def preview_directory(scene: Path, token: str) -> Path:
    if len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
        raise farmland_tool.FarmlandImportError('预览令牌无效，请重新预览', 404)
    return scene.parent / '.import-previews' / scene.name / token


def _farmland_signature(scene: Path):
    return farmland_tool.farmland_file_signature(scene)


def _scene_record(scene: Path) -> dict:
    path = scene / 'scene.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'id': scene.name}


def stage_road_source(scene: Path, staged: Path, source: Path, provider: str,
                      config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    from data_tools.traffic_tool import build_road_product
    data = load_project_config(config_path).data
    frame = scene_frame_info(scene)
    if frame is None:
        raise ValueError('场景缺少地理参考')
    segments, labels, kinds, metadata = build_road_product(
        source, staged / 'road_segments_local.npy', staged / 'road_voronoi_1m.npy',
        None, (frame['height'], frame['width']), data.road_dp_tolerance_m, data.road_resolution_m,
        reference_frame=frame, kind_rules=data.road_kind_rules,
        voronoi_backend=data.road_voronoi_backend, voronoi_device=data.road_voronoi_device,
        voronoi_chunk_points=data.road_voronoi_chunk_points, voronoi_segment_tile=data.road_voronoi_segment_tile,
    )
    _validate_road_arrays(segments, labels, labels.shape, kinds)
    metadata['provider'] = provider
    return metadata


def stage_road_record(scene: Path, staged: Path, metadata: dict, source: Path | None) -> None:
    for name in ('road_segments_local.json', 'road_voronoi_1m.json'):
        write_json(staged / name, metadata)
    scene_metadata = json.loads((scene / SCENE_METADATA).read_text(encoding='utf-8'))
    scene_metadata['road'] = metadata
    write_json(staged / SCENE_METADATA, scene_metadata)
    record = _scene_record(scene)
    if source is None:
        record.pop('road_source', None)
    else:
        shutil.copyfile(source, staged / ROAD_SOURCE)
        record['road_source'] = {'provider': metadata['provider'], 'path': ROAD_SOURCE,
                                 'source_sha256': metadata.get('source_sha256')}
    write_json(staged / 'scene.json', record)


def preview_scene_data(scene: Path, farmland: tuple[str, bytes] | None = None,
                       roads: tuple[str, bytes] | None = None, provider: str = '', *,
                       config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    scene = Path(scene).resolve()
    ensure_scene_readable(scene)
    farmland_tool._require_scene_grid(scene)
    if farmland is None and roads is None:
        raise ValueError('请至少选择永农或道路中的一项文件')
    for upload in (farmland, roads):
        if upload is not None and len(upload[1]) > farmland_tool.MAX_ZIP_BYTES:
            raise farmland_tool.FarmlandImportError('压缩包超过 80 MB', 413)
    if roads is not None and (not provider.strip() or provider.strip().lower() in {'osm', 'openstreetmap'}):
        raise ValueError('请填写外部道路的来源名称；OSM 来源使用“改回 OSM 道路”')
    token = uuid4().hex
    destination = preview_directory(scene, token)
    destination.mkdir(parents=True)
    grid = farmland_tool._grid_signature(scene)
    road_signature = _road_signature(scene)
    farmland_signature = _farmland_signature(scene)
    result = {'token': token, 'scene_id': scene.name, 'grid_signature': grid,
              'road_signature': road_signature, 'farmland_signature': farmland_signature,
              'farmland': None, 'roads': None, 'saved': False}
    try:
        if roads is not None:
            filename, payload = roads
            suffix = Path(filename).suffix.lower()
            if suffix not in {'.zip', '.rar'}:
                raise ValueError('道路上传文件必须为 ZIP 或 RAR')
            uploaded = destination / ('upload' + suffix)
            uploaded.write_bytes(payload)
            data = load_project_config(config_path).data
            config = RoadImportConfig(scene.name, uploaded, destination / 'roads', data.road_import_clip_buffer_m,
                                      data.road_import_excluded_classes, provider.strip())
            candidate = preview_road_source(config, root=scene.parent, config_path=config_path)
            candidate['road']['source_name'] = Path(filename).name
            result['roads'] = candidate['road']
        if farmland is not None:
            target = destination / 'farmland'
            target.mkdir()
            result['farmland'] = farmland_tool._rasterize_zip(scene, target, farmland[0], farmland[1])
            mask = np.load(target / farmland_tool.MASK_NAME)
        else:
            mask = farmland_tool.load_mask(scene, farmland_tool._scene_shape(scene))
        effective_roads = destination / 'roads' if roads is not None else scene
        if mask is not None:
            overlap = farmland_tool._osm_overlap(effective_roads, mask)
            if result['farmland'] is not None:
                result['farmland']['osm_overlap_cells'] = overlap
            result['access_overlap_cells'] = overlap
        if grid != farmland_tool._grid_signature(scene) or road_signature != _road_signature(scene) or farmland_signature != _farmland_signature(scene):
            raise ValueError('预览期间场景数据已变化，请重新预览')
        write_json(destination / 'summary.json', result)
        return result
    except Exception:
        shutil.rmtree(destination)
        raise


def road_preview(scene: Path, token: str) -> dict:
    directory = preview_directory(Path(scene).resolve(), token)
    return {'segments': np.load(directory / 'roads/road_segments_local.npy').tolist(),
            'kinds': np.load(directory / 'roads/road_segment_kind.npy').tolist()}


def commit_scene_data(scene: Path, token: str, *, backup_root: Path = Path('outputs/scene-road-backups')) -> dict:
    scene = Path(scene).resolve()
    directory = preview_directory(scene, token)
    path = directory / 'summary.json'
    if not path.is_file():
        raise farmland_tool.FarmlandImportError('预览不存在，请重新预览', 404)
    with scene_write_lock(scene.name, scene.parent):
        ensure_scene_readable(scene)
        summary = json.loads(path.read_text(encoding='utf-8'))
        if summary['saved']:
            raise ValueError('该预览已经发布，请重新预览')
        if (summary['scene_id'] != scene.name or summary['grid_signature'] != farmland_tool._grid_signature(scene)
                or summary['road_signature'] != _road_signature(scene)
                or summary['farmland_signature'] != json.loads(json.dumps(_farmland_signature(scene)))):
            raise ValueError('场景数据已经变化，请重新预览后再导入')
        staged = directory / 'publish'
        staged.mkdir(exist_ok=True)
        files: tuple[str, ...] = ()
        if summary['roads'] is not None:
            road_dir = directory / 'roads'
            frame = scene_frame_info(scene)
            _validate_road_arrays(np.load(road_dir / 'road_segments_local.npy'), np.load(road_dir / 'road_voronoi_1m.npy'),
                                  (frame['height'], frame['width']), np.load(road_dir / 'road_segment_kind.npy'))
            for name in ROAD_PRODUCT_FILES:
                if name != SCENE_METADATA:
                    shutil.copyfile(road_dir / name, staged / name)
            source = road_dir / 'roads_wgs84.geojson'
            metadata = dict(summary['roads'])
            metadata['source_path'] = ROAD_SOURCE
            stage_road_record(scene, staged, metadata, source)
            files = (*ROAD_PRODUCT_FILES, ROAD_SOURCE, 'scene.json')
        if summary['farmland'] is not None:
            source = directory / 'farmland'
            mask = np.asarray(np.load(source / farmland_tool.MASK_NAME), dtype=bool)
            if mask.shape != farmland_tool._scene_shape(scene) or not mask.any():
                raise ValueError('永农预览栅格与当前场景不一致')
            record = {**summary['farmland'], 'saved': True, 'imported_at': datetime.now(timezone.utc).isoformat(),
                      'content_sha256': farmland_tool._array_sha256(mask)}
            farmland_tool._publish_layer(staged, mask, record, source / farmland_tool.OVERLAY_NAME)
            files = (*files, *FARMLAND_FILES)
        backup = publish_road_bundle(scene, staged, backup_root, token, files=files)
        summary.update(saved=True, backup=str(backup))
        write_json(path, summary)
        farmland_tool.invalidate_runtime_caches()
    return summary


def restore_osm_roads(scene: Path, *, backup_root: Path = Path('outputs/scene-road-backups'),
                       config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    scene = Path(scene).resolve()
    with scene_write_lock(scene.name, scene.parent):
        ensure_scene_readable(scene)
        record = _scene_record(scene)
        original = record.get('source_files', {}).get('osm_roads_path')
        if not original:
            raise FileNotFoundError('该场景没有记录原始 OSM 道路来源')
        source = _resolve_source_path(original)
        if not source.is_file():
            raise FileNotFoundError(f'场景原始 OSM 文件不存在：{source}')
        with tempfile.TemporaryDirectory(prefix='.restore-roads-', dir=scene.parent) as temp:
            staged = Path(temp)
            metadata = stage_road_source(scene, staged, source, 'osm', config_path)
            stage_road_record(scene, staged, metadata, None)
            backup = publish_road_bundle(scene, staged, backup_root, metadata['road_product_id'],
                                         files=(*ROAD_PRODUCT_FILES, 'scene.json', ROAD_SOURCE), remove_files=(ROAD_SOURCE,))
        farmland_tool.invalidate_runtime_caches()
    return {'road': metadata, 'backup': str(backup)}
