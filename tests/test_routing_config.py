import json
from dataclasses import asdict, replace

import numpy as np
import pytest
from pyproj import Transformer

from config.project_config import DEFAULT_CONFIG_PATH, load_default_config, load_project_config
from modeling.routing.types import OBJECTIVE_NAMES, Route, RoutingConstraints, RoutingFrame


def test_default_routing_values_have_one_source():
    assert asdict(load_default_config().routing) == json.loads(DEFAULT_CONFIG_PATH.read_text())["routing"]
    assert OBJECTIVE_NAMES == ("tower_count", "length_3d_m", "bend_sum_rad", "crossing_3d_m")


@pytest.mark.parametrize("change", [{"devices": []}, {"devices": ["cpu", "cuda:0"]},
    {"devices": ["cuda:0", "cuda:0"]}, {"devices": ["cuda"]}, {"evolution_backend": "guess"},
    {"evaluation_backend": "approximate"}, {"evaluation_batch_size": 0}, {"gpu_memory_budget_mib": True}])
def test_execution_settings_are_explicit(change):
    with pytest.raises(ValueError):
        replace(load_default_config().routing, **change)


@pytest.mark.parametrize("change", ["missing", "extra", "invalid"])
def test_routing_config_rejects_bad_fields(tmp_path, change):
    raw = json.loads(DEFAULT_CONFIG_PATH.read_text())
    if change == "missing":
        del raw["routing"]["seed"]
    elif change == "extra":
        raw["routing"]["crossing_price"] = 10
    else:
        raw["routing"]["popsize"] = True
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    with pytest.raises((TypeError, ValueError)):
        load_project_config(path)


@pytest.mark.parametrize("field,value", [("max_span_m", 0), ("tower_radius_m", -1),
    ("max_turn_deg", 181), ("road_setback_m", -1), ("highway_setback_m", float("inf")),
    ("max_span_m", True)])
def test_constraints_are_explicit_and_finite(field, value):
    valid = RoutingConstraints(100, 2, 60, 0, 0)
    with pytest.raises(ValueError):
        replace(valid, **{field: value})


def test_zero_tower_route_keeps_endpoints_out_of_genes():
    route = Route(np.empty((0, 2)))
    np.testing.assert_array_equal(route.points((1, 2), (8, 9)), [[1, 2], [8, 9]])
    assert route.towers.shape == (0, 2)
    assert not route.towers.flags.writeable


def test_frame_matches_independent_projection_and_rejects_outside():
    frame = RoutingFrame("EPSG:32651", (1, 0, 221000, 0, -1, 3046000), 1800, 1800)
    lng, lat = Transformer.from_crs(32651, 4326, always_xy=True).transform(221123.5, 3045678.75)
    point = frame.to_local(lng, lat)
    np.testing.assert_allclose(point, [123.5, 321.25], atol=1e-7)
    np.testing.assert_allclose(frame.to_wgs84(point), [lng, lat], atol=1e-10)
    with pytest.raises(ValueError, match="outside"):
        frame.to_local(lng + 1, lat)
    with pytest.raises(ValueError):
        frame.validate_point([float("nan"), 1])


def test_saved_task_without_generations_keeps_the_old_generation_ceiling():
    import math
    from config.routing_task import RoutingParameters
    raw = asdict(load_default_config().routing)
    del raw["max_generations"]
    raw["popsize"] = 48
    raw["max_evaluations"] = 100
    assert RoutingParameters.model_validate(raw).max_generations == math.ceil(100 / 48)
    raw["max_generations"] = 9
    assert RoutingParameters.model_validate(raw).max_generations == 9


def test_grid_must_be_metric_and_one_metre():
    with pytest.raises(ValueError):
        RoutingFrame("EPSG:3857", (1, 0, 0, 0, -1, 0), 100, 100)
    with pytest.raises(ValueError):
        RoutingFrame("EPSG:32651", (2, 0, 0, 0, -2, 0), 100, 100)
