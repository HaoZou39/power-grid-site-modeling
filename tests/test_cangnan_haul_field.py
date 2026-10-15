"""Prepared-scene regressions for cangnan road and haul-field behavior."""

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from modeling.haul_field import build_haul_field, query_exact, query_route
from modeling.logistics_cost import RoadNetwork


SCENE = Path(__file__).resolve().parents[1] / "scenes" / "cangnan"
REQUIRED = (
    SCENE / "dem_1m.npy",
    SCENE / "landuse_1m.npy",
    SCENE / "road_segments_local.npy",
    SCENE / "road_segments_local.json",
)
P2B_REFERENCE = Path(__file__).resolve().parent / "fixtures" / "cangnan_p2b_reference.csv"


@pytest.mark.skipif(not all(path.is_file() for path in REQUIRED), reason="prepared cangnan scene is absent")
def test_reported_origin_reaches_the_topology_repaired_real_haul_field() -> None:
    from pyproj import Transformer

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


@pytest.mark.skipif(
    not all(path.is_file() for path in REQUIRED) or not P2B_REFERENCE.is_file(),
    reason="prepared cangnan scene or P2b reference fixture is absent",
)
def test_all_40_reference_solutions_reconstruct_their_optimized_metrics() -> None:
    from experiments.constraint_mask import compose_constraint_masks, policy_from_form

    dem = np.load(SCENE / "dem_1m.npy")
    segments = np.load(SCENE / "road_segments_local.npy")
    hard_mask, _soft_mask = compose_constraint_masks(
        np.load(SCENE / "landuse_1m.npy"),
        [],
        policy_from_form({"field_policy": "blocked", "mountain_policy": "allowed"}),
    )
    origin = (452.68826107194656, 537.6665018220328)
    field = build_haul_field(dem, hard_mask == 0, segments, origin)
    with P2B_REFERENCE.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))

    assert len(rows) == 40
    for row in rows:
        site = (float(row["x"]), float(row["y"]))
        values, blocked = query_exact(field, np.asarray([site], dtype=np.float64))
        route = query_route(field, site)
        expected = np.asarray(
            [row["road_haul_m"], row["offroad_haul_m"], row["haul_rise_m"]],
            dtype=np.float64,
        )
        assert blocked.tolist() == [0.0]
        assert values[0] == pytest.approx(expected, abs=1e-6)
        assert route["road_haul_m"] == pytest.approx(expected[0], abs=1e-6)
        assert route["offroad_haul_m"] == pytest.approx(expected[1], abs=1e-6)
        assert route["haul_rise_m"] == pytest.approx(expected[2], abs=1e-6)
        assert route["points"][0] == pytest.approx(origin)
        assert np.linalg.norm(np.asarray(route["points"][-1]) - np.asarray(site)) <= 0.05

    by_id = {int(row["run_id"]): row for row in rows}
    assert float(by_id[8]["haul_rise_m"]) == pytest.approx(48.533843994140625)
    assert float(by_id[35]["offroad_haul_m"]) == pytest.approx(118.52396278648303)
