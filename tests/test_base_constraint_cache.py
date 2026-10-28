"""Base setback masks stay pixel-identical when only drawn zones change."""

from __future__ import annotations

import threading

import numpy as np
import pytest
import torch

from experiments.base_constraint_cache import (
    BaseConstraintCache,
    base_constraint_cache_info,
    cached_highway_buffer,
    cached_road_buffer,
    cached_water_buffer,
    clear_base_constraint_cache,
    scene_buffer_sources,
)
from experiments.constraint_mask import compose_constraint_masks, policy_from_form
from experiments.problem_context import context_from_arrays, with_constraint_masks
from experiments.protected_farmland import access_inputs, dilate_mask, mask_path
from modeling.context import (
    highway_building_buffer,
    road_building_buffer,
    water_building_buffer,
)
from modeling.evaluator import compute_hard_constraints
from modeling.haul_field import build_haul_field, query_exact


SHAPE = (24, 24)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_base_constraint_cache()
    yield
    clear_base_constraint_cache()


def _save_scene(directory, landuse, segments, kinds) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    np.save(directory / "landuse_1m.npy", np.asarray(landuse))
    np.save(directory / "road_segments_local.npy", np.asarray(segments, dtype=np.float64))
    np.save(directory / "road_segment_kind.npy", np.asarray(kinds, dtype=np.int8))


def _load_scene(directory):
    return (
        np.load(directory / "landuse_1m.npy"),
        np.load(directory / "road_segments_local.npy"),
        np.load(directory / "road_segment_kind.npy"),
    )


def _arrays(landuse, segments, kinds, obstacle=None):
    return {
        "dem": np.zeros(landuse.shape, dtype=np.float32),
        "landuse": landuse,
        "obstacle_mask": np.zeros(landuse.shape, dtype=np.float32) if obstacle is None else obstacle,
        "road_segments": segments,
        "road_segment_kinds": kinds,
        "road_voronoi": np.zeros(landuse.shape, dtype=np.int64),
        "demand_points": np.array([[4.5, 4.5]], dtype=np.float32),
    }


def _scene(tmp_path, landuse, segments, kinds):
    _save_scene(tmp_path, landuse, segments, kinds)
    loaded = _load_scene(tmp_path)
    sources = scene_buffer_sources(tmp_path, loaded[0].shape)
    assert sources is not None
    return loaded, sources


def _base_landuse():
    landuse = np.zeros(SHAPE, dtype=np.uint8)
    landuse[0, 0] = 3
    landuse[5, 5] = 5
    landuse[-1, 10] = 3
    return landuse


def _roads():
    segments = np.array([
        [0.5, 12.5, SHAPE[1] - 0.5, 12.5],
        [-6.0, 8.5, SHAPE[1] + 4.0, 8.5],
    ], dtype=np.float64)
    kinds = np.array([0, 1], dtype=np.int8)
    return segments, kinds


def test_cached_masks_match_direct_results_and_hits_share_the_array(tmp_path):
    landuse, segments, kinds = _base_landuse(), *_roads()
    (landuse_loaded, segments_loaded, kinds_loaded), sources = _scene(tmp_path, landuse, segments, kinds)
    osm = np.zeros(SHAPE, dtype=bool)
    osm[12, :] = True
    for setback in (0.0, 2.5):
        clear_base_constraint_cache()
        direct_road = road_building_buffer(landuse_loaded, osm, setback)
        direct_water = water_building_buffer(landuse_loaded, setback)
        direct_highway = highway_building_buffer(segments_loaded, kinds_loaded, SHAPE, setback)
        first_road = cached_road_buffer(sources, setback, landuse_loaded, osm)
        first_water = cached_water_buffer(sources, setback, landuse_loaded)
        first_highway = cached_highway_buffer(sources, setback, segments_loaded, kinds_loaded, SHAPE)
        second_road = cached_road_buffer(sources, setback, landuse_loaded, osm)
        second_water = cached_water_buffer(sources, setback, landuse_loaded)
        second_highway = cached_highway_buffer(sources, setback, segments_loaded, kinds_loaded, SHAPE)
        assert np.array_equal(first_road, direct_road)
        assert np.array_equal(first_water, direct_water)
        assert np.array_equal(first_highway, direct_highway)
        assert second_road is first_road and second_water is first_water and second_highway is first_highway
        assert base_constraint_cache_info()["hits"] == 3
        assert base_constraint_cache_info()["misses"] == 3


