"""Preview an external road source, then optionally publish its road products."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
from uuid import uuid4

import numpy as np

from config.project_config import DEFAULT_CONFIG_PATH, load_project_config
from data_tools.io_utils import write_json
from data_tools.traffic_tool import build_road_product
from experiments.coordinate_scene import scene_write_lock
from experiments.protected_farmland import (
    _extract_zip, _grid_signature, _read_sidecars, _scene_bounds, _source_crs,
)
from experiments.scene_store import (
    SCENE_METADATA, _validate_road_arrays, ensure_scene_readable,
    publish_road_bundle, scene_directory, scene_frame_info, scenes_root,
)


@dataclass(frozen=True)
class RoadImportConfig:
    scene_name: str
    source_path: Path
    output_dir: Path
    clip_buffer_m: float
    excluded_classes: tuple[str, ...]
    provider: str


def _extract_source(source: Path, destination: Path) -> dict[str, Path]:
    if source.suffix.lower() == ".shp":
        members = {suffix: source.with_suffix(f".{suffix}") for suffix in ("shp", "shx", "dbf", "prj", "cpg")}
        for suffix in ("shp", "shx", "dbf", "prj"):
            if not members[suffix].is_file():
                raise FileNotFoundError(members[suffix])
        return {key: value for key, value in members.items() if value.is_file()}
    destination.mkdir(parents=True)
    if source.suffix.lower() == ".zip":
        return _extract_zip(source.read_bytes(), destination)
    if source.suffix.lower() != ".rar":
        raise ValueError("road source must be a Shapefile, ZIP or RAR")
    bsdtar = shutil.which("bsdtar")
    if bsdtar is None:
        raise RuntimeError("RAR 道路导入需要安装 bsdtar（libarchive）；也可以先解压后指定 .shp")
    names = subprocess.check_output([bsdtar, "-tf", str(source)], text=True).splitlines()
    members: dict[str, Path] = {}
    stems = set()
    for name in names:
        path = PurePosixPath(name)
        suffix = path.suffix.lower().lstrip(".")
        if suffix not in {"shp", "shx", "dbf", "prj", "cpg"}:
            continue
        if path.is_absolute() or ".." in path.parts or suffix in members:
            raise ValueError("RAR must contain one Shapefile with safe member paths")
        stems.add(str(path.with_suffix("")))
        target = destination / f"roads.{suffix}"
        with target.open("wb") as stream:
            subprocess.run([bsdtar, "-xOf", str(source), name], stdout=stream, check=True)
        members[suffix] = target
    if len(stems) != 1 or not {"shp", "shx", "dbf", "prj"}.issubset(members):
        raise ValueError("RAR must contain same-name shp, shx, dbf and prj files")
    return members


def _source_features(members: dict[str, Path], frame: dict, config: RoadImportConfig) -> tuple[dict, dict]:
    import shapefile
    from shapely.geometry import LineString, box

    from data_tools.scene_coordinates import projection

    prj, encoding = _read_sidecars(members)
    source_crs = _source_crs(prj)
    to_map = projection(source_crs, frame["crs"])
    to_source = projection(frame["crs"], source_crs)
    to_geo = projection(frame["crs"], "EPSG:4326")
    clip = box(*_scene_bounds(frame)).buffer(config.clip_buffer_m)
    source_bounds = to_source.transform_bounds(*clip.bounds)
    included: Counter = Counter()
    excluded: Counter = Counter()
    features = []
    with shapefile.Reader(str(members["shp"]), encoding=encoding or "utf-8") as reader:
        fields = [field[0] for field in reader.fields[1:]]
        if config.excluded_classes and "class" not in fields:
            raise ValueError(f"指定排除类别时，Shapefile 必须包含 class 字段；实际字段：{', '.join(fields)}")
        feature_count = len(reader)
        for item in reader.iterShapeRecords(bbox=source_bounds):
            if item.shape.shapeType == 0:
                continue
            if item.shape.shapeType not in {3, 13, 23}:
                raise ValueError("道路导入只接受 PolyLine，不接受面或点图层")
            properties = item.record.as_dict()
            road_class = str(properties.get("class", ""))
            if road_class in config.excluded_classes:
                excluded[road_class] += 1
                continue
            points = np.asarray(item.shape.points, dtype=np.float64)
            if not np.isfinite(points).all():
                raise ValueError("road source contains nonfinite coordinates")
            ends = list(item.shape.parts) + [len(points)]
            for part, (start, end) in enumerate(zip(ends, ends[1:])):
                if end - start < 2:
                    continue
                x, y = to_map.transform(points[start:end, 0], points[start:end, 1])
                geometry = LineString(np.column_stack((x, y))).intersection(clip)
                lines = [geometry] if geometry.geom_type == "LineString" else getattr(geometry, "geoms", ())
                for piece, line in enumerate(lines):
                    if line.geom_type != "LineString" or line.is_empty or line.length <= 0:
                        continue
                    coords = np.asarray(line.coords)
                    lon, lat = to_geo.transform(coords[:, 0], coords[:, 1])
                    features.append({
                        "type": "Feature",
                        "properties": {
                            **properties, "@id": f"{config.provider}/{item.shape.oid}/{part}/{piece}",
                            "tunnel": properties.get("road_detai") == "隧道",
                        },
                        "geometry": {"type": "LineString", "coordinates": np.column_stack((lon, lat)).tolist()},
                    })
                    included[road_class] += 1
    if not features:
        raise ValueError("道路源在当前场景和指定缓冲范围内没有可用道路")
    summary = {
        "source_crs": source_crs.to_string(), "source_crs_wkt": source_crs.to_wkt(),
        "feature_count": feature_count, "included_parts": len(features),
        "included_classes": dict(included), "excluded_classes": list(config.excluded_classes),
        "excluded_feature_counts": dict(excluded), "clip_buffer_m": config.clip_buffer_m,
    }
    return {"type": "FeatureCollection", "features": features}, summary


def _road_signature(scene: Path) -> dict:
    return {name: [(scene / name).stat().st_mtime_ns, (scene / name).stat().st_size]
            for name in ("road_segments_local.npy", "road_voronoi_1m.npy", "road_segment_kind.npy")}


def preview_road_source(config: RoadImportConfig, *, root: Path | None = None,
                        config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    if not np.isfinite(config.clip_buffer_m) or config.clip_buffer_m < 0:
        raise ValueError("clip_buffer_m must be finite and nonnegative")
    if not config.provider.strip():
        raise ValueError("provider must be explicit")
    source = config.source_path.expanduser().resolve(strict=True)
    scene = scene_directory(scenes_root(root), config.scene_name).resolve()
    ensure_scene_readable(scene)
    frame = scene_frame_info(scene)
    if frame is None:
        raise ValueError("scene has no prepared reference grid")
    grid_signature = _grid_signature(scene)
    previous_roads = _road_signature(scene)
    output = config.output_dir.expanduser().resolve()
    if output == scene or scene in output.parents:
        raise ValueError("road trial output must be outside the published scene")
    output.mkdir(parents=True, exist_ok=False)
    members = _extract_source(source, output / "source")
    raw, import_info = _source_features(members, frame, config)
    geojson = output / "roads_wgs84.geojson"
    write_json(geojson, raw)
    data = load_project_config(config_path).data
    segments, voronoi, kinds, metadata = build_road_product(
        geojson, output / "road_segments_local.npy", output / "road_voronoi_1m.npy",
        None, (frame["height"], frame["width"]), data.road_dp_tolerance_m, data.road_resolution_m,
        voronoi_backend=data.road_voronoi_backend, voronoi_device=data.road_voronoi_device,
        voronoi_chunk_points=data.road_voronoi_chunk_points, voronoi_segment_tile=data.road_voronoi_segment_tile,
        reference_frame=frame, kind_rules=data.road_kind_rules,
    )
    _validate_road_arrays(segments, voronoi, (frame["height"], frame["width"]), kinds)
    digest = hashlib.sha256()
    for suffix in ("shp", "shx", "dbf", "prj", "cpg"):
        if suffix in members:
            digest.update(suffix.encode())
            with members[suffix].open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
    metadata.update({"provider": config.provider, "source_name": source.name,
                     "source_sha256": digest.hexdigest(), "import": import_info,
                     "road_product_id": uuid4().hex})
    for name in ("road_segments_local.json", "road_voronoi_1m.json"):
        write_json(output / name, metadata)
    if grid_signature != _grid_signature(scene) or previous_roads != _road_signature(scene):
        raise ValueError("候选构建过程中场景网格或路网已变化，请重新生成候选")
    summary = {"scene_id": scene.name, "grid_signature": grid_signature,
               "previous_road_signature": previous_roads, "road": metadata, "applied": False}
    write_json(output / "import_summary.json", summary)
    return summary


def apply_road_preview(scene: Path, preview: Path, backup_root: Path) -> Path:
    scene, preview = scene.resolve(), preview.resolve()
    summary = json.loads((preview / "import_summary.json").read_text(encoding="utf-8"))
    for name in ("road_segments_local.npy", "road_segment_kind.npy", "road_voronoi_1m.npy", "road_segments_local.json", "road_voronoi_1m.json"):
        if not (preview / name).is_file():
            raise FileNotFoundError(preview / name)
    with scene_write_lock(scene.name, scene.parent):
        ensure_scene_readable(scene)
        if summary["scene_id"] != scene.name or summary["grid_signature"] != _grid_signature(scene):
            raise ValueError("场景网格已变化或预览不属于当前场景，请重新生成候选")
        if summary["previous_road_signature"] != _road_signature(scene):
            raise ValueError("正式路网已变化，请重新生成候选")
        frame = scene_frame_info(scene)
        _validate_road_arrays(np.load(preview / "road_segments_local.npy", mmap_mode="r"),
                             np.load(preview / "road_voronoi_1m.npy", mmap_mode="r"),
                             (frame["height"], frame["width"]),
                             np.load(preview / "road_segment_kind.npy", mmap_mode="r"))
        from experiments.scene_data_import import ROAD_SOURCE, stage_road_record
        from experiments.scene_store import ROAD_PRODUCT_FILES
        road_meta = {**summary["road"], "source_path": ROAD_SOURCE}
        stage_road_record(scene, preview, road_meta, preview / "roads_wgs84.geojson")
        backup = publish_road_bundle(scene, preview, backup_root, road_meta["road_product_id"],
                                     files=(*ROAD_PRODUCT_FILES, ROAD_SOURCE, "scene.json"))
    from experiments.protected_farmland import invalidate_runtime_caches
    invalidate_runtime_caches()
    summary.update({"applied": True, "backup": str(backup), "applied_at": datetime.now(timezone.utc).isoformat()})
    write_json(preview / "import_summary.json", summary)
    return backup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--buffer-m", type=float, required=True)
    parser.add_argument("--exclude-class", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    config = RoadImportConfig(args.scene, args.source, args.output_dir, args.buffer_m,
                              tuple(args.exclude_class), args.provider)
    summary = preview_road_source(config)
    if args.apply:
        backup = apply_road_preview(scene_directory(scenes_root(), args.scene), args.output_dir,
                                    Path("outputs/scene-road-backups"))
        print("Previous road bundle:", backup)
    print(json.dumps({"scene": args.scene, "provider": args.provider,
                      "segments": summary["road"]["n_segments"], "applied": args.apply}, ensure_ascii=False))


if __name__ == "__main__":
    main()
