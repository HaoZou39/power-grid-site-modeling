import numpy as np
import pytest

from experiments.tune_routing import RATIO_FLOOR, candidate_config, merge, sample_endpoints, score


def run(candidate, scene_class, front, draw=0, seed=1):
    return {"candidate": candidate, "class": scene_class, "draw": draw, "seed": seed, "front": front}


def test_score_ranks_by_the_worst_class_ratio_and_eliminates_empty_fronts():
    a = [[2., 10., 0., 0.]]
    b = [[3., 12., 0., 1.]]
    runs = [run("x", "short", a), run("y", "short", b), run("z", "short", a),
            run("x", "long", b), run("y", "long", a), run("z", "long", []),
            run("x", "none", []), run("y", "none", []), run("z", "none", [])]
    result = score(runs)
    assert result["eliminated"] == ["z"]
    assert result["skipped_instances"] == [{"class": "none", "draw": 0}]
    assert set(result["candidates"]) == {"x", "y"}
    worst = result["candidates"]["x"]["worst_ratio"]
    assert worst == pytest.approx((result["candidates"]["x"]["mean_igd_plus"]["long"] + RATIO_FLOOR) / RATIO_FLOOR)
    assert result["candidates"]["x"]["ratios"]["short"] == pytest.approx(1.0)


def test_candidate_overrides_merge_nested_fields_and_reject_unknown_names():
    config = candidate_config({"pilot": {"core": {"local_search_interval": 9}, "local_budget_factor": 4}}, 7)
    assert config.pilot.core.local_search_interval == 9 and config.pilot.local_budget_factor == 4 and config.seed == 7
    with pytest.raises(ValueError):
        merge({"a": 1}, {"b": 2})


def test_endpoint_sampling_is_deterministic_and_prefers_the_requested_obstacle_level():
    landuse = np.zeros((400, 400), dtype=np.int32)
    landuse[:, 180:220] = 2
    low = sample_endpoints(landuse, (100, 250), "low", 3)
    high = sample_endpoints(landuse, (100, 250), "high", 3)
    again = sample_endpoints(landuse, (100, 250), "low", 3)
    assert np.array_equal(low[0], again[0]) and 100 <= low[2] <= 250
    assert low[3] <= high[3]