def test_empty_sources_and_a_single_water_cell_match(tmp_path):
    empty = np.zeros(SHAPE, dtype=np.uint8)
    no_segments = np.zeros((0, 4), dtype=np.float64)
    no_kinds = np.zeros((0,), dtype=np.int8)
    _, sources = _scene(tmp_path, empty, no_segments, no_kinds)
    landuse, segments, kinds = _load_scene(tmp_path)
    osm = np.zeros(SHAPE, dtype=bool)
    assert np.array_equal(cached_road_buffer(sources, 4.0, landuse, osm), road_building_buffer(landuse, osm, 4.0))
    assert np.array_equal(cached_water_buffer(sources, 4.0, landuse), water_building_buffer(landuse, 4.0))
    assert not cached_highway_buffer(sources, 4.0, segments, kinds, SHAPE).any()

    single = empty.copy()
    single[1, 1] = 5
    water_dir = tmp_path / "water"
    _, water_sources = _scene(water_dir, single, no_segments, no_kinds)
    loaded = np.load(water_dir / "landuse_1m.npy")
    direct = water_building_buffer(loaded, 1.5)
    cached = cached_water_buffer(water_sources, 1.5, loaded)
    assert np.array_equal(cached, direct)
    assert cached[1, 1] and cached[1, 2]


def test_highway_crossing_the_border_keeps_the_padded_distance(tmp_path):
    landuse = np.zeros(SHAPE, dtype=np.uint8)
    segments = np.array([[-8.0, 4.5, 3.5, 4.5]], dtype=np.float64)
    kinds = np.array([2], dtype=np.int8)
    _, sources = _scene(tmp_path, landuse, segments, kinds)
    _, loaded_segments, loaded_kinds = _load_scene(tmp_path)
    direct = highway_building_buffer(loaded_segments, loaded_kinds, SHAPE, 3.0)
    cached = cached_highway_buffer(sources, 3.0, loaded_segments, loaded_kinds, SHAPE)
    assert direct.any()
    assert np.array_equal(cached, direct)
    assert np.array_equal(cached_highway_buffer(sources, 3.0, loaded_segments, loaded_kinds, SHAPE), direct)


def test_arrays_without_a_snapshot_do_not_enter_the_cache():
    landuse = _base_landuse()
    segments, kinds = _roads()
    context_from_arrays(
        _arrays(landuse, segments, kinds), torch.device("cpu"),
        road_setback_m=5, water_setback_m=5, highway_setback_m=6,
    )
    assert base_constraint_cache_info()["entries"] == 0


