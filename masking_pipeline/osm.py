#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract a local OSM road graph around a reference satellite GeoTIFF.

Roads are not cut on the study-area boundary. The extraction window is that
area plus ``road_buffer_m`` in the reference CRS (EPSG:3857 metres for the
current satellite product — projected metres, not geodesic distance). Ways
that continue far past the window keep one real OSM vertex outside it, and
only when that vertex is within ``max_outside_m``. Shared OSM node ids are
preserved. Planar crossings are not noded, so a bridge over another road
does not become a junction.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from geo_utils import (
    bounds_center,
    bounds_contain,
    buffer_bounds,
    distance_outside_bounds,
    point_in_bounds,
    polyline_length_haversine,
    polyline_length_xy,
    segment_intersects_bounds,
    transform_bounds,
    transform_xy,
)
from osm_pbf import collect_highway_ways, read_pbf_header

INCLUDED_HIGHWAYS = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "unclassified",
        "residential",
        "living_street",
        "service",
        "track",
        "road",
        "busway",
        "escape",
    }
)

_KEPT_TAGS = (
    "highway",
    "name",
    "bridge",
    "tunnel",
    "layer",
    "access",
    "motor_vehicle",
    "service",
    "oneway",
)

HIGHWAY_COLORS = {
    "motorway": "#e31a1c",
    "motorway_link": "#e31a1c",
    "trunk": "#ff7f00",
    "trunk_link": "#ff7f00",
    "primary": "#fdbf6f",
    "primary_link": "#fdbf6f",
    "secondary": "#b2df8a",
    "secondary_link": "#b2df8a",
    "tertiary": "#33a02c",
    "tertiary_link": "#33a02c",
    "unclassified": "#6a3d9a",
    "residential": "#1f78b4",
    "living_street": "#a6cee3",
    "service": "#b15928",
    "track": "#8c510a",
    "road": "#666666",
    "busway": "#e7298a",
    "escape": "#666666",
}


class UnionFind:
    def __init__(self) -> None:
        self.parent: Dict[int, int] = {}
        self.rank: Dict[int, int] = {}

    def add(self, item: int) -> None:
        if item not in self.parent:
            self.parent[item] = item
            self.rank[item] = 0

    def find(self, item: int) -> int:
        parent = self.parent
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        self.add(left)
        self.add(right)
        a = self.find(left)
        b = self.find(right)
        if a == b:
            return
        if self.rank[a] < self.rank[b]:
            a, b = b, a
        self.parent[b] = a
        if self.rank[a] == self.rank[b]:
            self.rank[a] += 1


def _empty_tags(tags: Dict[str, str], way_id: int, part: int) -> dict:
    props = {"@id": f"way/{way_id}", "osm_way_id": int(way_id), "part": int(part)}
    for key in _KEPT_TAGS:
        props[key] = tags.get(key)
    return props


def _effective_level(props: dict) -> int:
    layer = props.get("layer")
    if layer not in (None, ""):
        try:
            return int(str(layer))
        except ValueError:
            return 0
    bridge = str(props.get("bridge") or "").strip().lower()
    tunnel = str(props.get("tunnel") or "").strip().lower()
    bridge_on = bridge not in {"", "0", "false", "no", "none"}
    tunnel_on = tunnel not in {"", "0", "false", "no", "none"}
    if bridge_on and not tunnel_on:
        return 1
    if tunnel_on and not bridge_on:
        return -1
    return 0


def clip_way_parts(
    node_ids: Sequence[int],
    lonlat: Sequence[Tuple[float, float]],
    xy: Sequence[Tuple[float, float]],
    extraction_lonlat: Sequence[float],
    extraction_xy: Sequence[float],
    max_outside_m: float,
) -> List[Tuple[List[int], List[Tuple[float, float]]]]:
    """Keep vertices inside the extraction box, plus one adjacent OSM vertex.

    The extra vertex is a real OSM node and is dropped when it lies farther
    than ``max_outside_m`` (reference-CRS units) outside the box. No synthetic
    intersection point is inserted.
    """
    if len(node_ids) != len(lonlat) or len(node_ids) != len(xy):
        raise ValueError("way node, lon/lat, and projected coordinate lengths differ")
    inside = [point_in_bounds(lon, lat, tuple(extraction_lonlat)) for lon, lat in lonlat]
    parts: List[Tuple[List[int], List[Tuple[float, float]]]] = []
    index = 0
    n = len(node_ids)
    while index < n:
        if not inside[index]:
            index += 1
            continue
        start = index
        end = index
        while end + 1 < n and inside[end + 1]:
            end += 1
        lo, hi = start, end
        if start - 1 >= 0:
            dist = distance_outside_bounds(xy[start - 1][0], xy[start - 1][1], tuple(extraction_xy))
            if dist <= max_outside_m:
                lo = start - 1
        if end + 1 < n:
            dist = distance_outside_bounds(xy[end + 1][0], xy[end + 1][1], tuple(extraction_xy))
            if dist <= max_outside_m:
                hi = end + 1
        if hi > lo:
            parts.append((list(node_ids[lo : hi + 1]), list(lonlat[lo : hi + 1])))
        index = end + 1
    return parts


