"""Construction reports stay outside the three search objectives."""

import math
from types import SimpleNamespace

import numpy as np
import pytest

from algorithms.common.scalarization import OBJECTIVE_NAMES
from modeling.access_path import access_profile, access_warning
from modeling.haul_field import query_route
from modeling.evaluator import compute_hard_constraints
from modeling.logistics_cost import RoadDisconnectedError, logistics_route
from modeling.slope import footprint_max_slope_deg
from experiments.constraint_mask import compose_constraint_masks, policy_from_form, polygons_from_form
from experiments.haul_field_cache import compatible_haul_field, haul_memory_identity
from experiments.launch_site_run import _shared_haul_field
from experiments.site_report import (
    build_site_report,
    clear_site_report_cache,
    site_report_cache_info,
    site_report_hard_mask,
)


def test_uniform_slope_is_steeper_than_flat_ground() -> None:
    flat = np.full((8, 8), 3.0, dtype=np.float32)
    ramp = np.zeros((8, 8), dtype=np.float32)
    ramp[:] = np.arange(8, dtype=np.float32) * 0.5
    pose = (4.5, 4.5, 0.0)
    assert footprint_max_slope_deg(ramp, pose, 4.0, 4.0) > footprint_max_slope_deg(flat, pose, 4.0, 4.0)
    assert OBJECTIVE_NAMES == ("dem_soft", "road_distance", "demand_distance")


def test_nearby_origin_has_a_shorter_road_length() -> None:
    segments = np.array([[0.0, 0.0, 10.0, 0.0]], dtype=np.float64)
    near = logistics_route((0.0, 1.0), (1.0, 1.0), segments)
    far = logistics_route((0.0, 1.0), (10.0, 1.0), segments)
    assert near["road_m"] < far["road_m"]
    assert math.isclose(far["road_m"], 10.0)
    assert math.isclose(far["offroad_m"], 2.0)
    joined = np.array([[0.0, 0.0, 5.0, 0.0], [5.0, 0.0, 10.0, 0.0]], dtype=np.float64)
    route = logistics_route((0.0, 1.0), (10.0, 1.0), joined)
    assert route["points"][0] == (0.0, 1.0)
    assert route["points"][-1] == (10.0, 1.0)
    assert any(abs(point[1]) < 0.01 for point in route["points"])


def test_points_inside_the_same_segment_use_the_direct_road_distance() -> None:
    segments = np.array([[0.0, 0.0, 10.0, 0.0]], dtype=np.float64)
    route = logistics_route((2.0, 0.0), (8.0, 0.0), segments)
    assert math.isclose(route["road_m"], 6.0)
    assert math.isclose(route["offroad_m"], 0.0)


def test_disconnected_roads_do_not_create_a_false_route() -> None:
    segments = np.array(
        [[0.0, 0.0, 4.0, 0.0], [10.0, 0.0, 14.0, 0.0]],
        dtype=np.float64,
    )
    with pytest.raises(RoadDisconnectedError, match="connected road network"):
        logistics_route((1.0, 0.0), (11.0, 0.0), segments)


def test_steep_approach_warns_without_changing_feasibility() -> None:
    dem = np.zeros((1, 7), dtype=np.float32)
    dem[0, 3] = 5.0
    segments = np.array([[6.5, 0.5, 8.5, 0.5]], dtype=np.float64)
    steep = access_profile(dem, (0.5, 0.5), segments)
    flat = access_profile(np.zeros_like(dem), (0.5, 0.5), segments)
    assert steep["max_slope_deg"] > flat["max_slope_deg"]
    assert access_warning(steep["max_slope_deg"], 10.0) is True
    feasible = compute_hard_constraints(
        dem,
        np.zeros_like(dem),
        np.array([[0.5, 0.5, 0.0]]),
        0.4,
        0.4,
        device="cpu",
    )
    assert bool(feasible["is_feasible"][0].item()) is True


def test_unreachable_construction_path_does_not_hide_infeasibility(tmp_path) -> None:
    _write_scene(tmp_path)
    report = build_site_report(
        tmp_path,
        6.5,
        6.5,
        0.0,
        2.0,
        2.0,
        obstacle_mask=np.ones((12, 12), dtype=np.float32),
        allow_unreachable=True,
    )
    assert report["offroad_haul_m"] is None
    assert "access_error" in report