def test_zone_edits_reuse_buffers_and_change_the_hard_mask(tmp_path):
    landuse = _base_landuse()
    segments, kinds = _roads()
    _, sources = _scene(tmp_path, landuse, segments, kinds)
    loaded_landuse, loaded_segments, loaded_kinds = _load_scene(tmp_path)
    context = context_from_arrays(
        _arrays(loaded_landuse, loaded_segments, loaded_kinds), torch.device("cpu"),
        road_setback_m=2.5, water_setback_m=1.5, highway_setback_m=3,
        sources=sources,
    )
    again = context_from_arrays(
        _arrays(loaded_landuse, loaded_segments, loaded_kinds), torch.device("cpu"),
        road_setback_m=2.5, water_setback_m=1.5, highway_setback_m=3,
        sources=sources,
    )
    assert again.road_buffer is context.road_buffer
    assert again.water_buffer is context.water_buffer
    assert again.highway_buffer is context.highway_buffer
    direct = context_from_arrays(
        _arrays(loaded_landuse, loaded_segments, loaded_kinds), torch.device("cpu"),
        road_setback_m=2.5, water_setback_m=1.5, highway_setback_m=3,
    )
    assert np.array_equal(context.road_buffer, direct.road_buffer)
    assert np.array_equal(context.water_buffer, direct.water_buffer)
    assert np.array_equal(context.highway_buffer, direct.highway_buffer)
    assert np.array_equal(context.obstacle_mask, direct.obstacle_mask)
    assert torch.equal(context.building_soft_tensor, direct.building_soft_tensor)

    policy = policy_from_form({"field_policy": "allowed", "mountain_policy": "allowed"})
    exclusion = [[2.0, 2.0], [9.0, 2.0], [9.0, 9.0], [2.0, 9.0]]
    moved = [[3.0, 3.0], [11.0, 3.0], [11.0, 10.0], [3.0, 10.0]]
    feasible = [[14.0, 14.0], [20.0, 14.0], [20.0, 20.0], [14.0, 20.0]]
    none_hard, none_soft = compose_constraint_masks(loaded_landuse, [], policy)
    added_hard, added_soft = compose_constraint_masks(loaded_landuse, [exclusion], policy)
    moved_hard, moved_soft = compose_constraint_masks(loaded_landuse, [moved], policy)
    removed_hard, removed_soft = compose_constraint_masks(loaded_landuse, [], policy)
    feasible_hard, feasible_soft = compose_constraint_masks(loaded_landuse, [], policy, [feasible])
    bare = with_constraint_masks(context, none_hard, none_soft)
    blocked = with_constraint_masks(context, added_hard, added_soft)
    shifted = with_constraint_masks(context, moved_hard, moved_soft)
    cleared = with_constraint_masks(context, removed_hard, removed_soft)
    limited = with_constraint_masks(context, feasible_hard, feasible_soft)
    assert blocked.road_buffer is context.road_buffer
    assert shifted.water_buffer is context.water_buffer
    assert limited.highway_buffer is context.highway_buffer
    assert np.array_equal(cleared.building_obstacle_mask, bare.building_obstacle_mask)
    assert not np.array_equal(blocked.building_obstacle_mask, bare.building_obstacle_mask)
    assert not np.array_equal(shifted.building_obstacle_mask, blocked.building_obstacle_mask)
    assert not np.array_equal(limited.building_obstacle_mask, bare.building_obstacle_mask)
    pose = torch.tensor([[6.5, 6.5, 0.0]], dtype=torch.float32)
    hard_direct = compute_hard_constraints(direct.dem, direct.building_obstacle_mask, pose, 4.0, 3.0, "cpu")
    hard_cached = compute_hard_constraints(context.dem, context.building_obstacle_mask, pose, 4.0, 3.0, "cpu")
    for name in hard_direct:
        assert torch.equal(hard_direct[name], hard_cached[name])
    with pytest.raises(ValueError):
        context.road_buffer[0, 0] = True
    assert np.array_equal(context.road_buffer, direct.road_buffer)