def iter_feature_segments(feature: dict) -> Iterable[Tuple[Tuple[float, float], Tuple[float, float], int, int]]:
    node_ids = feature["node_ids"]
    coords = feature["geometry"]["coordinates"]
    for i in range(len(coords) - 1):
        yield tuple(coords[i]), tuple(coords[i + 1]), int(node_ids[i]), int(node_ids[i + 1])


def feature_intersects_bounds(feature: dict, bounds) -> bool:
    coords = feature["geometry"]["coordinates"]
    if any(point_in_bounds(lon, lat, bounds) for lon, lat in coords):
        return True
    for (lon1, lat1), (lon2, lat2), _a, _b in iter_feature_segments(feature):
        if segment_intersects_bounds(lon1, lat1, lon2, lat2, bounds):
            return True
    return False


def _orient(p, q, r) -> float:
    return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])


def _proper_crossing(a, b, c, d) -> bool:
    o1 = _orient(a, b, c)
    o2 = _orient(a, b, d)
    o3 = _orient(c, d, a)
    o4 = _orient(c, d, b)
    if o1 == 0 or o2 == 0 or o3 == 0 or o4 == 0:
        return False
    return (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0)


def connectivity_report(features: Sequence[dict], target_lonlat: Sequence[float]) -> dict:
    """Component stats from shared OSM node ids only.

    Two roads that cross in plan, including a bridge over a surface road,
    stay disconnected unless they share an OSM node.
    """
    uf = UnionFind()
    edge_records = []
    for feature in features:
        level = _effective_level(feature["properties"])
        xy = feature.get("xy") or []
        coords = feature["geometry"]["coordinates"]
        node_ids = feature["node_ids"]
        if len(xy) != len(coords):
            raise ValueError("feature is missing projected coordinates")
        for i in range(len(coords) - 1):
            left = int(node_ids[i])
            right = int(node_ids[i + 1])
            uf.add(left)
            uf.add(right)
            if left != right:
                uf.union(left, right)
            projected = polyline_length_xy(
                (xy[i][0], xy[i + 1][0]),
                (xy[i][1], xy[i + 1][1]),
            )
            ground = polyline_length_haversine((coords[i], coords[i + 1]))
            edge_records.append((left, right, projected, ground, level, (xy[i], xy[i + 1])))

    length_by_root: Dict[int, float] = defaultdict(float)
    ground_by_root: Dict[int, float] = defaultdict(float)
    nodes_by_root: Dict[int, set] = defaultdict(set)
    for left, right, projected, ground, _level, _seg in edge_records:
        root = uf.find(left)
        length_by_root[root] += projected
        ground_by_root[root] += ground
        nodes_by_root[root].add(left)
        nodes_by_root[root].add(right)
    # Isolated vertices should not occur; still count nodes that never joined an edge.
    for node in uf.parent:
        root = uf.find(node)
        nodes_by_root[root].add(node)

    hits = {}
    for feature in features:
        if not feature_intersects_bounds(feature, tuple(target_lonlat)):
            continue
        if not feature["node_ids"]:
            continue
        root = uf.find(int(feature["node_ids"][0]))
        hits[root] = True

    components = []
    for root, length in length_by_root.items():
        components.append(
            {
                "node_count": len(nodes_by_root[root]),
                "projected_length_m": length,
                "ground_length_m": ground_by_root[root],
                "intersects_target": bool(hits.get(root)),
            }
        )
    components.sort(key=lambda item: (-item["projected_length_m"], -item["node_count"]))
    total_projected = float(sum(item["projected_length_m"] for item in components))
    total_ground = float(sum(item["ground_length_m"] for item in components))
    largest = components[0]["projected_length_m"] if components else 0.0
    largest_ratio = (largest / total_projected) if total_projected > 0 else 0.0
    target_components = [item for item in components if item["intersects_target"]]
    isolated_target = target_components[1:] if len(target_components) > 1 else []
    # A target component is isolated from the main network when it is not the
    # single longest component overall.
    if components:
        main_length = components[0]["projected_length_m"]
        isolated_target = [
            item
            for item in target_components
            if item["projected_length_m"] < main_length - 1e-6
        ]
    crossing = _count_level_crossings(edge_records)
    return {
        "component_count": len(components),
        "components": components[:50],
        "projected_length_m": total_projected,
        "ground_length_m_haversine": total_ground,
        "length_note": (
            "projected_length_m is EPSG:3857 Euclidean length, not ground distance. "
            "ground_length_m_haversine uses a sphere of radius 6371008.8 m."
        ),
        "largest_component_projected_length_ratio": largest_ratio,
        "target_intersecting_component_count": len(target_components),
        "isolated_target_component_count": len(isolated_target),
        "isolated_target_components": isolated_target[:20],
        "unconnected_grade_separated_crossings": crossing,
        "topology_evidence": "shared_osm_node_ids",
        "planar_crossings_connected": False,
    }


