"""Read classified CAD areas and align them with an existing scene grid."""
from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import numpy as np
from shapely.geometry import box, mapping, shape
from shapely.ops import polygonize, transform, unary_union

from data_tools.scene_coordinates import projection

CAD_CLASSES = {"field": 1, "road": 3, "building": 2, "water": 5}
LAYER_WORDS = {
    "field": ("农田", "耕地", "旱地", "水田", "田块", "farmland", "cropland", "field", "fields"),
    "building": ("建筑", "房屋", "房舍", "building", "buildings", "bldg", "house", "houses"),
    "road": ("道路", "路面", "公路", "街道", "road", "roads", "street", "streets", "highway"),
    "water": ("水体", "水域", "河流", "河道", "湖泊", "池塘", "water", "river", "lake", "pond"),
}
AREA_TYPES = {"LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC", "ELLIPSE", "SPLINE", "HATCH", "MPOLYGON", "SOLID", "TRACE", "3DFACE", "LINE"}
ANNOTATIONS = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF", "DIMENSION", "LEADER", "MLEADER", "POINT", "VIEWPORT"}


def suggest_layer_kind(name: str) -> str | None:
    words = set(re.findall(r"[a-z]+", name.lower()))
    matches = [kind for kind, keys in LAYER_WORDS.items()
               if any(key in words if key.isascii() else key in name for key in keys)]
    return matches[0] if len(matches) == 1 else None


def _dxf_path(source: Path, temporary: Path, converter: str | None) -> tuple[Path, list[str]]:
    if source.suffix.lower() == ".dxf":
        return source, []
    executable = converter or os.getenv("CAD_DWG_CONVERTER") or shutil.which("dwg2dxf")
    if not executable:
        raise ValueError("读取 DWG 需要 LibreDWG dwg2dxf，请配置 CAD_DWG_CONVERTER；也可上传 DXF")
    target = temporary / "drawing.dxf"
    try:
        result = subprocess.run([executable, "-o", str(target), str(source.resolve())],
                                capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"DWG 转换器无法完成转换：{exc}") from exc
    diagnostics = result.stderr.decode("utf-8", errors="replace").strip()
    if result.returncode or not target.is_file():
        raise ValueError(f"DWG 转换失败（退出码 {result.returncode}）：{diagnostics[-1500:]}")
    return target, [f"DWG 转换诊断：{diagnostics[-1500:]}，请核对图层预览。"] if diagnostics else []


def read_cad_drawing(source: Path, *, converter: str | None = None, curve_tolerance: float = 0.1) -> dict:
    try:
        import ezdxf
    except ImportError as exc:
        raise ValueError("CAD 解析需要 ezdxf，请安装项目数据处理依赖") from exc
    from ezdxf.addons.geo import proxy
    from ezdxf.xclip import XClip

    if not np.isfinite(curve_tolerance) or curve_tolerance <= 0:
        raise ValueError("CAD 曲线容差必须为有限正数")
    source = Path(source)
    if source.suffix.lower() not in {".dwg", ".dxf"}:
        raise ValueError("CAD 文件必须为 DWG 或 DXF")
    with tempfile.TemporaryDirectory(prefix="cad-read-") as temporary:
        path, warnings = _dxf_path(source, Path(temporary), converter)
        try:
            document = ezdxf.readfile(path)
        except (ezdxf.DXFError, OSError, UnicodeError, ValueError) as exc:
            raise ValueError(f"CAD 文件无法解析：{exc}") from exc
    layers: dict[str, dict] = {}
    features = []
    linework: dict[str, list] = {}

    def layer_record(name):
        if name not in layers:
            layers[name] = {"name": name, "entity_count": 0, "polygon_count": 0,
                            "open_line_count": 0, "invalid_count": 0, "unsupported_count": 0,
                            "suggested_kind": suggest_layer_kind(name), "entity_types": Counter()}
        return layers[name]

    def add_polygon(name, geometry):
        record = layer_record(name)
        if geometry.is_empty or not geometry.is_valid or not np.isfinite(geometry.bounds).all() or geometry.area <= 0:
            record["invalid_count"] += 1
            return
        for polygon in geometry.geoms if geometry.geom_type == "MultiPolygon" else [geometry]:
            features.append({"layer": name, "geometry": mapping(polygon)})
            record["polygon_count"] += 1

    def visit(entities, inherited="0", depth=0):
        if depth > 32:
            raise ValueError("CAD 块引用嵌套超过 32 层，请展开或修正循环引用")
        for entity in entities:
            name = entity.dxf.layer
            if name == "0":
                name = inherited
            record = layer_record(name)
            kind = entity.dxftype()
            record["entity_count"] += 1
            record["entity_types"][kind] += 1
            if kind == "INSERT":
                if entity.block() is None or entity.block().block.dxf.flags & 12 or XClip(entity).has_clipping_path:
                    record["unsupported_count"] += 1
                    continue
                def skipped(_entity, _reason):
                    record["unsupported_count"] += 1
                for instance in entity.multi_insert() if entity.mcount > 1 else [entity]:
                    visit(instance.virtual_entities(skipped_entity_callback=skipped), name, depth + 1)
                continue
            if kind in ANNOTATIONS:
                continue
            if kind not in AREA_TYPES:
                record["unsupported_count"] += 1
                continue
            try:
                geometry = shape(proxy(entity, distance=curve_tolerance).__geo_interface__)
            except (TypeError, ValueError, ZeroDivisionError):
                record["invalid_count"] += 1
                continue
            if geometry.geom_type in {"Polygon", "MultiPolygon"}:
                add_polygon(name, geometry)
            elif geometry.geom_type in {"LineString", "MultiLineString"}:
                if geometry.is_empty or not geometry.is_valid or not np.isfinite(geometry.bounds).all():
                    record["invalid_count"] += 1
                    continue
                linework.setdefault(name, []).extend(geometry.geoms if geometry.geom_type == "MultiLineString" else [geometry])
    visit(document.modelspace())
    for name, lines in linework.items():
        network = unary_union(lines)
        areas = list(polygonize(network))
        for polygon in areas:
            add_polygon(name, polygon)
        boundary = unary_union([polygon.boundary for polygon in areas]) if areas else None
        layers[name]["open_line_count"] = sum(boundary is None or not boundary.covers(line) for line in lines)
    for record in layers.values():
        record["entity_types"] = dict(record["entity_types"])
    return {"layers": list(layers.values()), "features": features,
            "drawing_units": int(document.header.get("$INSUNITS", 0)), "warnings": warnings}


