"""Build an independent UTM replacement; never rescale or overwrite a legacy grid."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pyproj import Transformer

from data_tools.io_utils import write_json
from experiments.coordinate_scene import build_scene_from_coordinates
from experiments.scene_lock import scene_write_lock
from experiments.scene_store import scene_directory, scene_frame_info
from experiments.scene_version import scene_data_version


def migrate_metric_scene(source: Path, destination_root: Path, reporter, *,
                         farmland_source: Path | None = None, roads_source: Path | None = None) -> Path:
    source = source.resolve()
    with scene_write_lock(source.name, source.parent, blocking=True):
        frame = scene_frame_info(source)
        if frame is None or frame["crs"] != "EPSG:3857":
            raise ValueError("migration requires an explicitly identified legacy EPSG:3857 scene")
        if frame["width"] != frame["height"]:
            raise ValueError("coordinate migration requires a square scene")
        record = json.loads((source / "scene.json").read_text(encoding="utf-8"))
        version = scene_data_version(source)
        if (source / "protected_farmland_mask_1m.npy").is_file() and farmland_source is None:
            raise ValueError("原场景含永农，必须提供原始 farmland_source；不能扩大已裁剪掩膜")
        imported = record.get("road_source", {}).get("provider", "osm")
        if imported != "osm" and roads_source is None:
            raise ValueError("原场景含导入道路，必须提供原始 roads_source 重新裁剪")
        edits_path = source / "landuse_edits.json"
        edits = json.loads(edits_path.read_text())["items"] if edits_path.is_file() else []
        a, _b, c, _d, e, f = frame["transform"]
        lon, lat = Transformer.from_crs(frame["crs"], 4326, always_xy=True).transform(
            c + a * frame["width"] / 2, f + e * frame["height"] / 2)
    for path in (farmland_source, roads_source):
        if path is not None and not path.is_file():
            raise FileNotFoundError(path)
    name = source.name + "-utm-v2"
    destination = scene_directory(destination_root, name)
    if destination.exists():
        raise FileExistsError(destination)
    build_scene_from_coordinates({"lat":round(lat,6), "lon":round(lon,6), "side_length_m":frame["width"],
        "site_name":None}, reporter, root=destination_root, scene_name=name)
    if roads_source is not None:
        from experiments.import_road_shapefile import RoadImportConfig, preview_road_source, apply_road_preview
        preview = destination_root / ".migration-previews" / name
        from config.project_config import load_default_config
        data = load_default_config().data
        preview_road_source(RoadImportConfig(name, roads_source, preview, data.road_import_clip_buffer_m,
            data.road_import_excluded_classes, imported), root=destination_root)
        apply_road_preview(destination, preview, destination_root / ".migration-backups")
    if farmland_source is not None:
        from experiments.scene_data_import import preview_scene_data, commit_scene_data
        preview = preview_scene_data(destination, (farmland_source.name, farmland_source.read_bytes()))
        commit_scene_data(destination, preview["token"], backup_root=destination_root / ".migration-backups")
    if edits:
        from experiments.landuse_edits import create_landuse_edit
        target = scene_frame_info(destination)
        project = Transformer.from_crs(frame["crs"], target["crs"], always_xy=True)
        ta, _, tc, _, te, tf = target["transform"]
        for edit in edits:
            points = []
            for x,y in edit["points"]:
                tx,ty = project.transform(c+a*x, f+e*y)
                points.append(((tx-tc)/ta, (ty-tf)/te))
            create_landuse_edit(name, edit["class_id"], points, destination_root)
    with scene_write_lock(source.name, source.parent, blocking=True):
        if version != scene_data_version(source):
            raise ValueError("迁移期间原场景已变化，新场景暂不发布，请核对后重新迁移")
    target_record = json.loads((destination / "scene.json").read_text(encoding="utf-8"))
    target_record["title"] = record.get("title", source.name) + "（UTM）"
    write_json(destination / "scene.json", target_record)
    write_json(destination / "migration.json", {"source_scene":source.name, "source_version":version,
        "target_version":scene_data_version(destination), "nominal_side_m":frame["width"],
        "farmland_source":str(farmland_source) if farmland_source else None,
        "roads_source":str(roads_source) if roads_source else None})
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination_root", type=Path)
    parser.add_argument("--farmland-source", type=Path)
    parser.add_argument("--roads-source", type=Path)
    args = parser.parse_args()
    migrate_metric_scene(args.source, args.destination_root,
        lambda progress, stage, message: print(f"{progress:.2f} {stage} {message}", flush=True),
        farmland_source=args.farmland_source, roads_source=args.roads_source)


if __name__ == "__main__":
    main()
