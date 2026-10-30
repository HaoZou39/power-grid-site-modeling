#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行政边界只读显示图层：按场景经纬度外框筛选区域 GeoJSON。

口径见 markdown/DATA_MODULE_SUMMARY.md「行政边界显示数据」。只用于地图显示，
不进建模、优化或实验产物。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

REGIONAL_GEOJSON = (
    Path(__file__).resolve().parents[1]
    / "masking_pipeline"
    / "data"
    / "regional"
    / "admin_boundaries.geojson"
)
# 约 3 km，让场景外邻近的乡镇边界和标注点也进入响应
BBOX_BUFFER_DEG = 0.03

_cache: dict[str, Any] = {}


def _feature_bbox(feature: dict[str, Any]) -> tuple[float, float, float, float]:
    lons: list[float] = []
    lats: list[float] = []

    def walk(coords: list) -> None:
        if isinstance(coords[0], (int, float)):
            lons.append(coords[0])
            lats.append(coords[1])
            return
        for item in coords:
            walk(item)

    walk(feature["geometry"]["coordinates"])
    return min(lons), min(lats), max(lons), max(lats)


def _load() -> tuple[dict[str, Any], list[tuple[float, float, float, float]]]:
    mtime = os.path.getmtime(REGIONAL_GEOJSON)
    if _cache.get("mtime") != mtime:
        with open(REGIONAL_GEOJSON, encoding="utf-8") as handle:
            data = json.load(handle)
        bboxes = [_feature_bbox(feature) for feature in data["features"]]
        _cache.update(mtime=mtime, data=data, bboxes=bboxes)
    return _cache["data"], _cache["bboxes"]


def scene_admin_boundaries(frame: dict[str, Any]) -> dict[str, Any]:
    """按 scene_frame_info 返回的网格 frame 筛选行政边界要素。"""
    from data_tools.scene_coordinates import local_to_lonlat

    width, height = float(frame["width"]), float(frame["height"])
    corners = [
        local_to_lonlat(frame, x, y)
        for x, y in ((0.0, 0.0), (width, 0.0), (width, height), (0.0, height))
    ]
    lons = [c[0] for c in corners]
    lats = [c[1] for c in corners]
    west = min(lons) - BBOX_BUFFER_DEG
    east = max(lons) + BBOX_BUFFER_DEG
    south = min(lats) - BBOX_BUFFER_DEG
    north = max(lats) + BBOX_BUFFER_DEG
    data, bboxes = _load()
    features = [
        feature
        for feature, (fw, fs, fe, fn) in zip(data["features"], bboxes)
        if fw <= east and fe >= west and fs <= north and fn >= south
    ]
    return {
        "type": "FeatureCollection",
        "source": data["metadata"]["source_pbf"],
        "features": features,
    }