def rasterize_cad_landuse(drawing: dict, source_crs: str, layer_kinds: dict[str, str], frame: dict) -> tuple[np.ndarray, dict]:
    from affine import Affine
    from rasterio.features import rasterize

    if not source_crs.strip():
        raise ValueError("请明确填写 CAD 源坐标系，不按图纸范围猜测坐标系")
    from pyproj import CRS
    from pyproj.exceptions import CRSError
    try:
        transformer = projection(CRS.from_user_input(source_crs), frame["crs"])
    except CRSError as exc:
        raise ValueError("CAD 源坐标系无效，请填写 EPSG 代码或有效 CRS") from exc
    known = {layer["name"]: layer for layer in drawing["layers"]}
    if set(layer_kinds) - set(known):
        raise ValueError("图层映射含 CAD 中不存在的图层")
    for name, layer in known.items():
        selected = layer_kinds.get(name)
        if selected is not None and selected not in {*CAD_CLASSES, "ignore"}:
            raise ValueError(f"图层 {name} 的用地类别无效")
        if selected != "ignore" and any(layer[key] for key in ("polygon_count", "invalid_count", "unsupported_count", "open_line_count")):
            if selected is None:
                raise ValueError(f"请为图层 {name} 指定用地类别或明确忽略")
            if layer["invalid_count"] or layer["unsupported_count"] or layer["open_line_count"]:
                raise ValueError(f"图层 {name} 有无效、未闭合或不支持的图形，请修正或忽略该层")
    affine = Affine(*frame["transform"])
    height, width = int(frame["height"]), int(frame["width"])
    corners = [affine * point for point in ((0, 0), (width, 0), (width, height), (0, height))]
    extent = box(min(p[0] for p in corners), min(p[1] for p in corners), max(p[0] for p in corners), max(p[1] for p in corners))
    shapes = []
    feature_counts = {}
    for kind, class_id in CAD_CLASSES.items():
        count = 0
        for feature in drawing["features"]:
            if layer_kinds.get(feature["layer"]) != kind:
                continue
            geometry = transform(lambda x, y, z=None: transformer.transform(x, y), shape(feature["geometry"]))
            if not geometry.is_valid or not np.isfinite(geometry.bounds).all():
                raise ValueError(f"图层 {feature['layer']} 投影后几何无效，请核对源坐标系")
            geometry = geometry.intersection(extent)
            if geometry.is_empty or geometry.area <= 0:
                continue
            shapes.append((mapping(geometry), class_id))
            count += 1
        feature_counts[kind] = count
    if not shapes:
        raise ValueError("没有与当前场景相交的可用地物面；请检查图层类别和坐标系，行政边界不能代替建筑、农田等地物")
    result = rasterize(shapes, out_shape=(height, width), transform=affine,
                       fill=-1, dtype="int16", all_touched=True).astype(np.int8)
    counts = {kind: int(np.count_nonzero(result == value)) for kind, value in CAD_CLASSES.items()}
    if not any(counts.values()):
        raise ValueError("CAD 地物未覆盖当前场景的任何栅格")
    return result, {"source_crs": source_crs, "layer_kinds": layer_kinds, "feature_counts": feature_counts,
                    "cell_counts": counts, "covered_area_m2": int(np.count_nonzero(result >= 0))}
