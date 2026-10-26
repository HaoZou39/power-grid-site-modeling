from dataclasses import replace

import numpy as np
import pytest

from modeling.routing.context import build_routing_problem
from modeling.routing.types import RoutingConstraints, RoutingFrame


def make_problem(*, landuse=None, dem=None, farmland=None, segments=None, kinds=None, constraints=None,
                 start=(2, 8), end=(28, 8), no_tower_zones=(), no_cross_zones=()):
    landuse = np.zeros((32, 32), dtype=np.int32) if landuse is None else landuse
    return build_routing_problem(
        np.zeros(landuse.shape) if dem is None else dem, landuse,
        np.empty((0, 4)) if segments is None else np.asarray(segments, dtype=float),
        np.empty(0, dtype=np.int8) if kinds is None else np.asarray(kinds, dtype=np.int8),
        farmland, start, end, RoutingFrame("EPSG:32651", (1, 0, 221000, 0, -1, 3046000),
            landuse.shape[1], landuse.shape[0]), constraints or RoutingConstraints(30, 0.4, 90, 0, 0),
        no_tower_zones=no_tower_zones, no_cross_zones=no_cross_zones,
    )


def test_land_classes_and_farmland_have_different_tower_and_crossing_rules():
    landuse = np.tile(np.arange(6, dtype=np.int32), (6, 1))
    farmland = np.zeros_like(landuse, dtype=bool)
    farmland[2, 1] = True
    problem = make_problem(landuse=landuse, farmland=farmland, start=(0, 0), end=(5, 5))
    assert problem.tower_blocked[0].tolist() == [False, False, True, True, False, True]
    assert problem.tower_blocked[2, 1]
    assert not problem.crossing_mask[2, 1]
    np.testing.assert_array_equal(landuse[0], np.arange(6))
    with pytest.raises(ValueError):
        problem.dem[0, 0] = 1


def test_surface_road_union_and_tunnel_exclusion():
    problem = make_problem(segments=[[8, 1, 8, 30], [16, 1, 16, 30], [24, 1, 24, 30]], kinds=[0, 2, 3])
    assert problem.road_control[8, 8] and problem.road_control[8, 16]
    assert not problem.road_control[8, 24]
    wider = make_problem(segments=[[8, 1, 8, 30]], kinds=[0],
        constraints=replace(problem.constraints, road_setback_m=2))
    assert wider.road_control[8, 6] and wider.crossing_mask[8, 6] and wider.tower_blocked[8, 6]


def test_missing_road_kind_and_invalid_region_are_errors():
    with pytest.raises(ValueError, match="road kinds"):
        make_problem(segments=[[1, 1, 2, 2]])
    with pytest.raises(ValueError, match="polygon"):
        make_problem(no_cross_zones=[[[1, 1], [4, 4], [1, 4], [4, 1]]])
