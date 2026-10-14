"""Prepared-scene regression for the reported cangnan origin."""

import json
from pathlib import Path

import numpy as np
import pytest
from pyproj import Transformer

from modeling.haul_field import build_haul_field, query_exact
from modeling.logistics_cost import RoadNetwork


SCENE = Path(__file__).resolve().parents[1] / "scenes" / "cangnan"
REQUIRED = (
    SCENE / "dem_1m.npy",
    SCENE / "landuse_1m.npy",
    SCENE / "road_segments_local.npy",
    SCENE / "road_segments_local.json",
)


@pytest.mark.skipif(not all(path.is_file() for path in REQUIRED), reason="prepared cangnan scene is absent")
def test_reported_origin_reaches_the_topology_repaired_real_haul_field() -> None:
    metadata = json.loads((SCENE / "road_segments_local.json").read_text(encoding="utf-8"))
    bounds = metadata["reference_bounds"]
    map_x, map_y = Transformer.from_crs(
        "EPSG:4326",
        metadata["reference_crs"],
        always_xy=True,
    ).transform(120.193987, 27.500968)
    origin = (
        (map_x - bounds["left"]) * metadata["x_scale_grid_per_crs_unit"],
        (bounds["top"] - map_y) * metadata["y_scale_grid_per_crs_unit"],
    )
    assert origin == pytest.approx((827.541, 987.102), abs=0.002)

    dem = np.load(SCENE / "dem_1m.npy")
    from experiments.constraint_mask import compose_constraint_masks, policy_from_form

    hard_mask, _soft_mask = compose_constraint_masks(
        np.load(SCENE / "landuse_1m.npy"),
        [],
        policy_from_form({"field_policy": "allowed", "mountain_policy": "allowed"}),
    )
    buildable = hard_mask == 0
    segments = np.load(SCENE / "road_segments_local.npy")
    network = RoadNetwork(segments)
    projection = network.project(origin)
    field = build_haul_field(dem, buildable, segments, origin)

    assert projection.gap_m >= 0.0
    assert network.component_count == metadata["simplified_component_count"]
    assert metadata["raw_component_count"] == metadata["simplified_component_count"]
    assert field.gate_count == field.reachable_gate_count + field.unreachable_gate_count
    assert field.reachable_gate_count == field.gate_count
    assert field.unreachable_gate_count == 0

    row, col = np.argwhere(field.reachable & ~field.road_cells)[0]
    values, blocked = query_exact(field, np.array([[col + 0.5, row + 0.5]], dtype=np.float64))
    assert blocked[0] == 0.0
    assert np.isfinite(values[0]).all()
    assert np.all(values[0] >= 0.0)

    voronoi = np.load(SCENE / "road_voronoi_1m.npy")
    assert int(voronoi.min()) >= 0
    assert int(voronoi.max()) < len(segments)
