"""Add road kinds to a prepared scene without changing any published segment bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from config.project_config import DEFAULT_CONFIG_PATH
from data_tools.io_utils import write_json
from experiments.coordinate_scene import scene_write_lock
from experiments.scene_data_import import ROAD_SOURCE, stage_road_record, stage_road_source
from experiments.scene_store import ROAD_PRODUCT_FILES, SCENE_METADATA, publish_road_bundle
from experiments.protected_farmland import invalidate_runtime_caches


def migrate_road_kinds(scene: Path, source: Path, provider: str, output: Path,
                        config_path: Path = DEFAULT_CONFIG_PATH,
                        backup_root: Path = Path('outputs/scene-road-backups')) -> dict:
    scene, source, output = scene.resolve(), source.resolve(), output.resolve()
    if output == scene or scene in output.parents:
        raise ValueError('migration output must be outside the scene')
    output.mkdir(parents=True, exist_ok=False)
    with scene_write_lock(scene.name, scene.parent):
        before = (scene / 'road_segments_local.npy').read_bytes()
        old_metadata = json.loads((scene / SCENE_METADATA).read_text())
        metadata = stage_road_source(scene, output, source, provider, config_path)
        if (output / 'road_segments_local.npy').read_bytes() != before:
            raise ValueError('migration changed segment bytes; candidate was not published')
        previous = old_metadata.get('road', {})
        metadata.update({key: previous[key] for key in ('source_name', 'source_sha256', 'import') if key in previous})
        if provider != 'osm': metadata['source_path'] = ROAD_SOURCE
        stage_road_record(scene, output, metadata, source if provider != 'osm' else None)
        record = json.loads((output / 'scene.json').read_text())
        if 'source_files' not in record:
            from experiments.scene_store import SCENE_SOURCES
            if scene.name not in SCENE_SOURCES:
                raise ValueError('scene is missing its original source registration')
            record['source_files'] = {key: str(value) for key, value in SCENE_SOURCES[scene.name].items() if key != 'title'}
            write_json(output / 'scene.json', record)
        files = (*ROAD_PRODUCT_FILES, 'scene.json', *((ROAD_SOURCE,) if provider != 'osm' else ()))
        backup = publish_road_bundle(scene, output, backup_root, metadata['road_product_id'], files=files)
    invalidate_runtime_caches()
    report = {'scene': scene.name, 'provider': provider, 'segment_bytes_unchanged': True,
              'segment_sha256': hashlib.sha256(before).hexdigest(),
              'segment_kind_counts': metadata['segment_kind_counts'],
              'road_product_id': metadata['road_product_id'], 'backup': str(backup)}
    write_json(output / 'migration.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', required=True, type=Path)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--provider', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument('--backup-root', type=Path, default=Path('outputs/scene-road-backups'))
    args = parser.parse_args()
    print(json.dumps(migrate_road_kinds(args.scene, args.source, args.provider, args.output, args.config, args.backup_root), ensure_ascii=False))


if __name__ == '__main__':
    main()