def _count_level_crossings(edge_records) -> int:
    if len(edge_records) > 20000:
        return -1
    cells: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    cell = 250.0
    indexed = []
    for idx, (_left, _right, _proj, _ground, level, seg) in enumerate(edge_records):
        (x1, y1), (x2, y2) = seg
        indexed.append((idx, level, (x1, y1), (x2, y2), { _left, _right }))
        cx0 = int(math.floor(min(x1, x2) / cell))
        cx1 = int(math.floor(max(x1, x2) / cell))
        cy0 = int(math.floor(min(y1, y2) / cell))
        cy1 = int(math.floor(max(y1, y2) / cell))
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                cells[(cx, cy)].append(idx)
    seen = set()
    count = 0
    by_index = {item[0]: item for item in indexed}
    for members in cells.values():
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                pair = (a, b) if a < b else (b, a)
                if pair in seen:
                    continue
                seen.add(pair)
                ia, level_a, a1, a2, nodes_a = by_index[a]
                ib, level_b, b1, b2, nodes_b = by_index[b]
                del ia, ib
                if level_a == level_b or nodes_a & nodes_b:
                    continue
                if _proper_crossing(a1, a2, b1, b2):
                    count += 1
    return count


def _highway_histogram(features: Sequence[dict]) -> Dict[str, int]:
    hist: Dict[str, int] = defaultdict(int)
    for feature in features:
        hist[str(feature["properties"].get("highway") or "unknown")] += 1
    return dict(sorted(hist.items(), key=lambda item: (-item[1], item[0])))


def build_road_features(
    ways,
    nodes: Dict[int, Tuple[float, float]],
    ref_crs: str,
    extraction_lonlat: Sequence[float],
    extraction_xy: Sequence[float],
    max_outside_m: float,
) -> Tuple[List[dict], int]:
    raw_count = len(ways)
    features: List[dict] = []
    for way_id, tags, refs in ways:
        kept_ids = [ref for ref in refs if ref in nodes]
        if len(kept_ids) < 2:
            continue
        # Preserve gaps: a missing node splits the way instead of drawing a chord.
        runs: List[List[int]] = []
        current: List[int] = []
        previous_present = False
        for ref in refs:
            if ref in nodes:
                if not previous_present and current:
                    runs.append(current)
                    current = []
                current.append(ref)
                previous_present = True
            else:
                if current:
                    runs.append(current)
                    current = []
                previous_present = False
        if current:
            runs.append(current)
        part_index = 0
        for run in runs:
            if len(run) < 2:
                continue
            lonlat = [nodes[ref] for ref in run]
            xs, ys = transform_xy("EPSG:4326", ref_crs, [p[0] for p in lonlat], [p[1] for p in lonlat])
            xy = list(zip(xs, ys))
            parts = clip_way_parts(run, lonlat, xy, extraction_lonlat, extraction_xy, max_outside_m)
            for part_ids, part_lonlat in parts:
                if len(part_ids) < 2:
                    continue
                px, py = transform_xy(
                    "EPSG:4326",
                    ref_crs,
                    [p[0] for p in part_lonlat],
                    [p[1] for p in part_lonlat],
                )
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[lon, lat] for lon, lat in part_lonlat],
                        },
                        "properties": _empty_tags(tags, way_id, part_index),
                        "node_ids": [int(n) for n in part_ids],
                        "xy": [[float(x), float(y)] for x, y in zip(px, py)],
                    }
                )
                part_index += 1
    return features, raw_count


