#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行政边界只读图层：场景经纬度外框筛选与缺失报错。"""
import json

import pytest

from data_tools.scene_coordinates import projection
from experiments import admin_boundaries


def _frame(lon: float, lat: float, side_m: float = 1800.0) -> dict:
    east, north = projection(4326, 3857).transform(lon, lat)
    return {
        "crs": "EPSG:3857",
        "transform": [1.0, 0.0, east, 0.0, -1.0, north],
        "width": side_m,
        "height": side_m,
    }


def _square(lon: float, lat: float, half: float = 0.005) -> dict:
    ring = [
        [lon - half, lat - half],
        [lon + half, lat - half],
        [lon + half, lat + half],
        [lon - half, lat + half],
        [lon - half, lat - half],
    ]
    return {
        "type": "Feature",
        "properties": {"name": "测试镇", "admin_level": 8, "osm_relation_id": 1},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def _point(lon: float, lat: float) -> dict:
    return {
        "type": "Feature",
        "properties": {"name": "标注点", "admin_level": 8, "osm_relation_id": 1},
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


@pytest.fixture()
def regional(tmp_path, monkeypatch):
    collection = {
        "type": "FeatureCollection",
        "metadata": {"source_pbf": "test.osm.pbf"},
        "features": [
            _square(120.405, 27.495),
            _square(122.0, 30.0),
            _point(120.405, 27.495),
            _point(120.43, 27.52),
            _point(122.0, 30.0),
        ],
    }
    path = tmp_path / "admin_boundaries.geojson"
    path.write_text(json.dumps(collection), encoding="utf-8")
    monkeypatch.setattr(admin_boundaries, "REGIONAL_GEOJSON", path)
    admin_boundaries._cache.clear()
    yield path
    admin_boundaries._cache.clear()


def test_filters_by_scene_bbox_with_buffer(regional):
    result = admin_boundaries.scene_admin_boundaries(_frame(120.4, 27.5))
    assert result["type"] == "FeatureCollection"
    assert result["source"] == "test.osm.pbf"
    kinds = sorted(feature["geometry"]["type"] for feature in result["features"])
    assert kinds == ["Point", "Point", "Polygon"]


def test_outside_buffer_is_excluded(regional):
    result = admin_boundaries.scene_admin_boundaries(_frame(121.0, 29.0))
    assert result["features"] == []


def test_missing_regional_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(admin_boundaries, "REGIONAL_GEOJSON", tmp_path / "missing.geojson")
    admin_boundaries._cache.clear()
    try:
        with pytest.raises(FileNotFoundError):
            admin_boundaries.scene_admin_boundaries(_frame(120.4, 27.5))
    finally:
        admin_boundaries._cache.clear()
