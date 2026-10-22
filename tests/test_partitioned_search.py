from __future__ import annotations

from dataclasses import dataclass
from threading import Barrier, Lock

import pytest

from experiments.partitioned_search import (
    plan_search_partitions,
    run_partitioned_guided_search,
)


def test_four_partitions_cover_the_safe_search_rectangle_without_gaps() -> None:
    partitions = plan_search_partitions((100, 100), 10.0, 10.0, 4, 12)
    assert len(partitions) == 4
    assert {(tile.row, tile.column) for tile in partitions} == {
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
    }
    top_left, top_right, bottom_left, bottom_right = partitions
    assert top_left.center_bounds_m[2] == pytest.approx(top_right.center_bounds_m[0])
    assert bottom_left.center_bounds_m[2] == pytest.approx(bottom_right.center_bounds_m[0])
    assert top_left.center_bounds_m[3] == pytest.approx(bottom_left.center_bounds_m[1])
    assert top_right.center_bounds_m[3] == pytest.approx(bottom_right.center_bounds_m[1])
    assert (top_left.center_bounds_m[0], top_left.center_bounds_m[1]) == pytest.approx(
        (bottom_left.center_bounds_m[0], top_right.center_bounds_m[1])
    )
    assert len({tile.seed for tile in partitions}) == 4
    assert partitions == plan_search_partitions((100, 100), 10.0, 10.0, 4, 12)


def test_six_partitions_adapt_to_a_tall_search_rectangle() -> None:
    partitions = plan_search_partitions((240, 100), 10.0, 10.0, 6, 3)
    assert len(partitions) == 6
    assert len({tile.row for tile in partitions}) == 3
    assert len({tile.column for tile in partitions}) == 2


@pytest.mark.parametrize(
    ("shape", "rect", "count", "bounds"),
    [
        ((100, 100), (10.0, 10.0), 5, None),
        ((100, 100), (10.0, 10.0), 4, (20.0, 20.0, 10.0, 90.0)),
        ((40, 40), (80.0, 80.0), 4, None),
        ((100, 100), (10.0, 10.0), 4, (-1.0, 10.0, 90.0, 90.0)),
    ],
)
def test_partition_plan_rejects_invalid_ranges(shape, rect, count, bounds) -> None:
    with pytest.raises(ValueError):
        plan_search_partitions(shape, rect[0], rect[1], count, 1, bounds)


def test_parallel_searches_share_global_evaluation_and_merge_once(monkeypatch) -> None:
    import algorithms.guided_search.search as guided_search
    from config.project_config import GuidedSearchConfig

    partitions = plan_search_partitions((100, 100), 10.0, 10.0, 4, 23)
    barrier = Barrier(2)
    active_lock = Lock()
    active = 0
    peak_active = 0
    received_bounds = []
    global_rescores = []

    @dataclass
    class TileResult:
        objective_names: tuple[str, ...]
        solutions: list[dict]

    def fake_run(_problem, _modeling, _config, _origin, reporter, *, field, pose_bounds):
        nonlocal active, peak_active
        with active_lock:
            active += 1
            peak_active = max(peak_active, active)
        barrier.wait(timeout=3)
        assert field is not None
        received_bounds.append(pose_bounds)
        reporter(0.85, "search", "done")
        with active_lock:
            active -= 1
        x_min, x_max, y_min, y_max = pose_bounds
        x = (x_min + x_max) / 2
        y = (y_min + y_max) / 2
        return TileResult(
            ("dem_soft",),
            [
                {
                    "x": x,
                    "y": y,
                    "theta": 0.0,
                    "raw_x": 0.1,
                    "raw_y": 0.2,
                    "raw_theta": 0.3,
                    "is_feasible": True,
                }
            ],
        )

    def fake_pose_records(_problem, _modeling, _origin, poses, *, field, raw):
        global_rescores.append((poses.copy(), field, raw.copy()))
        return [
            {
                "run_id": index,
                "x": float(pose[0]),
                "y": float(pose[1]),
                "theta": float(pose[2]),
                "raw_x": float(raw[index, 0]),
                "raw_y": float(raw[index, 1]),
                "raw_theta": float(raw[index, 2]),
                "is_feasible": True,
            }
            for index, pose in enumerate(poses)
        ]

    monkeypatch.setattr(guided_search, "run_guided_search", fake_run)
    monkeypatch.setattr(guided_search, "pose_records", fake_pose_records)
    shared_field = object()
    progress = []
    result = run_partitioned_guided_search(
        object(),
        object(),
        GuidedSearchConfig(seed=23),
        None,
        shared_field,
        partitions,
        2,
        lambda amount, stage, message: progress.append((amount, stage, message)),
    )

    assert peak_active == 2
    assert len(received_bounds) == 4
    assert len(result.solutions) == 4
    assert {record["partition_id"] for record in result.solutions} == {
        partition.partition_id for partition in partitions
    }
    assert len(global_rescores) == 1
    assert global_rescores[0][1] is shared_field
    assert len(global_rescores[0][0]) == 4
    assert progress[-1][0] <= 0.85
    assert len(result.partitions) == 4


def test_parallel_search_rejects_invalid_worker_count() -> None:
    from config.project_config import GuidedSearchConfig

    partitions = plan_search_partitions((100, 100), 10.0, 10.0, 4, 1)
    with pytest.raises(ValueError, match="max_parallel_tiles"):
        run_partitioned_guided_search(
            object(),
            object(),
            GuidedSearchConfig(seed=1),
            None,
            object(),
            partitions,
            5,
            lambda *_: None,
        )