@pytest.mark.parametrize("field_policy", ["allowed", "costly"])
def test_site_report_uses_nonblocking_field_policy(tmp_path, field_policy: str) -> None:
    _write_scene(tmp_path, site_class=1)
    report = build_site_report(
        tmp_path,
        6.5,
        6.5,
        0.0,
        2.0,
        2.0,
        constraint_form=_constraint_form(field_policy=field_policy),
    )
    assert report["offroad_haul_m"] is not None
    assert float(report["offroad_haul_m"]) >= 0


def test_site_report_blocks_field_when_policy_blocks_it(tmp_path) -> None:
    _write_scene(tmp_path, site_class=1)
    with pytest.raises(ValueError, match="not buildable"):
        build_site_report(
            tmp_path,
            6.5,
            6.5,
            0.0,
            2.0,
            2.0,
            constraint_form=_constraint_form(field_policy="blocked"),
        )


def test_site_report_applies_mountain_policy(tmp_path) -> None:
    _write_scene(tmp_path, site_class=4)
    allowed = build_site_report(
        tmp_path,
        6.5,
        6.5,
        0.0,
        2.0,
        2.0,
        constraint_form=_constraint_form(mountain_policy="allowed"),
    )
    assert allowed["offroad_haul_m"] is not None
    with pytest.raises(ValueError, match="not buildable"):
        build_site_report(
            tmp_path,
            6.5,
            6.5,
            0.0,
            2.0,
            2.0,
            constraint_form=_constraint_form(mountain_policy="blocked"),
        )


@pytest.mark.parametrize("site_class", [2, 5])
def test_site_report_always_blocks_buildings_and_water(tmp_path, site_class: int) -> None:
    _write_scene(tmp_path, site_class=site_class)
    with pytest.raises(ValueError, match="not buildable"):
        build_site_report(
            tmp_path,
            6.5,
            6.5,
            0.0,
            2.0,
            2.0,
            constraint_form=_constraint_form(),
        )


def test_site_report_route_crosses_exclusion_zones_and_applies_feasible_zones(tmp_path) -> None:
    _write_scene(tmp_path)
    # 禁区只禁止建站，进站道路可以穿过。
    exclusion = [{"points": [[5, 5], [8, 5], [8, 8], [5, 8]]}]
    plain = build_site_report(tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0, constraint_form=_constraint_form())
    crossed = build_site_report(
        tmp_path,
        6.5,
        6.5,
        0.0,
        2.0,
        2.0,
        constraint_form=_constraint_form(exclusion_zones=exclusion),
    )
    assert crossed == plain
    feasible = [{"points": [[0, 0], [9, 0], [9, 9], [0, 9]]}]
    report = build_site_report(
        tmp_path,
        6.5,
        6.5,
        0.0,
        2.0,
        2.0,
        constraint_form=_constraint_form(feasible_zones=feasible),
    )
    assert report["haul_path"]


def test_site_report_route_with_and_without_origin(tmp_path) -> None:
    _write_scene(tmp_path)
    form = _constraint_form()
    approach = build_site_report(tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0, constraint_form=form)
    routed = build_site_report(
        tmp_path,
        6.5,
        6.5,
        0.0,
        2.0,
        2.0,
        origin=(2.5, 1.5),
        constraint_form=form,
    )
    assert approach["road_haul_m"] is None
    assert approach["haul_path"][-1] == (6.5, 6.5)
    assert routed["road_haul_m"] is not None
    assert routed["haul_path"][0] == (2.5, 1.5)
    assert routed["haul_path"][-1] == (6.5, 6.5)


def test_site_report_mask_is_the_search_access_mask_without_exclusions(tmp_path) -> None:
    _write_scene(tmp_path, site_class=1)
    form = _constraint_form(
        field_policy="costly",
        mountain_policy="blocked",
        exclusion_zones=[{"points": [[8, 8], [10, 8], [10, 10], [8, 10]]}],
        feasible_zones=[{"points": [[0, 0], [11, 0], [11, 11], [0, 11]]}],
    )
    landuse = np.load(tmp_path / "landuse_1m.npy")
    expected, _soft = compose_constraint_masks(
        landuse,
        [],
        policy_from_form(form),
        polygons_from_form(form, "feasible_zones"),
    )
    assert np.array_equal(site_report_hard_mask(tmp_path, form), expected)


