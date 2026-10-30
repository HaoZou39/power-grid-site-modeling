import numpy as np

from experiments.launch_routing_run import problem_from_snapshot, snapshot_routing_scene
from experiments.routing_context_cache import RoutingRasterCache
from test_routing_context import make_problem
from test_routing_output import routing_task


def test_cache_has_one_entry_honors_budget_and_readonly_data():
    cache = RoutingRasterCache(); calls = []
    def build():
        calls.append(1)
        return make_problem()
    first, hit, _ = cache.get("a", 1024**2, build);assert not hit
    second, hit, _ = cache.get("a", 1024**2, build);assert hit and first is second
    assert not second["tower_blocked"].flags.writeable
    cache.get("b", 1024**2, build);cache.get("a", 1024**2, build)
    assert len(calls) == 3
    cache.get("a", 0, build);_, hit, _ = cache.get("a", 1024**2, build)
    assert not hit


def test_cache_reuses_rasters_but_not_endpoints_or_polygons(tmp_path, monkeypatch):
    task, _ = routing_task(tmp_path, monkeypatch)
    snapshot = tmp_path / "snapshot"
    metadata = snapshot_routing_scene(task.scene_name, snapshot)
    first_info, second_info = {}, {}
    first = problem_from_snapshot(snapshot, task, metadata, cache_report=first_info)
    end = first.frame.to_wgs84([25, 20])
    changed = task.model_copy(update={"end": task.end.model_copy(update={"lng": end[0], "lat": end[1]}),
        "no_cross_zones": [[(10., 10.), (15., 10.), (15., 15.)]]})
    second = problem_from_snapshot(snapshot, changed, metadata, cache_report=second_info)
    assert second_info["hit"] and second.tower_blocked is first.tower_blocked
    assert not np.array_equal(second.end, first.end)
    assert second.no_cross_zones and not first.no_cross_zones
    third_info = {}
    problem_from_snapshot(snapshot, task.model_copy(update={"road_setback_m": 2.}), metadata, cache_report=third_info)
    assert not third_info["hit"]
    fourth_info = {}
    modified = {**metadata, "input_hashes": {**metadata["input_hashes"], "landuse_1m.npy": "new-content"}}
    problem_from_snapshot(snapshot, task, modified, cache_report=fourth_info)
    assert not fourth_info["hit"]
    disabled = task.model_copy(update={"algorithm": task.algorithm.model_copy(update={"context_cache_mib": 0})})
    info = {}
    problem_from_snapshot(snapshot, disabled, metadata, cache_report=info)
    assert not info["hit"]
