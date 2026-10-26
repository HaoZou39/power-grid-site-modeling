from dataclasses import replace
import math

import numpy as np
import pytest
import torch

from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.geometry import mask_intersection_length
from modeling.routing.types import Route, RoutingConstraints
from test_routing_context import make_problem


def test_hand_calculated_spatial_span_and_crossing():
    rows = np.indices((32, 32))[0] + 0.5
    landuse = np.zeros((32, 32), dtype=np.int32)
    landuse[10:12, :] = 2
    problem = make_problem(dem=3 * rows, landuse=landuse, start=(10, 10.4), end=(13, 14.4),
        constraints=RoutingConstraints(5, .4, 90, 0, 0))
    result = RouteEvaluator(problem).evaluate(Route(np.empty((0, 2))))
    assert result.is_feasible
    assert result.spans[0]["horizontal_m"] == pytest.approx(5)
    assert result.objectives[1] == pytest.approx(13)
    assert result.objectives[3] == pytest.approx(5.2)


def test_horizontal_turns_and_local_limit_ignore_dem_rise():
    problem = make_problem(start=(5, 5), end=(15, 15), constraints=RoutingConstraints(20, .4, 89, 0, 0))
    route = Route(np.array([[15, 5]]))
    result = RouteEvaluator(problem).evaluate(route)
    assert result.objectives[2] == pytest.approx(math.pi / 2)
    assert not result.is_feasible
    assert result.violations["turn_excess_rad"] > 0


def test_circle_touches_closed_cell_but_center_is_outside():
    landuse = np.zeros((32, 32), dtype=np.int32)
    landuse[8, 10] = 2
    evaluator = RouteEvaluator(make_problem(landuse=landuse))
    assert not evaluator.evaluate(Route(np.array([[9.6, 8.5]]))).is_feasible
    assert evaluator.evaluate(Route(np.array([[9.59, 8.5]]))).is_feasible


def test_farmland_and_two_region_types_differ():
    farmland = np.zeros((32, 32), dtype=bool)
    farmland[:, 15] = True
    empty = Route(np.empty((0, 2)))
    polygon = [[[14, 5], [17, 5], [17, 11], [14, 11]]]
    problem = make_problem(farmland=farmland, no_tower_zones=polygon)
    evaluation = RouteEvaluator(problem).evaluate(empty)
    assert evaluation.is_feasible and evaluation.objectives[3] == 0
    assert not RouteEvaluator(problem).evaluate(Route(np.array([[15.5, 8.5]]))).is_feasible
    forbidden = make_problem(no_cross_zones=polygon)
    assert not RouteEvaluator(forbidden).evaluate(empty).is_feasible


def test_tower_spacing_tangency_and_endpoint_exemption():
    problem = make_problem(constraints=RoutingConstraints(30, 1, 180, 0, 0))
    evaluator = RouteEvaluator(problem)
    assert evaluator.evaluate(Route(np.array([[3, 8], [5, 8]]))).is_feasible
    assert not evaluator.evaluate(Route(np.array([[3, 8], [4.99, 8]]))).is_feasible
    assert evaluator.evaluate(Route(np.array([[2.1, 8]]))).is_feasible


def test_grid_edge_union_length_and_thin_features():
    mask = np.zeros((10, 10), dtype=bool)
    mask[4, 2:8] = True
    mask[5, 2:8] = True
    assert mask_intersection_length(np.array([1., 5]), np.array([9., 5]), mask) == 6
    assert mask_intersection_length(np.array([1., 4.5]), np.array([9., 4.5]), mask) == 6


def test_grid_traversal_matches_independent_polygon_union():
    from shapely.geometry import LineString, box
    from shapely.ops import unary_union
    rng = np.random.default_rng(312)
    mask = rng.random((10, 10)) < .3
    region = unary_union([box(col, row, col + 1, row + 1) for row, col in zip(*np.nonzero(mask))])
    for _ in range(20):
        points = rng.uniform(0, 10, (2, 2))
        expected = LineString(points).intersection(region).length
        assert mask_intersection_length(*points, mask) == pytest.approx(expected, abs=1e-10)


def test_padded_batch_ignores_padding_and_slope_only_reports():
    dem = np.tile(np.arange(32) + 0.5, (32, 1))
    evaluator = RouteEvaluator(make_problem(dem=dem))
    towers = torch.tensor([[[float("nan"), float("nan")]], [[16., 8.]]])
    objectives, violation = evaluator.padded_batch(towers, torch.tensor([0, 1]))
    assert objectives.shape == (2, 4) and torch.isfinite(objectives).all()
    assert violation.tolist() == [0, 0]
    result = evaluator.evaluate(Route(np.array([[16., 8.]])), report=True)
    assert result.tower_slopes_deg == pytest.approx([45])
    np.testing.assert_allclose(result.objectives, objectives[1].numpy())


def test_invalid_geometry_dem_and_outside_cannot_be_feasible():
    evaluator = RouteEvaluator(make_problem())
    assert not evaluator.evaluate(Route(np.array([[2., 8.]]))).is_feasible
    assert not evaluator.evaluate(Route(np.array([[-1., 8.]]))).is_feasible
    dem = np.zeros((32, 32)); dem[7:10, 1:4] = np.nan
    with pytest.raises(ValueError, match="DEM"):
        RouteEvaluator(make_problem(dem=dem))
