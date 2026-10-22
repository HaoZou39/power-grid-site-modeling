#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

import numpy as np
import rasterio
from rasterio.transform import from_origin

from bundle import stage_is_reusable, write_landuse_csv
from dem import DemCoverageError, extract_dem
from download import enforce_tile_coverage, lonlat_to_webmercator
from geo_utils import bounds_contain, buffer_bounds, transform_xy
from osm import clip_way_parts, connectivity_report, extract_osm_roads


def _feature(node_ids, lonlat, xy, props):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": lonlat},
        "properties": props,
        "node_ids": node_ids,
        "xy": xy,
    }


def _write_tif(path, crs, transform, data, nodata=None):
    height, width = data.shape
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype=data.dtype, crs=crs, transform=transform, nodata=nodata,
    ) as dst:
        dst.write(data, 1)


class SiteBundleTests(unittest.TestCase):
    def test_web_mercator_matches_pyproj(self):
        lon, lat = 120.194639, 27.501662
        xs, ys = transform_xy("EPSG:4326", "EPSG:3857", [lon], [lat])
        x, y = lonlat_to_webmercator(lon, lat)
        self.assertAlmostEqual(xs[0], x, delta=0.05)
        self.assertAlmostEqual(ys[0], y, delta=0.05)

    def test_buffer_contains_target(self):
        target = (0.0, 0.0, 10.0, 10.0)
        outer = buffer_bounds(target, 5)
        self.assertTrue(bounds_contain(outer, target))
        self.assertFalse(bounds_contain(target, outer))
        self.assertEqual(outer, (-5.0, -5.0, 15.0, 15.0))

    def test_landuse_csv_roundtrip(self):
        mask = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int32)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "landuse.csv")
            write_landuse_csv(mask, path)
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            self.assertFalse(text.lower().startswith("class"))
            loaded = np.loadtxt(path, delimiter=",")
            np.testing.assert_array_equal(loaded, mask)
            with self.assertRaises(ValueError):
                write_landuse_csv(np.array([[0, 6]]), os.path.join(tmp, "bad.csv"))

    def test_shared_node_connects_and_bridge_crossing_does_not(self):
        target = (0.0, 0.0, 2.0, 2.0)
        shared = connectivity_report(
            [
                _feature([1, 2], [[0.2, 0.2], [0.4, 0.2]], [[0, 0], [10, 0]], {"highway": "residential"}),
                _feature([2, 3], [[0.4, 0.2], [0.4, 0.5]], [[10, 0], [10, 10]], {"highway": "service"}),
            ],
            target,
        )
        self.assertEqual(shared["component_count"], 1)
        crossing = connectivity_report(
            [
                _feature([10, 11], [[0.2, 0.2], [0.8, 0.8]], [[0, 0], [10, 10]], {"highway": "primary", "bridge": "yes", "layer": "1"}),
                _feature([12, 13], [[0.2, 0.8], [0.8, 0.2]], [[0, 10], [10, 0]], {"highway": "primary", "layer": "0"}),
            ],
            target,
        )
        self.assertEqual(crossing["component_count"], 2)
        self.assertFalse(crossing["planar_crossings_connected"])
        self.assertGreaterEqual(crossing["unconnected_grade_separated_crossings"], 1)

    def test_clip_keeps_one_nearby_node_and_drops_a_far_node(self):
        parts = clip_way_parts(
            [0, 1, 2, 3],
            [(-1.0, 0.5), (0.5, 0.5), (0.6, 0.5), (1.2, 0.5)],
            [(-5000.0, 500.0), (500.0, 500.0), (600.0, 500.0), (1200.0, 500.0)],
            (0.0, 0.0, 1.0, 1.0),
            (0.0, 0.0, 1000.0, 1000.0),
            1500,
        )
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0][0], [1, 2, 3])

    def test_missing_sources_raise(self):
        with self.assertRaises(FileNotFoundError):
            extract_osm_roads("missing.pbf", "missing.tif")
        with self.assertRaises(FileNotFoundError):
            extract_dem("missing.tif", "missing-ref.tif", "out.tif")

    def test_incomplete_tiles_are_rejected(self):
        with self.assertRaises(RuntimeError):
            enforce_tile_coverage(4, 3, [{"z": 18, "x": 1, "y": 2, "error": "404"}], False)
        enforce_tile_coverage(2, 2, [], False)

    def test_resume_rejects_parameter_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            ready = os.path.join(tmp, "satellite.tif")
            with open(ready, "w", encoding="utf-8") as handle:
                handle.write("x")
            manifest = {
                "download": {
                    "status": "passed",
                    "params": {"lat": 27.5, "lon": 120.2},
                    "files": [ready],
                }
            }
            ok, reason = stage_is_reusable(manifest, "download", {"lat": 28.0, "lon": 120.2}, [ready])
            self.assertFalse(ok)
            self.assertIn("do not match", reason)
            ok, reason = stage_is_reusable(manifest, "download", {"lon": 120.2, "lat": 27.5}, [ready])
            self.assertTrue(ok, reason)

    def test_dem_crop_preserves_elevation_and_rejects_nodata_hole(self):
        with tempfile.TemporaryDirectory() as tmp:
            dem_path = os.path.join(tmp, "dem.tif")
            ref_path = os.path.join(tmp, "ref.tif")
            out_path = os.path.join(tmp, "crop.tif")
            dem = np.full((20, 20), 42, dtype=np.int16)
            _write_tif(dem_path, "EPSG:4326", from_origin(120.0, 27.6, 0.01, 0.01), dem, nodata=-32767)
            xs, ys = transform_xy("EPSG:4326", "EPSG:3857", [120.05, 120.10], [27.50, 27.55])
            left, right = min(xs), max(xs)
            bottom, top = min(ys), max(ys)
            width, height = 10, 10
            transform = from_origin(left, top, (right - left) / width, (top - bottom) / height)
            _write_tif(ref_path, "EPSG:3857", transform, np.zeros((height, width), dtype=np.uint8))
            summary = extract_dem(dem_path, ref_path, out_path, pad_pixels=1)
            with rasterio.open(out_path) as src:
                values = src.read(1)
            self.assertEqual(int(values.min()), 42)
            self.assertEqual(int(values.max()), 42)
            self.assertFalse(summary["normalized"])
            dem[8, 7] = -32767
            _write_tif(dem_path, "EPSG:4326", from_origin(120.0, 27.6, 0.01, 0.01), dem, nodata=-32767)
            with self.assertRaises(DemCoverageError):
                extract_dem(dem_path, ref_path, os.path.join(tmp, "bad.tif"), pad_pixels=1)


if __name__ == "__main__":
    unittest.main()