def features_to_geojson(features: Sequence[dict]) -> dict:
    exported = []
    for feature in features:
        geom = feature["geometry"]
        if geom.get("type") not in {"LineString", "MultiLineString"}:
            raise ValueError(f"refusing to export geometry type {geom.get('type')}")
        exported.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": feature["properties"],
            }
        )
    return {
        "type": "FeatureCollection",
        "name": "osm_roads",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
        },
        "features": exported,
    }


def _node_window(extraction_lonlat: Sequence[float], max_outside_m: float) -> Tuple[float, float, float, float]:
    west, south, east, north = extraction_lonlat
    mid_lat = (south + north) / 2.0
    dlat = (max_outside_m + 50.0) / 110540.0
    dlon = (max_outside_m + 50.0) / (111320.0 * max(0.2, math.cos(math.radians(mid_lat))))
    return west - dlon, south - dlat, east + dlon, north + dlat


def read_reference_bounds(reference_geotiff_path: str) -> dict:
    import rasterio

    with rasterio.open(reference_geotiff_path) as src:
        if src.crs is None:
            raise ValueError(f"reference GeoTIFF has no CRS: {reference_geotiff_path}")
        bounds = (float(src.bounds.left), float(src.bounds.bottom), float(src.bounds.right), float(src.bounds.top))
        return {
            "path": os.path.abspath(reference_geotiff_path),
            "crs": str(src.crs),
            "bounds": list(bounds),
            "transform": [float(v) for v in src.transform][:6],
            "width": int(src.width),
            "height": int(src.height),
            "count": int(src.count),
        }


def _osmium_executable() -> Optional[str]:
    env_path = os.environ.get("OSMIUM")
    if env_path and os.path.isfile(env_path):
        return env_path
    found = shutil.which("osmium")
    if found:
        return found
    candidate = os.path.expanduser("~/miniconda3/envs/route_plan/bin/osmium")
    if os.path.isfile(candidate):
        return candidate
    return None


def osmium_version(executable: str) -> str:
    result = subprocess.run([executable, "--version"], check=True, capture_output=True, text=True)
    line = (result.stdout or result.stderr).splitlines()
    return line[0].strip() if line else "unknown"


def osmium_file_header(executable: str, pbf_path: str) -> dict:
    result = subprocess.run(
        [executable, "fileinfo", "-j", pbf_path],
        capture_output=True,
        text=True,
        check=True,
    )
    info = json.loads(result.stdout)
    header = info.get("header") or {}
    option = header.get("option") or {}
    boxes = header.get("boxes") or []
    return {
        "bbox_lonlat": boxes[0] if boxes else None,
        "writingprogram": option.get("generator"),
        "source": option.get("osmosis_replication_base_url"),
        "osmosis_replication_timestamp": option.get("osmosis_replication_timestamp") or option.get("timestamp"),
        "osmosis_replication_sequence_number": option.get("osmosis_replication_sequence_number"),
        "required_features": ["OsmSchema-V0.6", "DenseNodes"],
        "optional_features": [option.get("pbf_optional_feature_0")] if option.get("pbf_optional_feature_0") else [],
    }


def extract_bbox_with_osmium(
    executable: str,
    pbf_path: str,
    lonlat_bbox: Sequence[float],
    output_pbf: str,
) -> None:
    """Keep complete ways that touch the bbox, then the Python clip limits extent."""
    west, south, east, north = lonlat_bbox
    os.makedirs(os.path.dirname(os.path.abspath(output_pbf)) or ".", exist_ok=True)
    cmd = [
        executable,
        "extract",
        "--bbox",
        f"{west},{south},{east},{north}",
        "--strategy",
        "complete_ways",
        "--overwrite",
        "--output",
        output_pbf,
        pbf_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"osmium extract failed ({result.returncode}): {detail}")


