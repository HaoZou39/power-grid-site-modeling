"""Run the validation entry points on actual small GeoTIFF/CSV/GeoJSON inputs."""

import json
from dataclasses import replace

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from config.project_config import load_default_config, save_config


def test_validation_scripts_consume_current_road_product_contract(tmp_path, cuda_device):
    from experiments.compare_road_voronoi import _check_road_product
    from experiments.diagnose_road_topology import topology_report
    from experiments.validate_modeling import main

    size = 64
    for name in ("dem.tif", "reference.tif"):
        with rasterio.open(tmp_path / name, "w", driver="GTiff", count=1, dtype="float32",
                           height=size, width=size, crs="EPSG:3857", transform=from_origin(100, 200, 1, 1)) as dataset:
            dataset.write(np.zeros((size, size), np.float32), 1)
    np.savetxt(tmp_path / "landuse.csv", np.zeros((size, size)), delimiter=",", fmt="%d")
    inverse = Transformer.from_crs(3857, 4326, always_xy=True)
    points = [inverse.transform(100.5, 198.5), inverse.transform(163.5, 198.5)]
    (tmp_path / "roads.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"highway": "residential"},
         "geometry": {"type": "LineString", "coordinates": points}},
    ]}))
    base = load_default_config()
    config = replace(base, data=replace(base.data, dem_path=tmp_path / "dem.tif", reference_geotiff_path=tmp_path / "reference.tif",
        landuse_path=tmp_path / "landuse.csv", osm_roads_path=tmp_path / "roads.geojson", road_voronoi_backend="cpu"),
        modeling=replace(base.modeling, rect_w_m=4, rect_h_m=3))
    path = tmp_path / "config.json"
    save_config(config, path)
    output = tmp_path / "validation"
    main(path, output)
    summary = json.loads((output / "validation_summary.json").read_text())
    assert summary["data"]["road"]["n_segments"] == 1
    assert len(summary["raw_pose_grad"]) == 3
    roads = np.load(output / "road_segments_local.npy")
    comparison = tmp_path / "comparison"
    comparison.mkdir()
    _check_road_product(path, roads, size, comparison)
    assert json.loads((comparison / "product_validation.json").read_text())["auto"]["mismatched_cells"] == 0
    assert topology_report(path)["repaired"]["segment_count"] == 1