def test_exclusion_zone_blocks_building_but_not_the_access_mask(tmp_path, monkeypatch) -> None:
    import torch
    from config.project_config import load_default_config
    from experiments.launch_site_run import constrained_problem
    from modeling.context import building_hard_mask

    scene = tmp_path / "demo"
    scene.mkdir()
    _write_scene(scene)
    (scene / "data_metadata.json").write_text("{}")
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path))
    modeling = load_default_config().modeling
    base = _constraint_form(scene_name="demo", road_setback_m=0, water_setback_m=0, highway_setback_m=0)
    zone = [{"points": [[5, 5], [8, 5], [8, 8], [5, 8]]}]
    plain, _ = constrained_problem(base, torch.device("cpu"), modeling)
    zoned, _ = constrained_problem({**base, "exclusion_zones": zone}, torch.device("cpu"), modeling)

    assert np.array_equal(zoned.obstacle_mask, plain.obstacle_mask)
    assert building_hard_mask(plain)[6, 6] == 0
    assert building_hard_mask(zoned)[6, 6] > 0


def test_explicit_obstacle_mask_remains_supported(tmp_path) -> None:
    _write_scene(tmp_path, site_class=1)
    report = build_site_report(
        tmp_path,
        6.5,
        6.5,
        0.0,
        2.0,
        2.0,
        obstacle_mask=np.zeros((12, 12), dtype=np.float32),
    )
    assert report["offroad_haul_m"] is not None
    with pytest.raises(ValueError, match="cannot both"):
        build_site_report(
            tmp_path,
            6.5,
            6.5,
            0.0,
            2.0,
            2.0,
            obstacle_mask=np.zeros((12, 12), dtype=np.float32),
            constraint_form=_constraint_form(),
        )


def test_site_report_reuses_one_bounded_field_for_the_same_scene_and_constraints(tmp_path) -> None:
    _write_scene(tmp_path)
    clear_site_report_cache()
    form = _constraint_form()
    first = build_site_report(tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0, constraint_form=form)
    second = build_site_report(tmp_path, 7.5, 6.5, 0.0, 2.0, 2.0, constraint_form=form)
    info = site_report_cache_info()

    assert first["haul_path"] and second["haul_path"]
    assert info.maxsize == 1
    assert info.misses == 1
    assert info.hits == 1


def test_site_report_cache_invalidates_on_constraint_or_scene_file_change(tmp_path) -> None:
    _write_scene(tmp_path)
    clear_site_report_cache()
    build_site_report(tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0, constraint_form=_constraint_form())
    build_site_report(
        tmp_path,
        6.5,
        6.5,
        0.0,
        2.0,
        2.0,
        constraint_form=_constraint_form(field_cost=0.25),
    )
    assert site_report_cache_info().misses == 2

    clear_site_report_cache()
    build_site_report(tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0, origin=(1.5, 0.5), constraint_form=_constraint_form())
    build_site_report(tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0, origin=(2.5, 0.5), constraint_form=_constraint_form())
    assert site_report_cache_info().misses == 2

    landuse_path = tmp_path / "landuse_1m.npy"
    clear_site_report_cache()
    build_site_report(tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0, constraint_form=_constraint_form())
    np.save(landuse_path, np.load(landuse_path))
    build_site_report(tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0, constraint_form=_constraint_form())
    assert site_report_cache_info().misses == 2

    obstacle_path = tmp_path / "obstacle_mask_1m.npy"
    clear_site_report_cache()
    build_site_report(tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0)
    np.save(obstacle_path, np.load(obstacle_path))
    build_site_report(tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0)
    assert site_report_cache_info().misses == 2


def _constraint_form(**overrides) -> dict:
    form = {
        "field_policy": "allowed",
        "mountain_policy": "allowed",
        "field_cost": 0.5,
        "exclusion_zones": [],
        "feasible_zones": [],
    }
    form.update(overrides)
    return form