def extract_osm_roads(
    pbf_path: str,
    reference_geotiff_path: str,
    road_buffer_m: float = 500,
    output_geojson_path: Optional[str] = None,
    preview_png_path: Optional[str] = None,
    max_outside_m: float = 1500,
    highway_types: Optional[Iterable[str]] = None,
) -> dict:
    if road_buffer_m < 0 or max_outside_m < 0:
        raise ValueError("road buffers must be >= 0")
    if not os.path.isfile(pbf_path):
        raise FileNotFoundError(pbf_path)
    if not os.path.isfile(reference_geotiff_path):
        raise FileNotFoundError(reference_geotiff_path)

    ref = read_reference_bounds(reference_geotiff_path)
    target_xy = ref["bounds"]
    extraction_xy = buffer_bounds(target_xy, road_buffer_m)
    if not bounds_contain(extraction_xy, target_xy):
        raise RuntimeError("internal error: extraction bbox does not contain the target bbox")
    target_ll = transform_bounds(ref["crs"], "EPSG:4326", target_xy)
    extraction_ll = transform_bounds(ref["crs"], "EPSG:4326", extraction_xy)
    if not bounds_contain(extraction_ll, target_ll, tol=1e-9):
        raise RuntimeError("transformed extraction bbox does not contain the target bbox")

    allowed = set(highway_types or INCLUDED_HIGHWAYS)
    window = _node_window(extraction_ll, max_outside_m)
    print(
        f"OSM target lon/lat: [{target_ll[0]:.6f}, {target_ll[1]:.6f}, {target_ll[2]:.6f}, {target_ll[3]:.6f}]"
    )
    print(
        "OSM extraction lon/lat: "
        f"[{extraction_ll[0]:.6f}, {extraction_ll[1]:.6f}, {extraction_ll[2]:.6f}, {extraction_ll[3]:.6f}]"
    )
    print(f"Road buffer: {road_buffer_m} m in {ref['crs']} (projected units, not geodesic)")
    header = read_pbf_header(pbf_path)
    osmium_bin = _osmium_executable()
    source_pbf = pbf_path
    extract_method = "builtin_pbf_reader"
    temp_dir = None
    if osmium_bin:
        temp_dir = tempfile.mkdtemp(prefix="masking_osmium_")
        source_pbf = os.path.join(temp_dir, "complete_ways.pbf")
        version = osmium_version(osmium_bin)
        print(f"Using {version}: extract --strategy complete_ways")
        extract_bbox_with_osmium(osmium_bin, pbf_path, extraction_ll, source_pbf)
        extract_method = "osmium_extract_complete_ways"
        header = osmium_file_header(osmium_bin, pbf_path)
    else:
        print("WARNING: osmium was not found. Reading the regional PBF with the built-in parser.")
    try:
        _extracted_header, nodes, ways = collect_highway_ways(source_pbf, window, allowed, progress=print)
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
    features, raw_count = build_road_features(
        ways,
        nodes,
        ref["crs"],
        extraction_ll,
        extraction_xy,
        max_outside_m,
    )
    intersecting = sum(1 for feature in features if feature_intersects_bounds(feature, target_ll))
    report = connectivity_report(features, target_ll)
    histogram = _highway_histogram(features)
    both_flags = [
        feature["properties"].get("@id")
        for feature in features
        if _flag_on(feature["properties"].get("bridge")) and _flag_on(feature["properties"].get("tunnel"))
    ]
    summary = {
        "pbf_path": os.path.abspath(pbf_path),
        "pbf_header": header,
        "extract_method": extract_method,
        "osmium": osmium_version(osmium_bin) if osmium_bin else None,
        "reference": ref,
        "road_buffer_m": float(road_buffer_m),
        "buffer_units": f"{ref['crs']} projected metres, not geodesic ground distance",
        "max_outside_m": float(max_outside_m),
        "clip_policy": "vertices_inside_extraction_bbox_plus_one_adjacent_osm_node_within_max_outside_m",
        "target_bbox_projected": list(target_xy),
        "extraction_bbox_projected": list(extraction_xy),
        "target_bbox_wgs84": list(target_ll),
        "extraction_bbox_wgs84": list(extraction_ll),
        "extraction_contains_target": True,
        "highway_types": sorted(allowed),
        "raw_way_count": int(raw_count),
        "feature_count": len(features),
        "features_intersecting_target": int(intersecting),
        "highway_histogram": histogram,
        "bridge_and_tunnel_feature_ids": both_flags,
        "coordinate_collisions": _coordinate_collisions(features),
        "connectivity": report,
        "warning": None,
    }
    if report["largest_component_projected_length_ratio"] < 0.8 or report["isolated_target_component_count"] > 0:
        summary["warning"] = (
            "Road connectivity inside the default buffer is incomplete. "
            "This is not repaired automatically. Retry with --road-buffer-m 1000 "
            "(or larger) if a more connected approach network is required. "
            "Roads kept outside the study area do not mean every off-boundary detour is usable downstream."
        )
        print("WARNING:", summary["warning"])
    if both_flags:
        raise ValueError(
            "OSM features cannot be both bridge and tunnel: " + ", ".join(both_flags[:10])
        )
    if not features:
        raise RuntimeError(
            "No highway features were extracted for this extent. "
            "Check the PBF coverage, the reference GeoTIFF, and the highway filter."
        )
    longitudes = [coord[0] for feature in features for coord in feature["geometry"]["coordinates"]]
    latitudes = [coord[1] for feature in features for coord in feature["geometry"]["coordinates"]]
    if min(longitudes) < extraction_ll[0] - 0.2 or max(longitudes) > extraction_ll[2] + 0.2:
        raise RuntimeError(
            "Extracted road longitudes fall well outside the extraction window. "
            "The PBF coordinates were not decoded into WGS84."
        )
    if min(latitudes) < extraction_ll[1] - 0.2 or max(latitudes) > extraction_ll[3] + 0.2:
        raise RuntimeError(
            "Extracted road latitudes fall well outside the extraction window. "
            "The PBF coordinates were not decoded into WGS84."
        )
    if output_geojson_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_geojson_path)) or ".", exist_ok=True)
        with open(output_geojson_path, "w", encoding="utf-8") as handle:
            json.dump(features_to_geojson(features), handle, ensure_ascii=False)
        summary["geojson_path"] = os.path.abspath(output_geojson_path)
        print(f"Wrote OSM GeoJSON: {summary['geojson_path']} ({len(features)} features)")
    if preview_png_path:
        draw_osm_preview(
            features,
            target_xy,
            extraction_xy,
            ref["crs"],
            preview_png_path,
            summary,
        )
        summary["preview_png"] = os.path.abspath(preview_png_path)
    return summary


