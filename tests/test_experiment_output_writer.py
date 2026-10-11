from __future__ import annotations

import json

import numpy as np
import torch

from config.project_config import load_project_config
from experiments.output_writer import write_standard_outputs
from modeling.context import SiteProblemContext


def _context() -> SiteProblemContext:
    dem = np.arange(16, dtype=np.float32).reshape(4, 4)
    obstacle = np.zeros((4, 4), dtype=np.float32)
    roads = np.array([[0.0, 0.0, 3.0, 3.0]], dtype=np.float32)
    points = np.array([[1.0, 1.0], [2.0, 2.0]], dtype=np.float32)
    return SiteProblemContext(
        dem=dem,
        obstacle_mask=obstacle,
        road_segments=roads,
        dem_tensor=torch.as_tensor(dem)[None, None],
        obstacle_tensor=torch.as_tensor(obstacle)[None, None],
        road_segments_tensor=torch.as_tensor(roads),
        road_voronoi_tensor=torch.zeros((4, 4), dtype=torch.long),
        demand_points=points,
        demand_weights=None,
        demand_points_tensor=torch.as_tensor(points),
        demand_weights_tensor=None,
        device=torch.device("cpu"),
    )


def _record(run_id: int, feasible: bool = True) -> dict[str, object]:
    return {
        "run_id": run_id,
        "x": 1.0,
        "y": 1.0,
        "theta": 0.0,
        "scalar": 1.0,
        "dem_soft": 1.0,
        "road_distance": 2.0,
        "demand_distance": 3.0,
        "is_feasible": feasible,
    }


def test_standard_output_writer_keeps_common_files_consistent(tmp_path) -> None:
    config = load_project_config("config/default_config.json")
    record = _record(1)

    write_standard_outputs(
        config,
        tmp_path,
        _context(),
        {"dem_ideal": 0.0},
        [record],
        [record],
        run_records=[{"run_id": 1, "iterations": 2}],
        summary_extra={"algorithm": "test"},
    )

    summary = json.loads((tmp_path / "run_summary.json").read_text(encoding="utf-8"))
    assert summary == {
        "algorithm": "test",
        "n_solutions": 1,
        "n_feasible": 1,
        "n_pareto": 1,
        "no_feasible_solution": False,
    }
    assert (tmp_path / "runs.csv").is_file()
    assert (tmp_path / "all_candidates_points_map.png").is_file()
    assert (tmp_path / "pareto_3d_interactive.html").is_file()
