"""Write one Cangnan E1 preview case from the saved strict front.

It does not rerun the search and does not modify the historical task directory.
Bend stored in the map file stays in radians. A5 sees degrees.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np

from algorithms.routing.three_mode import build_three_mode
from experiments.routing_three_mode_output import write_three_mode_documents
from modeling.routing.geometry import turn_angles

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/苍南测试_起点120.194944,27.504922_终点120.194666,27.497567_1794548514053"
FRONT = ROOT / "diagnostics/CANGNAN_EPSILON_S1_S2_COMPARISON/s2_runs/E1/exact_pareto.npz"
DISTANCE = ROOT / "diagnostics/CANGNAN_ENGINEERING_PREFERENCE_PORTFOLIO/hausdorff_E1.npy"
TARGET = ROOT / "outputs/routing-three-mode-preview-cangnan-e1"


def _route(route_id: str, objectives: np.ndarray, line: np.ndarray) -> dict:
    spans = []
    for start, stop in zip(line[:-1], line[1:]):
        spans.append({"horizontal_m": float(np.linalg.norm(stop - start)), "length_3d_m": None, "crossing_3d_m": None})
    points = []
    for index, point in enumerate(line):
        role = "start" if index == 0 else "end" if index == len(line) - 1 else "tower"
        points.append({"x": float(point[0]), "y": float(point[1]), "z": None, "role": role})
    radians = float(np.radians(objectives[2]))
    return {
        "id": route_id,
        "objectives": {
            "tower_count": float(objectives[0]),
            "length_3d_m": float(objectives[1]),
            "bend_sum_rad": radians,
            "crossing_3d_m": float(objectives[3]),
        },
        "is_feasible": True,
        "is_pareto": True,
        "violations": {},
        "points": points,
        "spans": spans,
        "turns_deg": np.degrees(turn_angles(line)).tolist(),
        "tower_slopes_deg": [None] * max(len(line) - 2, 0),
    }


def main() -> None:
    published = json.loads((SOURCE / "routes.json").read_text(encoding="utf-8"))
    archive = np.load(FRONT)
    objectives = archive["objectives"].astype(float)
    degree_objectives = objectives.copy()
    degree_objectives[:, 2] = np.degrees(objectives[:, 2])
    offsets = archive["offsets"]
    lines = [archive["xy"][int(start):int(stop)].astype(float) for start, stop in zip(offsets[:-1], offsets[1:])]
    # These ids are the archive route_index values, not the published route-000001 ids.
    route_ids = [f"E1-{int(index)}" for index in archive["route_index"]]
    distance = np.load(DISTANCE)
    portfolio = build_three_mode(route_ids, degree_objectives, lines, distance=distance)
    geometries = [_route(route_id, degree_objectives[index], lines[index]) for index, route_id in enumerate(route_ids)]
    by_id = {item["id"]: item for item in geometries}
    recommended_ids = [item["route_id"] for item in portfolio["recommendations"]]
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)
    header = {key: published[key] for key in ("schema_version", "problem_type", "scene_name", "frame", "data_version")}
    write_three_mode_documents(TARGET, header, geometries, portfolio, {
        "source_revision": "saved-front",
        "retention": "这是手动预览案例，不进入自动结果的最近 2 次清理。",
    })
    published_routes = [by_id[route_id] for route_id in recommended_ids]
    (TARGET / "routes.json").write_text(
        json.dumps({**header, "routes": published_routes}, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    shutil.copyfile(SOURCE / "resolved_config.json", TARGET / "resolved_config.json")
    (TARGET / "run_summary.json").write_text(json.dumps({
        "schema_version": 1,
        "problem_type": "routing",
        "algorithm": "routing_nsga2",
        "scene_name": header["scene_name"],
        "display_name": "三档选线 苍南 E1",
        "is_case": True,
        "result_origin": "preview",
        "n_pareto": portfolio["counts"]["all_pareto"],
        "n_solutions": len(published_routes),
        "three_mode": True,
        "three_mode_counts": portfolio["counts"],
        "clearance_status": "净空未校核",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"directory": TARGET.name, **portfolio["counts"], "recommended": recommended_ids}, ensure_ascii=False))


if __name__ == "__main__":
    main()