def test_source_and_setback_changes_invalidate_only_their_masks(tmp_path):
    landuse = _base_landuse()
    segments, kinds = _roads()
    _, sources = _scene(tmp_path, landuse, segments, kinds)
    loaded_landuse, loaded_segments, loaded_kinds = _load_scene(tmp_path)
    kwargs = {"road_setback_m": 2.0, "water_setback_m": 2.0, "highway_setback_m": 3.0}
    context_from_arrays(_arrays(loaded_landuse, loaded_segments, loaded_kinds), torch.device("cpu"), sources=sources, **kwargs)
    before = base_constraint_cache_info()

    wider = context_from_arrays(
        _arrays(loaded_landuse, loaded_segments, loaded_kinds), torch.device("cpu"),
        sources=sources, road_setback_m=2.0, water_setback_m=6.5, highway_setback_m=3.0,
    )
    after_water = base_constraint_cache_info()
    assert after_water["misses"] == before["misses"] + 1
    assert after_water["hits"] == before["hits"] + 2
    direct_water = water_building_buffer(loaded_landuse, 6.5)
    assert np.array_equal(wider.water_buffer, direct_water)
    assert not np.array_equal(wider.water_buffer, water_building_buffer(loaded_landuse, 2.0))

    changed = loaded_landuse.copy()
    changed[8, 8] = 5
    np.save(tmp_path / "landuse_1m.npy", changed)
    refreshed = scene_buffer_sources(tmp_path, SHAPE)
    reloaded = np.load(tmp_path / "landuse_1m.npy")
    landuse_context = context_from_arrays(
        _arrays(reloaded, loaded_segments, loaded_kinds), torch.device("cpu"), sources=refreshed, **kwargs,
    )
    after_landuse = base_constraint_cache_info()
    assert after_landuse["misses"] == after_water["misses"] + 2
    assert after_landuse["hits"] == after_water["hits"] + 1
    assert np.array_equal(landuse_context.water_buffer, water_building_buffer(reloaded, 2.0))
    assert landuse_context.highway_buffer is wider.highway_buffer

    moved_segments = loaded_segments.copy()
    moved_segments[0, 1] += 2
    moved_segments[0, 3] += 2
    np.save(tmp_path / "road_segments_local.npy", moved_segments)
    road_sources = scene_buffer_sources(tmp_path, SHAPE)
    road_segments = np.load(tmp_path / "road_segments_local.npy")
    road_context = context_from_arrays(
        _arrays(reloaded, road_segments, loaded_kinds), torch.device("cpu"), sources=road_sources, **kwargs,
    )
    after_roads = base_constraint_cache_info()
    assert after_roads["misses"] == after_landuse["misses"] + 2
    assert after_roads["hits"] == after_landuse["hits"] + 1
    assert road_context.water_buffer is landuse_context.water_buffer
    assert np.array_equal(
        road_context.highway_buffer,
        highway_building_buffer(road_segments, loaded_kinds, SHAPE, 3.0),
    )


def test_farmland_buffer_follows_the_file_and_not_the_exclusion(tmp_path, monkeypatch):
    hard = np.zeros(SHAPE, dtype=np.float32)
    walkable, blocked = access_inputs(tmp_path, hard)
    assert blocked is None and np.array_equal(walkable, np.ones(SHAPE, dtype=bool))

    mask = np.zeros(SHAPE, dtype=bool)
    mask[10, 10] = True
    np.save(mask_path(tmp_path), mask)
    monkeypatch.setattr("experiments.protected_farmland.access_road_width_m", lambda: 4.0)
    _, first = access_inputs(tmp_path, hard)
    _, second = access_inputs(tmp_path, hard)
    assert first is second
    assert np.array_equal(first, dilate_mask(mask, 4.0))
    other = hard.copy()
    other[0, 0] = 1
    walk_other, blocked_other = access_inputs(tmp_path, other)
    assert blocked_other is first
    assert walk_other[0, 0] == 0 and walk_other[10, 10] == 0

    monkeypatch.setattr("experiments.protected_farmland.access_road_width_m", lambda: 0.0)
    _, zero_width = access_inputs(tmp_path, hard)
    assert np.array_equal(zero_width, mask)
    assert zero_width is not first

    replaced = mask.copy()
    replaced[10, 10] = False
    replaced[2, 2] = True
    np.save(mask_path(tmp_path), replaced)
    monkeypatch.setattr("experiments.protected_farmland.access_road_width_m", lambda: 4.0)
    _, updated = access_inputs(tmp_path, hard)
    assert np.array_equal(updated, dilate_mask(replaced, 4.0))
    assert not np.array_equal(updated, first)

    mask_path(tmp_path).unlink()
    _, gone = access_inputs(tmp_path, hard)
    assert gone is None


