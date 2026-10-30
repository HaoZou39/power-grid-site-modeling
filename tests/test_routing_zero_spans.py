"""A duplicate tower remains invalid and must not invent a pi-radian turn."""

import numpy as np
import pytest

from modeling.routing.compiled_evaluator import CompiledRouteEvaluator
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.types import Route
from test_routing_context import make_problem


@pytest.mark.parametrize("direction", [[1., 1.], [1., -1.], [-1., 1.], [-1., -1.]])
def test_compiled_duplicate_tower_matches_reference_in_all_directions(direction):
    direction = np.array(direction)
    center = np.array([16., 16.])
    problem = make_problem(start=center - 8 * direction, end=center + 8 * direction)
    route = Route(np.array([center - 2 * direction, center, center, center + 2 * direction]))
    reference = RouteEvaluator(problem).evaluate(route)
    compiled = CompiledRouteEvaluator(problem).evaluate(route)
    assert not reference.is_feasible and not compiled.is_feasible
    assert reference.violations["invalid_geometry"] == compiled.violations["invalid_geometry"] == 1
    np.testing.assert_allclose(compiled.objectives, reference.objectives, atol=1e-8, rtol=1e-10)
    assert compiled.violations == reference.violations
    assert compiled.violation == reference.violation
