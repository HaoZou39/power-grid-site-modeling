"""Actual source files exercise all four products in a UTM grid."""
import json
from dataclasses import replace

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from config.project_config import load_default_config
from data_tools.metric_grid import metric_grid, frame_id
from experiments.problem_context import write_scene_products


def test_real_source_products_share_one_metric_frame(tmp_path):
    frame = metric_grid(27.5, 120.2, 64)
    mx, my = Transformer.from_crs(4326, 3857, always_xy=True).transform(120.2, 27.5)
    for name in ("dem.tif", "reference.tif"):
        with rasterio.open(tmp_path / name, "w", driver="GTiff", count=1, dtype="float32",
                           height=100, width=100, crs="EPSG:3857", transform=from_origin(mx-50, my+50, 1, 1)) as dst:
            dst.write(np.full((100, 100), 100, np.float32), 1)
    np.savetxt(tmp_path / "landuse.csv", np.zeros((100, 100)), delimiter=",", fmt="%d")
    inverse = Transformer.from_crs(frame["crs"], 4326, always_xy=True)
    points = [inverse.transform(frame["transform"][2]+x, frame["transform"][5]-10) for x in (0, 64)]
    (tmp_path / "roads.geojson").write_text(json.dumps({"type":"FeatureCollection", "features":[{
        "type":"Feature", "properties":{"highway":"residential"},
        "geometry":{"type":"LineString", "coordinates":points}}]}))
    base = load_default_config()
    config = replace(base, data=replace(base.data, dem_path=tmp_path/"dem.tif",
        reference_geotiff_path=tmp_path/"reference.tif", landuse_path=tmp_path/"landuse.csv",
        osm_roads_path=tmp_path/"roads.geojson", road_voronoi_backend="cpu"))
    arrays, metadata = write_scene_products(config, tmp_path/"products", reference_frame=frame)
    for key in ("dem", "landuse", "obstacle_mask", "road_voronoi"):
        assert arrays[key].shape == (64, 64)
    np.testing.assert_allclose(arrays["dem"], 100, atol=1e-5)
    np.testing.assert_allclose(arrays["road_segments"][:, [1,3]], 10, atol=.01)
    assert metadata["dem"]["reference_crs"] == frame["crs"]
    assert metadata["dem"]["target_transform"] == frame["transform"]
    assert metadata["frame_id"] == frame_id(frame)
    assert metadata["scene_revision"]


def test_official_and_imported_polygons_burn_in_the_target_crs(tmp_path, monkeypatch):
    import shapefile
    from pyproj import CRS
    from experiments import official_water
    from experiments.protected_farmland import _read_polygons, _clip_to_scene, _burn

    frame = metric_grid(27.5, 120.2, 64)
    x, y = frame["transform"][2], frame["transform"][5]
    inverse = Transformer.from_crs(frame["crs"], 4326, always_xy=True)
    ring = [inverse.transform(x+dx, y-dy) for dx,dy in ((10,10),(10,30),(30,30),(30,10),(10,10))]
    source = tmp_path / "water_polygons"
    with shapefile.Writer(str(source), shapeType=shapefile.POLYGON) as writer:
        writer.field("fclass", "C")
        writer.poly([ring])
        writer.record("water")
    source.with_suffix(".prj").write_text(CRS.from_epsg(4326).to_wkt())
    source.with_suffix(".cpg").write_text("UTF-8")
    monkeypatch.setattr(official_water, "water_polygon_dir", lambda: tmp_path)
    official, metadata = official_water.rasterize_official_water(frame, (64,64))
    polygons, count, empty = _read_polygons(source.with_suffix(".shp"), "utf-8", CRS.from_epsg(4326), frame["crs"])
    imported = _burn(_clip_to_scene(polygons, frame), frame, (64,64))
    assert count == 1 and empty == 0
    assert metadata["scene_crs"] == frame["crs"]
    assert official[20,20] and not official[40,40]
    np.testing.assert_array_equal(official, imported)
