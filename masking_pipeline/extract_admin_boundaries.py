#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从区域 OSM PBF 提取行政边界显示图层（区县级 admin_level=6、乡镇/街道级 admin_level=8）。

产物与口径见 markdown/DATA_MODULE_SUMMARY.md「行政边界显示数据」。
只用于地图只读显示，不进建模、优化或实验产物。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Sequence, Tuple

from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.ops import polylabel, transform

from geo_utils import transformer
from osm_pbf import (
    BoundaryRelation,
    collect_boundary_relations,
    collect_nodes,
    collect_way_refs,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OSM_PBF = os.path.join(SCRIPT_DIR, "data", "regional", "zhejiang-261020.osm.pbf")
DEFAULT_OUTPUT = os.path.join(SCRIPT_DIR, "data", "regional", "admin_boundaries.geojson")
ADMIN_LEVELS = frozenset({"6", "8"})
# EPSG:3857 米制下的显示简化容差；27°N 处对应地面约 17 m
SIMPLIFY_TOLERANCE_M = 20.0

_to_3857 = transformer("EPSG:4326", "EPSG:3857").transform
_to_4326 = transformer("EPSG:3857", "EPSG:4326").transform


def assemble_rings(
    way_ids: Sequence[int],
    way_refs: Dict[int, List[int]],
) -> Tuple[List[List[int]], int]:
    """把无序的 member ways 链成闭合环，返回 (闭合环列表, 未闭合链数)。

    每条 way 的 refs 可正接也可反接；组不成闭合环的链整条放弃。
    """
    segs = [list(way_refs[w]) for w in way_ids if w in way_refs]
    used = [False] * len(segs)
    rings: List[List[int]] = []
    open_chains = 0
    for start in range(len(segs)):
        if used[start]:
            continue
        used[start] = True
        ring = segs[start][:]
        while ring[-1] != ring[0]:
            extended = False
            for i, seg in enumerate(segs):
                if used[i]:
                    continue
                if seg[0] == ring[-1]:
                    ring.extend(seg[1:])
                elif seg[-1] == ring[-1]:
                    ring.extend(reversed(seg[:-1]))
                else:
                    continue
                used[i] = True
                extended = True
                break
            if not extended:
                break
        if ring[-1] == ring[0]:
            rings.append(ring)
        else:
            open_chains += 1
    return rings, open_chains


def relation_geometry(
    relation: BoundaryRelation,
    way_refs: Dict[int, List[int]],
    nodes: Dict[int, Tuple[float, float]],
) -> Tuple[MultiPolygon | None, int]:
    """把 relation 的 outer/inner 环组装成 MultiPolygon（WGS84）。返回 (几何, 未闭合链数)。"""
    _, _, outer_ids, inner_ids = relation
    outer_rings, open_outer = assemble_rings(outer_ids, way_refs)
    inner_rings, open_inner = assemble_rings(inner_ids, way_refs)

    def coords(ring: Sequence[int]) -> List[Tuple[float, float]]:
        return [nodes[n] for n in ring if n in nodes]

    outers = [Polygon(coords(r)) for r in outer_rings if len(coords(r)) >= 4]
    inners = [Polygon(coords(r)) for r in inner_rings if len(coords(r)) >= 4]
    polys: List[Polygon] = []
    for outer in outers:
        if not outer.is_valid:
            outer = outer.buffer(0)
            if outer.is_empty:
                continue
            if isinstance(outer, MultiPolygon):
                polys.extend(outer.geoms)
                continue
        holes = [list(p.exterior.coords) for p in inners if outer.contains(p.representative_point())]
        polys.append(Polygon(list(outer.exterior.coords), holes))
    if not polys:
        return None, open_outer + open_inner
    return MultiPolygon(polys), open_outer + open_inner


def build_features(
    relations: Sequence[BoundaryRelation],
    way_refs: Dict[int, List[int]],
    nodes: Dict[int, Tuple[float, float]],
    tolerance_m: float,
) -> Tuple[List[dict], dict]:
    """生成边界与标注点要素（WGS84），几何在 EPSG:3857 下简化。"""
    features: List[dict] = []
    stats = {"relations": len(relations), "built": 0, "open_chains": 0, "empty": 0}
    for relation in sorted(relations, key=lambda r: (r[1].get("admin_level", ""), r[1].get("name", ""), r[0])):
        rel_id, tags, _, _ = relation
        geom, open_chains = relation_geometry(relation, way_refs, nodes)
        stats["open_chains"] += open_chains
        if geom is None or geom.is_empty:
            stats["empty"] += 1
            continue
        simplified = transform(_to_4326, transform(_to_3857, geom).simplify(tolerance_m, preserve_topology=True))
        if simplified.is_empty:
            stats["empty"] += 1
            continue
        label_point = transform(_to_4326, polylabel(transform(_to_3857, simplified), tolerance=tolerance_m))
        props = {
            "name": tags.get("name", ""),
            "admin_level": int(tags["admin_level"]),
            "osm_relation_id": rel_id,
        }
        features.append({"type": "Feature", "properties": props, "geometry": mapping(simplified)})
        features.append({"type": "Feature", "properties": props, "geometry": mapping(label_point)})
        stats["built"] += 1
    return features, stats


def extract_admin_boundaries(
    osm_pbf: str,
    output: str,
    tolerance_m: float = SIMPLIFY_TOLERANCE_M,
    progress=print,
) -> dict:
    _, relations = collect_boundary_relations(osm_pbf, ADMIN_LEVELS, progress)
    way_ids = {w for _, _, outer, inner in relations for w in outer + inner}
    way_refs = collect_way_refs(osm_pbf, way_ids, progress)
    node_ids = {n for refs in way_refs.values() for n in refs}
    nodes = collect_nodes(osm_pbf, node_ids, progress)
    features, stats = build_features(relations, way_refs, nodes, tolerance_m)

    with open(osm_pbf, "rb") as handle:
        pbf_sha256 = hashlib.sha256(handle.read()).hexdigest()
    collection = {
        "type": "FeatureCollection",
        "metadata": {
            "source_pbf": os.path.basename(osm_pbf),
            "source_pbf_sha256": pbf_sha256,
            "admin_levels": sorted(int(v) for v in ADMIN_LEVELS),
            "simplify_tolerance_m_epsg3857": tolerance_m,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            **stats,
        },
        "features": features,
    }
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(collection, handle, ensure_ascii=False, separators=(",", ":"))
    return collection["metadata"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osm-pbf", default=DEFAULT_OSM_PBF)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--tolerance-m", type=float, default=SIMPLIFY_TOLERANCE_M)
    args = parser.parse_args()
    metadata = extract_admin_boundaries(args.osm_pbf, args.output, args.tolerance_m)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    print(f"written: {args.output}")


if __name__ == "__main__":
    main()