def _write_scene(directory, site_class: int = 0) -> None:
    shape = (12, 12)
    dem = np.arange(shape[0], dtype=np.float32)[:, None] * np.ones(shape, dtype=np.float32)
    np.save(directory / "dem_1m.npy", dem)
    np.save(directory / "obstacle_mask_1m.npy", np.zeros(shape, dtype=np.float32))
    landuse = np.zeros(shape, dtype=np.int32)
    landuse[6, 6] = site_class
    np.save(directory / "landuse_1m.npy", landuse)
    np.save(directory / "road_segments_local.npy", np.array([[0.5, 0.5, 11.5, 0.5]], dtype=np.float32))
    np.save(directory / "road_segment_kind.npy", np.zeros(len(np.load(directory / "road_segments_local.npy")), np.int8))
    np.save(directory / "road_voronoi_1m.npy", np.zeros(shape, dtype=np.int64))
    np.save(directory / "demand_points.npy", np.array([[10.5, 10.5]], dtype=np.float32))


def _publish_field(directory, form, weight=1.0):
    dem = np.load(directory / "dem_1m.npy")
    problem = SimpleNamespace(
        access_connector_blocked=None,
        obstacle_mask=np.zeros(dem.shape, dtype=np.float32),
        dem=dem,
        road_segments=np.load(directory / "road_segments_local.npy"),
        road_segment_kinds=np.load(directory / "road_segment_kind.npy"),
    )
    return _shared_haul_field(problem, {"scene_dir": str(directory)}, form, weight)


def _same_route(report, route) -> None:
    assert report["offroad_haul_m"] == route["offroad_haul_m"]
    assert report["road_haul_m"] == route.get("road_haul_m")
    assert report["haul_rise_m"] == route["haul_rise_m"]
    assert report["access_slope_deg"] == route["access_slope_deg"]
    assert report["haul_path"] == route["points"]


def test_site_report_reuses_the_validated_field_from_the_same_process(tmp_path, monkeypatch) -> None:
    _write_scene(tmp_path)
    clear_site_report_cache()
    form = _constraint_form()
    field = _publish_field(tmp_path, form)
    direct = query_route(field, (6.5, 6.5))

    def refuse_disk(*_args, **_kwargs):
        raise AssertionError("site-report reloaded a field that was already built")

    monkeypatch.setattr("experiments.site_report.get_or_build_haul_field", refuse_disk)
    monkeypatch.setattr("experiments.haul_field_cache._array_identity", refuse_disk)
    before = site_report_cache_info()
    first = build_site_report(tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0, constraint_form=form)
    second = build_site_report(tmp_path, 7.5, 6.5, 0.0, 2.0, 2.0, constraint_form=form)
    after = site_report_cache_info()

    _same_route(first, direct)
    assert second["haul_path"]
    assert after.hits == before.hits
    assert after.misses == before.misses
    seen = []
    real_query = query_route

    def record(candidate, site):
        seen.append(candidate)
        return real_query(candidate, site)

    monkeypatch.setattr("experiments.site_report.query_route", record)
    build_site_report(tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0, constraint_form=form)
    assert seen == [field]


