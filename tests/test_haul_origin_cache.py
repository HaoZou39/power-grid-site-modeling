"""Origin changes must preserve uncached field values and complete routes exactly."""

import os

import numpy as np
import pytest

from experiments import haul_field_cache as cache
from modeling.haul_field import build_haul_field, query_exact, query_route


def _scene(directory, dem, walkable, segments):
    directory.mkdir(parents=True, exist_ok=True)
    np.save(directory / "dem_1m.npy", dem)
    np.save(directory / "obstacle_mask_1m.npy", ~walkable)
    np.save(directory / "road_segments_local.npy", segments)


def _cached(directory, dem, walkable, segments, origin, diagonal=False, weight=1.0):
    return cache.get_or_build_haul_field(
        directory, dem, walkable, segments, origin, None,
        uses_landuse=False, diagonal=diagonal, access_elevation_weight=weight,
    )


def _assert_identical(actual, expected):
    for name in (*cache._ARRAY_DTYPES, "road_m"):
        left, right = getattr(actual, name), getattr(expected, name)
        if left is None or right is None:
            assert left is right, name
        else:
            np.testing.assert_array_equal(left, right, err_msg=name)
    assert actual.origin == expected.origin
    assert actual.reachable_gate_count == expected.reachable_gate_count
    assert actual.unreachable_gate_count == expected.unreachable_gate_count
    row, col = np.indices(actual.dem.shape)
    sites = np.column_stack((col.ravel() + .5, row.ravel() + .5))
    sites = np.concatenate((sites, sites + [.071, .127]))
    measured, blocked = query_exact(actual, sites)
    reference, reference_blocked = query_exact(expected, sites)
    np.testing.assert_array_equal(measured, reference)
    np.testing.assert_array_equal(blocked, reference_blocked)
    for site in sites[blocked == 0][::max(1, int(np.count_nonzero(blocked == 0)) // 30)]:
        assert query_route(actual, tuple(site)) == query_route(expected, tuple(site))


def _connected():
    rng = np.random.default_rng(812)
    dem = rng.normal(size=(25, 29)).astype(np.float32)
    walkable = rng.random(dem.shape) > .2
    segments = np.array([[.2, .35, 15., .35], [15., .35, 28.8, 20.1]])
    return dem, walkable, segments


@pytest.mark.parametrize("diagonal", [False, True])
@pytest.mark.parametrize("weight", [0.0, 1.0, 3.0])
def test_origin_changes_and_removal_skip_grid_build_without_any_difference(tmp_path, monkeypatch, diagonal, weight):
    dem, walkable, segments = _connected()
    _scene(tmp_path, dem, walkable, segments)
    result = _cached(tmp_path, dem, walkable, segments, None, diagonal, weight)
    assert result.status == "built"

    def forbidden(*args, **kwargs):
        pytest.fail("changing the origin rebuilt the Dijkstra grid")

    monkeypatch.setattr(cache, "build_haul_field", forbidden)
    for origin in ((2.125, 1.7), (27.3, 24.9), (10.25, .35), None):
        reused = _cached(tmp_path, dem, walkable, segments, origin, diagonal, weight)
        assert reused.status == "disk_hit"
        _assert_identical(reused.field, build_haul_field(dem, walkable, segments, origin, diagonal, weight))


def test_cache_created_with_origin_can_be_reused_without_origin(tmp_path, monkeypatch):
    dem, walkable, segments = _connected()
    _scene(tmp_path, dem, walkable, segments)
    _cached(tmp_path, dem, walkable, segments, (2.125, 1.7))

    def forbidden(*args, **kwargs):
        pytest.fail("removing the origin rebuilt the grid")

    monkeypatch.setattr(cache, "build_haul_field", forbidden)
    reused = _cached(tmp_path, dem, walkable, segments, None)
    _assert_identical(reused.field, build_haul_field(dem, walkable, segments))


@pytest.mark.parametrize("diagonal", [False, True])
def test_disconnected_components_have_separate_fields(tmp_path, diagonal):
    dem = np.arange(120, dtype=np.float64).reshape(10, 12) / 7
    walkable = np.ones(dem.shape, dtype=bool)
    walkable[4:6] = False
    segments = np.array([[.5, 1.5, 4.5, 1.5], [7.5, 7.5, 11.5, 7.5]])
    _scene(tmp_path, dem, walkable, segments)
    seen = {}
    for origin in (None, (1.5, 1.5), (8.5, 7.5), (2.5, 1.5)):
        result = _cached(tmp_path, dem, walkable, segments, origin, diagonal)
        _assert_identical(result.field, build_haul_field(dem, walkable, segments, origin, diagonal))
        seen[origin] = result
    assert seen[(1.5, 1.5)].key != seen[(8.5, 7.5)].key
    assert seen[(1.5, 1.5)].key != seen[None].key
    assert seen[(2.5, 1.5)].key == seen[(1.5, 1.5)].key
    assert seen[(2.5, 1.5)].status == "disk_hit"


def test_diagonal_equal_gap_reuses_exact_heap_result(tmp_path, monkeypatch):
    dem = np.random.default_rng(4).normal(size=(15, 20))
    walkable = np.ones(dem.shape, dtype=bool)
    segments = np.array([[0., .5, 19.9, .5]])
    _scene(tmp_path, dem, walkable, segments)
    original = _cached(tmp_path, dem, walkable, segments, (1.25, 1.5), True)

    def forbidden(*args, **kwargs):
        pytest.fail("equal-gap diagonal update rebuilt the grid")

    monkeypatch.setattr(cache, "build_haul_field", forbidden)
    reused = _cached(tmp_path, dem, walkable, segments, (4.25, 1.5), True)
    assert reused.key == original.key
    _assert_identical(reused.field, build_haul_field(dem, walkable, segments, (4.25, 1.5), True))


def test_diagonal_changed_gap_reuses_the_same_weighted_paths(tmp_path):
    rng = np.random.default_rng(125)
    for _ in range(58):
        dem = rng.normal(size=(14, 16)).astype(np.float32)
        walkable = rng.random(dem.shape) > .15
        origin = (float(rng.uniform(0, 16)), float(rng.uniform(0, 14)))
    segments = np.array([[.5, .5, .5, 13.5], [.5, 13.5, 15.5, 13.5]])
    _scene(tmp_path, dem, walkable, segments)
    first = _cached(tmp_path, dem, walkable, segments, (.5, .5), True)
    second = _cached(tmp_path, dem, walkable, segments, origin, True)
    assert first.key == second.key
    assert second.status == "disk_hit"
    np.testing.assert_array_equal(first.field.predecessor, second.field.predecessor)
    np.testing.assert_array_equal(first.field.access_rise_m, second.field.access_rise_m)
    _assert_identical(second.field, build_haul_field(dem, walkable, segments, origin, True))


@pytest.mark.parametrize("change", ["dem", "mask", "segments", "source", "form"])
def test_scene_or_constraint_change_invalidates_reusable_field(tmp_path, change):
    dem, walkable, segments = _connected()
    _scene(tmp_path, dem, walkable, segments)
    first = _cached(tmp_path, dem, walkable, segments, None)
    form = None
    if change == "dem":
        dem = dem + .1
    elif change == "mask":
        walkable = walkable.copy()
        walkable[10, 10] = ~walkable[10, 10]
    elif change == "segments":
        segments = segments + .01
    elif change == "source":
        source = tmp_path / "dem_1m.npy"
        before = source.stat()
        np.save(source, dem + .1)
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
    else:
        form = {"field_cost": .8}
    # Use the landuse identity for the form invalidation case.
    if change == "form":
        np.save(tmp_path / "landuse_1m.npy", np.zeros_like(dem, dtype=np.int32))
        first = cache.get_or_build_haul_field(tmp_path, dem, walkable, segments, None, None, uses_landuse=True)
    second = cache.get_or_build_haul_field(
        tmp_path, dem, walkable, segments, (2.125, 1.7), form, uses_landuse=change == "form",
    )
    assert second.status == "built"
    assert first.key != second.key
    _assert_identical(second.field, build_haul_field(dem, walkable, segments, (2.125, 1.7)))


@pytest.mark.parametrize("damage", ["range", "duplicates", "order", "predecessor", "owner"])
def test_corrupt_settlement_orders_are_rebuilt(tmp_path, damage):
    dem, walkable, segments = _connected()
    _scene(tmp_path, dem, walkable, segments)
    first = _cached(tmp_path, dem, walkable, segments, None)
    path = tmp_path / cache._CACHE_DIRECTORY / first.key / "access_order.npy"
    if damage == "range":
        np.save(path, np.array([-1], dtype=np.int32))
    elif damage == "duplicates":
        order = np.load(path)
        order[-1] = order[0]
        np.save(path, order)
    elif damage == "order":
        np.save(path, np.load(path)[::-1])
    else:
        name = "predecessor" if damage == "predecessor" else "gate_owner"
        values = np.load(path.with_name(f"{name}.npy"))
        values[first.field.reachable] = 0 if name == "predecessor" else -1
        np.save(path.with_name(f"{name}.npy"), values)
    repaired = _cached(tmp_path, dem, walkable, segments, (2.125, 1.7))
    assert repaired.status == "built"
    _assert_identical(repaired.field, build_haul_field(dem, walkable, segments, (2.125, 1.7)))


@pytest.mark.parametrize("diagonal", [False, True])
def test_origin_with_no_reachable_gate_still_raises(tmp_path, diagonal):
    dem = np.zeros((6, 6), dtype=np.float32)
    walkable = np.zeros(dem.shape, dtype=bool)
    segments = np.array([[.5, .5, 5.5, .5]])
    _scene(tmp_path, dem, walkable, segments)
    _cached(tmp_path, dem, walkable, segments, None, diagonal)
    with pytest.raises(ValueError, match="reachable_gates=0"):
        _cached(tmp_path, dem, walkable, segments, (1.5, .5), diagonal)


@pytest.mark.parametrize("change", ["weight", "diagonal"])
def test_path_configuration_invalidates_cache(tmp_path, change):
    dem, walkable, segments = _connected()
    _scene(tmp_path, dem, walkable, segments)
    first = _cached(tmp_path, dem, walkable, segments, None)
    diagonal, weight = (True, 1.0) if change == "diagonal" else (False, 2.0)
    second = _cached(tmp_path, dem, walkable, segments, None, diagonal, weight)
    assert second.key != first.key
    assert second.status == "built"
    _assert_identical(second.field, build_haul_field(dem, walkable, segments, None, diagonal, weight))