def _flag_on(value) -> bool:
    return str(value or "").strip().lower() not in {"", "0", "false", "no", "none"}


def _coordinate_collisions(features: Sequence[dict]) -> int:
    owners: Dict[Tuple[float, float], set] = defaultdict(set)
    for feature in features:
        for node_id, coord in zip(feature["node_ids"], feature["geometry"]["coordinates"]):
            owners[(round(coord[0], 7), round(coord[1], 7))].add(int(node_id))
    return sum(1 for ids in owners.values() if len(ids) > 1)


def draw_osm_preview(
    features: Sequence[dict],
    target_xy: Sequence[float],
    extraction_xy: Sequence[float],
    crs: str,
    preview_png_path: str,
    summary: dict,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch, Rectangle

    os.makedirs(os.path.dirname(os.path.abspath(preview_png_path)) or ".", exist_ok=True)
    fig, ax = plt.subplots(figsize=(10.5, 10.5))
    grouped: Dict[str, list] = defaultdict(list)
    for feature in features:
        highway = str(feature["properties"].get("highway") or "road")
        xs = [p[0] for p in feature["xy"]]
        ys = [p[1] for p in feature["xy"]]
        grouped[highway].append((xs, ys))
    for highway, lines in sorted(grouped.items()):
        color = HIGHWAY_COLORS.get(highway, "#444444")
        for xs, ys in lines:
            ax.plot(xs, ys, color=color, linewidth=1.1, solid_capstyle="round", zorder=2)

    def _rect(bounds, **kwargs):
        left, bottom, right, top = bounds
        return Rectangle((left, bottom), right - left, top - bottom, fill=False, **kwargs)

    ax.add_patch(
        _rect(extraction_xy, edgecolor="#ff7f0e", linestyle="--", linewidth=1.8, zorder=3, label="OSM extraction bbox")
    )
    ax.add_patch(_rect(target_xy, edgecolor="#1f77b4", linestyle="-", linewidth=2.0, zorder=4, label="target bbox"))
    cx, cy = bounds_center(tuple(target_xy))
    ax.scatter([cx], [cy], c="#111111", s=28, zorder=5, label="target center")

    present = []
    for highway in sorted(grouped):
        present.append(Line2D([0], [0], color=HIGHWAY_COLORS.get(highway, "#444444"), lw=2, label=highway))
    present.extend(
        [
            Patch(facecolor="none", edgecolor="#1f77b4", linewidth=2, label="target bbox"),
            Patch(facecolor="none", edgecolor="#ff7f0e", linewidth=1.8, linestyle="--", label="OSM extraction bbox"),
            Line2D([0], [0], marker="o", color="none", markerfacecolor="#111111", markersize=6, label="target center"),
        ]
    )
    ax.legend(handles=present, loc="upper left", fontsize=8, framealpha=0.92)
    conn = summary.get("connectivity") or {}
    text = (
        f"features {summary.get('feature_count', 0)}\n"
        f"raw ways {summary.get('raw_way_count', 0)}\n"
        f"projected length {conn.get('projected_length_m', 0):.0f} m\n"
        f"ground length {conn.get('ground_length_m_haversine', 0):.0f} m\n"
        f"components {conn.get('component_count', 0)}\n"
        f"largest share {conn.get('largest_component_projected_length_ratio', 0):.2f}\n"
        f"buffer {summary.get('road_buffer_m')} m in {crs}"
    )
    ax.text(
        0.99,
        0.01,
        text,
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=8,
        bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.9},
    )
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel(f"{crs} easting (m)")
    ax.set_ylabel(f"{crs} northing (m)")
    ax.set_title("OSM roads with target extent and extraction buffer")
    pad = max(80.0, 0.08 * (extraction_xy[2] - extraction_xy[0]))
    ax.set_xlim(extraction_xy[0] - pad, extraction_xy[2] + pad)
    ax.set_ylim(extraction_xy[1] - pad, extraction_xy[3] + pad)
    ax.grid(True, linewidth=0.3, alpha=0.4)
    fig.tight_layout()
    fig.savefig(preview_png_path, dpi=140)
    plt.close(fig)
    print(f"Wrote OSM preview: {preview_png_path}")