def test_changed_constraints_do_not_reuse_the_previous_field(tmp_path, monkeypatch) -> None:
    _write_scene(tmp_path)
    clear_site_report_cache()
    form = _constraint_form()
    field = _publish_field(tmp_path, form)
    old_route = query_route(field, (6.5, 6.5))
    calls = []
    real = __import__("experiments.site_report", fromlist=["get_or_build_haul_field"]).get_or_build_haul_field

    def wrapped(*args, **kwargs):
        calls.append(args[2].sum())
        return real(*args, **kwargs)

    monkeypatch.setattr("experiments.site_report.get_or_build_haul_field", wrapped)
    zoned = _constraint_form(exclusion_zones=[{"points": [[5.0, 5.0], [8.0, 5.0], [8.0, 8.0], [5.0, 8.0]]}])
    same = build_site_report(tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0, constraint_form=zoned)
    assert not calls
    _same_route(same, old_route)

    blocked = _constraint_form(feasible_zones=[{"points": [[0.0, 0.0], [12.0, 0.0], [12.0, 5.0], [0.0, 5.0]]}])
    report = build_site_report(
        tmp_path,
        6.5,
        6.5,
        0.0,
        2.0,
        2.0,
        constraint_form=blocked,
        allow_unreachable=True,
    )
    assert calls
    assert calls[0] < field.dem.size
    assert report["access_error"]
    assert old_route["points"]

    calls.clear()
    moved = build_site_report(
        tmp_path,
        6.5,
        6.5,
        0.0,
        2.0,
        2.0,
        origin=(1.5, 0.5),
        constraint_form=form,
    )
    assert calls
    assert moved["road_haul_m"] != old_route.get("road_haul_m")
    fresh = real(
        tmp_path,
        field.dem,
        np.ones(field.dem.shape, dtype=bool),
        field.segments,
        (1.5, 0.5),
        form,
        uses_landuse=True,
        access_elevation_weight=1.0,
        segment_kinds=np.load(tmp_path / "road_segment_kind.npy"),
    ).field
    _same_route(moved, query_route(fresh, (6.5, 6.5)))

    calls.clear()
    weighted = build_site_report(
        tmp_path,
        6.5,
        6.5,
        0.0,
        2.0,
        2.0,
        constraint_form=form,
        access_elevation_weight=4.0,
    )
    assert calls
    weighted_field = real(
        tmp_path,
        field.dem,
        np.ones(field.dem.shape, dtype=bool),
        field.segments,
        None,
        form,
        uses_landuse=True,
        access_elevation_weight=4.0,
        segment_kinds=np.load(tmp_path / "road_segment_kind.npy"),
    ).field
    assert weighted_field is not field
    _same_route(weighted, query_route(weighted_field, (6.5, 6.5)))


def test_empty_registry_reads_the_disk_cache(tmp_path, monkeypatch) -> None:
    _write_scene(tmp_path)
    clear_site_report_cache()
    form = _constraint_form()
    field = _publish_field(tmp_path, form)
    clear_site_report_cache()
    calls = []
    real = __import__("experiments.haul_field_cache", fromlist=["get_or_build_haul_field"]).get_or_build_haul_field

    def wrapped(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr("experiments.site_report.get_or_build_haul_field", wrapped)
    report = build_site_report(tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0, constraint_form=form)
    assert calls == [1]
    _same_route(report, query_route(field, (6.5, 6.5)))
    assert compatible_haul_field(haul_memory_identity(
        tmp_path, form, None, 1.0, uses_landuse=True, diagonal=True,
    )) is None


def test_reuse_keeps_only_the_latest_validated_field(tmp_path) -> None:
    _write_scene(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    _write_scene(other)
    clear_site_report_cache()
    form = _constraint_form()
    first = _publish_field(tmp_path, form)
    first_identity = haul_memory_identity(tmp_path, form, None, 1.0, uses_landuse=True, diagonal=True)
    _publish_field(other, form)
    assert compatible_haul_field(first_identity) is None
    assert compatible_haul_field(haul_memory_identity(
        other, form, None, 1.0, uses_landuse=True, diagonal=True,
    )) is not first


def test_scene_file_or_field_cost_change_does_not_reuse_a_published_field(tmp_path, monkeypatch) -> None:
    _write_scene(tmp_path)
    clear_site_report_cache()
    form = _constraint_form()
    field = _publish_field(tmp_path, form)
    calls = []
    real = __import__("experiments.site_report", fromlist=["get_or_build_haul_field"]).get_or_build_haul_field

    def wrapped(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr("experiments.site_report.get_or_build_haul_field", wrapped)
    build_site_report(
        tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0,
        constraint_form=_constraint_form(field_cost=0.25),
    )
    assert calls == [1]
    np.save(tmp_path / "landuse_1m.npy", np.load(tmp_path / "landuse_1m.npy"))
    build_site_report(tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0, constraint_form=form)
    assert calls == [1, 1]


def test_explicit_mask_does_not_reuse_a_published_field(tmp_path, monkeypatch) -> None:
    _write_scene(tmp_path)
    clear_site_report_cache()
    field = _publish_field(tmp_path, _constraint_form())
    seen = []

    def record(candidate, site):
        seen.append(candidate)
        return query_route(candidate, site)

    monkeypatch.setattr("experiments.site_report.query_route", record)
    build_site_report(tmp_path, 6.5, 6.5, 0.0, 2.0, 2.0, obstacle_mask=np.zeros((12, 12), dtype=np.float32))
    assert seen and seen[0] is not field
