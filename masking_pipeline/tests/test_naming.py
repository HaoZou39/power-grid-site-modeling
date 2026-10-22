#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest

import numpy as np
import rasterio
from rasterio.transform import from_bounds, from_origin

from bundle import export_bundle, release_staged_bundle, stage_is_reusable
from naming import (
    NamingError,
    assert_site_identity,
    build_site_id,
    build_site_paths,
    bundle_filenames,
    canonical_parameters,
    resolve_site_directory,
)

CANGNAN = dict(
    site_name="cangnan",
    lat=27.501662,
    lon=120.194639,
    radius_km=0.9,
    zoom=18,
    target_height=1800,
    target_width=1800,
    road_buffer_m=500,
)
CANGNAN_ID = "lat27.501662_lon120.194639_r0.900km_z18_g1800x1800_rb500m"


def _write_tif(path, crs, transform, data, nodata=None):
    height, width = data.shape
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=1 if data.ndim == 2 else data.shape[2],
        dtype=data.dtype, crs=crs, transform=transform, nodata=nodata,
    ) as dst:
        if data.ndim == 2:
            dst.write(data, 1)
        else:
            for band in range(data.shape[2]):
                dst.write(data[:, :, band], band + 1)


class NamingTests(unittest.TestCase):
    def test_same_inputs_are_stable_and_independent_fields_change_the_id(self):
        self.assertEqual(build_site_id(**CANGNAN), CANGNAN_ID)
        self.assertEqual(build_site_id(**CANGNAN), build_site_id(**CANGNAN))
        self.assertNotEqual(build_site_id(**{**CANGNAN, "lat": 27.501663}), CANGNAN_ID)
        self.assertNotEqual(build_site_id(**{**CANGNAN, "radius_km": 1.0}), CANGNAN_ID)
        self.assertNotEqual(build_site_id(**{**CANGNAN, "zoom": 17}), CANGNAN_ID)
        self.assertNotEqual(build_site_id(**{**CANGNAN, "target_height": 900}), CANGNAN_ID)
        self.assertNotEqual(build_site_id(**{**CANGNAN, "road_buffer_m": 1000}), CANGNAN_ID)

    def test_site_name_and_extra_precision_are_rejected(self):
        self.assertEqual(canonical_parameters(**CANGNAN)["site_name"], "cangnan")
        self.assertEqual(build_site_id(**{**CANGNAN, "site_name": "苍南"}), CANGNAN_ID)
        self.assertEqual(canonical_parameters(**{**CANGNAN, "site_name": "苍南"})["site_name"], "苍南")
        with self.assertRaises(NamingError):
            build_site_id(**{**CANGNAN, "site_name": "cang nan"})
        with self.assertRaises(NamingError):
            build_site_id(**{**CANGNAN, "lat": 27.5016624})

    def test_existing_metadata_with_different_parameters_is_a_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            site_dir = os.path.join(tmp, CANGNAN_ID)
            os.makedirs(site_dir)
            with open(os.path.join(site_dir, "metadata.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "site_id": CANGNAN_ID,
                        "site_name": "cangnan",
                        "center": {"lat": 27.501661, "lon": 120.194639},
                        "parameters": {
                            "radius_km": 0.9,
                            "zoom": 18,
                            "target_height": 1800,
                            "target_width": 1800,
                            "road_buffer_m": 500,
                        },
                    },
                    handle,
                )
            with self.assertRaises(NamingError):
                assert_site_identity(site_dir, CANGNAN_ID, canonical_parameters(**CANGNAN))

    def test_filenames_share_the_site_id(self):
        paths = build_site_paths(CANGNAN_ID, site_dir=os.path.join("/tmp", CANGNAN_ID))
        names = bundle_filenames(CANGNAN_ID)
        for key, filename in names.items():
            self.assertTrue(filename.startswith(CANGNAN_ID + "_"))
            self.assertEqual(os.path.basename(paths[key]), filename)
        self.assertTrue(os.path.basename(paths["osm_preview"]).startswith(CANGNAN_ID + "_"))
        self.assertTrue(paths["metadata"].endswith("metadata.json"))

    def test_legacy_output_dir_is_exact_and_output_root_appends_site_id(self):
        legacy, mode = resolve_site_directory(CANGNAN_ID, output_dir="/tmp/exact-legacy")
        self.assertEqual(legacy, "/tmp/exact-legacy")
        self.assertEqual(mode, "legacy_output_dir")
        modern, modern_mode = resolve_site_directory(
            CANGNAN_ID, output_root="/tmp/outputs", default_root="/tmp/ignored"
        )
        self.assertEqual(modern, os.path.join("/tmp/outputs", CANGNAN_ID))
        self.assertEqual(modern_mode, "site_id_directory")
        with self.assertRaises(NamingError):
            resolve_site_directory(CANGNAN_ID, output_dir="/tmp/a", output_root="/tmp/b")

    def test_changed_source_file_signature_rejects_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            ready = os.path.join(tmp, "roads.geojson")
            with open(ready, "w", encoding="utf-8") as handle:
                handle.write("{}")
            manifest = {
                "osm": {
                    "status": "passed",
                    "params": {"pbf": {"size": 10, "mtime_ns": 1}},
                    "files": [ready],
                }
            }
            ok, reason = stage_is_reusable(
                manifest, "osm", {"pbf": {"size": 99, "mtime_ns": 2}}, [ready]
            )
            self.assertFalse(ok)
            self.assertIn("do not match", reason)

    def test_incomplete_staging_is_not_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = os.path.join(tmp, "staging")
            bundle = os.path.join(tmp, "bundle")
            os.makedirs(staging)
            with open(os.path.join(staging, "only_one.txt"), "w", encoding="utf-8") as handle:
                handle.write("x")
            with self.assertRaises(RuntimeError):
                release_staged_bundle(staging, bundle, ["a.tif", "b.csv", "c.tif", "d.geojson"])
            self.assertFalse(os.path.isdir(bundle))

    def test_publish_writes_four_files_and_metadata_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            site_id = "lat0.000000_lon0.000000_r0.001km_z18_g2x2_rb500m"
            paths = build_site_paths(site_id, site_dir=os.path.join(tmp, "scene"))
            os.makedirs(paths["cache_dir"], exist_ok=True)
            sat = os.path.join(tmp, "sat.tif")
            dem = os.path.join(tmp, "dem.tif")
            _write_tif(sat, "EPSG:3857", from_bounds(0, 0, 100, 100, 4, 4), np.zeros((4, 4), np.uint8))
            _write_tif(dem, "EPSG:4326", from_origin(-1, 1, 0.1, 0.1), np.full((20, 20), 12, np.int16), nodata=-32767)
            roads = os.path.join(tmp, "roads.geojson")
            with open(roads, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "type": "FeatureCollection",
                        "features": [{
                            "type": "Feature",
                            "properties": {"@id": "way/1", "highway": "unclassified"},
                            "geometry": {"type": "LineString", "coordinates": [[0.0001, 0.0001], [0.0002, 0.0002]]},
                        }],
                    },
                    handle,
                )
            landuse = np.array([[0, 1], [4, 5]], dtype=np.int32)
            summary = {
                "extraction_bbox_projected": [-10, -10, 110, 110],
                "target_bbox_projected": [0, 0, 100, 100],
                "connectivity": {
                    "component_count": 1,
                    "largest_component_projected_length_ratio": 1,
                    "isolated_target_component_count": 0,
                    "projected_length_m": 10,
                },
            }
            dem_summary = {"elevation_min": 12, "elevation_max": 12, "elevation_model": "unknown"}
            result = export_bundle(
                paths["site_dir"],
                sat,
                landuse,
                roads,
                dem,
                run_params={
                    "site_name": "site",
                    "lat": 0.0,
                    "lon": 0.0,
                    "radius_km": 0.001,
                    "zoom": 18,
                    "target_height": 2,
                    "target_width": 2,
                    "road_buffer_m": 500,
                    "center": {"lat": 0.0, "lon": 0.0},
                },
                osm_summary=summary,
                dem_summary=dem_summary,
                model="mfaytin/mask2former-satellite",
                site_paths=paths,
            )
            self.assertEqual(result["overall_status"], "passed")
            published = sorted(os.listdir(paths["bundle_dir"]))
            self.assertEqual(published, sorted(bundle_filenames(site_id).values()))
            with open(paths["metadata"], encoding="utf-8") as handle:
                metadata = json.load(handle)
            self.assertEqual(metadata["schema_version"], "1.0")
            self.assertEqual(metadata["site_id"], site_id)
            self.assertTrue(metadata["files"]["landuse_path"].startswith("bundle/"))
            self.assertTrue(metadata["files"]["landuse_path"].endswith(f"{site_id}_landuse.csv"))
            loaded = np.loadtxt(os.path.join(paths["bundle_dir"], bundle_filenames(site_id)["landuse"]), delimiter=",")
            np.testing.assert_array_equal(loaded, landuse)
            self.assertFalse(os.path.exists(os.path.join(paths["bundle_dir"], "downstream_config.json")))
            self.assertTrue(os.path.isfile(paths["downstream_config"]))


if __name__ == "__main__":
    unittest.main()