def load_geojson_features(path: str, reference_geotiff_path: str) -> List[dict]:
    """Reload a written GeoJSON and reattach projected coordinates for QA."""
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if raw.get("type") != "FeatureCollection":
        raise ValueError(f"OSM file is not a FeatureCollection: {path}")
    ref = read_reference_bounds(reference_geotiff_path)
    features = []
    for feature in raw.get("features", []):
        geom = feature.get("geometry") or {}
        gtype = geom.get("type")
        if gtype == "LineString":
            parts = [geom.get("coordinates") or []]
        elif gtype == "MultiLineString":
            parts = geom.get("coordinates") or []
        else:
            raise ValueError(f"OSM feature geometry must be LineString or MultiLineString, got {gtype}")
        for part, coords in enumerate(parts):
            if len(coords) < 2:
                raise ValueError("OSM line has fewer than 2 positions")
            arr = np.asarray(coords, dtype=np.float64)
            if arr.ndim != 2 or arr.shape[1] < 2 or not np.isfinite(arr[:, :2]).all():
                raise ValueError("OSM coordinates must be finite lon/lat pairs")
            xs, ys = transform_xy("EPSG:4326", ref["crs"], arr[:, 0].tolist(), arr[:, 1].tolist())
            props = dict(feature.get("properties") or {})
            props.setdefault("part", part)
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": arr[:, :2].tolist()},
                    "properties": props,
                    "node_ids": _synthetic_node_ids(arr[:, :2]),
                    "xy": [[float(x), float(y)] for x, y in zip(xs, ys)],
                }
            )
    return features


def _synthetic_node_ids(coords: np.ndarray) -> List[int]:
    """Stable ids for reloaded GeoJSON.

    Fresh extracts keep real OSM ids in memory. After a round trip the GeoJSON
    does not repeat node ids, so QA reconnects vertices that still share the
    exact published coordinate. It does not node planar crossings.
    """
    ids = []
    for lon, lat in coords:
        ids.append((int(round(lon * 1e7)) << 32) ^ (int(round(lat * 1e7)) & 0xFFFFFFFF))
    return ids