def test_two_scenes_stay_distinct_and_a_full_cache_evicts_the_oldest(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    landuse = _base_landuse()
    segments, kinds = _roads()
    _, left_sources = _scene(left, landuse, segments, kinds)
    other = landuse.copy()
    other[3, 3] = 5
    _, right_sources = _scene(right, other, segments, kinds)
    left_landuse = np.load(left / "landuse_1m.npy")
    right_landuse = np.load(right / "landuse_1m.npy")
    left_mask = cached_water_buffer(left_sources, 2.0, left_landuse)
    right_mask = cached_water_buffer(right_sources, 2.0, right_landuse)
    assert cached_water_buffer(left_sources, 2.0, left_landuse) is left_mask
    assert cached_water_buffer(right_sources, 2.0, right_landuse) is right_mask
    assert not np.array_equal(left_mask, right_mask)

    cache = BaseConstraintCache(max_bytes=300, max_entries=8)
    first = cache.get_or_compute(("a",), lambda: np.ones((16, 16), dtype=bool))
    cache.get_or_compute(("b",), lambda: np.zeros((16, 16), dtype=bool))
    assert cache.info()["entries"] == 1
    calls = {"n": 0}

    def recompute():
        calls["n"] += 1
        return np.ones((16, 16), dtype=bool)

    restored = cache.get_or_compute(("a",), recompute)
    assert calls["n"] == 1
    assert np.array_equal(restored, first)
    assert restored is not first


def test_one_cache_key_is_computed_once_when_callers_overlap():
    cache = BaseConstraintCache()
    entered = threading.Barrier(4)
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        threading.Event().wait(0.2)
        return np.array([[True, False], [False, True]])

    results = []

    def worker():
        entered.wait()
        results.append(cache.get_or_compute(("shared",), compute))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
    assert calls["n"] == 1
    assert all(mask is results[0] for mask in results)


def test_haul_field_ignores_building_setback_and_matches_the_uncached_context(tmp_path):
    landuse = np.zeros(SHAPE, dtype=np.uint8)
    landuse[12, :] = 3
    segments = np.array([[0.5, 12.5, SHAPE[1] - 0.5, 12.5]], dtype=np.float64)
    kinds = np.array([0], dtype=np.int8)
    _, sources = _scene(tmp_path, landuse, segments, kinds)
    loaded_landuse, loaded_segments, loaded_kinds = _load_scene(tmp_path)
    direct = context_from_arrays(
        _arrays(loaded_landuse, loaded_segments, loaded_kinds), torch.device("cpu"),
        road_setback_m=3, water_setback_m=0, highway_setback_m=0,
    )
    cached = context_from_arrays(
        _arrays(loaded_landuse, loaded_segments, loaded_kinds), torch.device("cpu"),
        road_setback_m=3, water_setback_m=0, highway_setback_m=0, sources=sources,
    )
    assert cached.road_buffer.any()
    assert np.array_equal(cached.obstacle_mask == 0, direct.obstacle_mask == 0)
    assert not np.array_equal(cached.obstacle_mask == 0, cached.road_buffer)
    sites = np.array([[4.5, 4.5]], dtype=np.float64)
    direct_field = build_haul_field(
        direct.dem, direct.obstacle_mask == 0, direct.road_segments, segment_kinds=direct.road_segment_kinds,
    )
    cached_field = build_haul_field(
        cached.dem, cached.obstacle_mask == 0, cached.road_segments, segment_kinds=cached.road_segment_kinds,
    )
    direct_values, direct_blocked = query_exact(direct_field, sites)
    cached_values, cached_blocked = query_exact(cached_field, sites)
    assert np.array_equal(direct_values, cached_values)
    assert np.array_equal(direct_blocked, cached_blocked)

    farmland = np.zeros(SHAPE, dtype=bool)
    farmland[4, 4] = True
    np.save(mask_path(tmp_path), farmland)
    _, blocked = access_inputs(tmp_path, cached.obstacle_mask)
    _, blocked_again = access_inputs(tmp_path, direct.obstacle_mask)
    assert blocked is blocked_again
    from experiments.protected_farmland import access_road_width_m
    assert np.array_equal(blocked, dilate_mask(farmland, access_road_width_m()))
    assert not np.array_equal(blocked, cached.road_buffer)
