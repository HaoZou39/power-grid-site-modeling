"""Re-evaluate retained routes and publish an independent workspace case."""

import hashlib
import json
import shutil
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np

from algorithms.common.pareto import feasible_front_indices
from experiments.launch_routing_run import INPUT_FILES, problem_from_snapshot
from experiments.output_writer import write_csv
from experiments.protected_farmland import MASK_NAME as FARMLAND_MASK, META_NAME as FARMLAND_METADATA
from experiments.routing_output import json_safe, write_routing_json
from experiments.scene_lock import scene_write_lock
from experiments.scene_store import ensure_scene_readable, scene_directory, scenes_root
from experiments.scene_version import scene_data_version
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.geometry import turn_angles
from modeling.routing.types import OBJECTIVE_NAMES, Route, RoutingFrame


def save_routing_workspace(output_root: Path, name: str, task, source: Path) -> tuple[str, int]:
    original = json.loads(source.read_text(encoding="utf-8"))
    if original.get("problem_type") != "routing" or original.get("scene_name") != task.scene_name:
        raise ValueError("线路结果与当前场景不一致。")
    routes = original.get("routes")
    if not isinstance(routes, list) or not routes:
        raise ValueError("没有可保存的线路。")
    scene = scene_directory(scenes_root(), task.scene_name)
    with scene_write_lock(task.scene_name, scene.parent, blocking=True):
        ensure_scene_readable(scene)
        metadata = json.loads((scene / "data_metadata.json").read_text(encoding="utf-8"))
        if (metadata.get("protected_farmland") or (scene / FARMLAND_METADATA).exists()) and not (scene / FARMLAND_MASK).is_file():
            raise FileNotFoundError(scene / FARMLAND_MASK)
        metadata["data_version"] = scene_data_version(scene, metadata)
        names = [*INPUT_FILES, *([FARMLAND_MASK] if (scene / FARMLAND_MASK).is_file() else []),
                 *([FARMLAND_METADATA] if (scene / FARMLAND_METADATA).is_file() else [])]
        metadata["input_hashes"] = {}
        for filename in names:
            with (scene / filename).open("rb") as stream:
                metadata["input_hashes"][filename] = hashlib.file_digest(stream, "sha256").hexdigest()
        source_metadata = source.parent / "data_metadata.json"
        metadata.pop("source_input_hashes", None)
        if source_metadata.is_file():
            metadata["source_input_hashes"] = json.loads(source_metadata.read_text(encoding="utf-8")).get("input_hashes", {})
        frame = RoutingFrame.from_metadata(metadata)
        if json_safe(asdict(frame)) != original.get("frame"):
            raise ValueError("线路结果与当前场景的坐标网格不一致。")
        # Do not cache mutable live-scene inputs; hashes still describe this evaluation.
        problem = problem_from_snapshot(scene, task, {key: value for key, value in metadata.items() if key != "input_hashes"})
        evaluator = RouteEvaluator(problem)
        saved, evaluations, seen = [], [], set()
        for item in routes:
            route_id, points = item.get("id"), item.get("points")
            if not isinstance(route_id, str) or not route_id or route_id in seen or not isinstance(points, list) or len(points) < 2:
                raise ValueError("线路编号或接点无效。")
            seen.add(route_id)
            coords = np.asarray([[p["x"], p["y"]] for p in points], dtype=float)
            if not np.isfinite(coords).all() or not np.allclose(coords[[0, -1]], [problem.start, problem.end], rtol=0, atol=1e-5):
                raise ValueError("线路起终点与当前设置不一致，请先重新选线。")
            route = Route(coords[1:-1])
            evaluation = evaluator.evaluate(route, report=True)
            evaluations.append(evaluation)
            saved.append({"id": route_id, "objectives": dict(zip(OBJECTIVE_NAMES, evaluation.objectives)),
                "is_feasible": evaluation.is_feasible, "is_pareto": False, "violations": evaluation.violations,
                "points": [{"x": p[0], "y": p[1], "z": z, "role": "start" if i == 0 else "end" if i == len(coords)-1 else "tower"}
                           for i, (p, z) in enumerate(zip(coords, evaluation.elevations))],
                "spans": evaluation.spans, "turns_deg": np.degrees(turn_angles(coords)),
                "tower_slopes_deg": evaluation.tower_slopes_deg})
        front = feasible_front_indices(np.asarray([e.objectives for e in evaluations]), np.asarray([e.is_feasible for e in evaluations]))
        for index in front:
            saved[index]["is_pareto"] = True
        output_root.mkdir(parents=True, exist_ok=True)
        experiment_id = f"saved-{uuid4().hex}"
        temporary = Path(tempfile.mkdtemp(prefix=".saving-", dir=output_root))
        try:
            rows = [json_safe({"route_id": r["id"], **r["objectives"], "is_feasible": r["is_feasible"],
                               "is_pareto": r["is_pareto"], **r["violations"]}) for r in saved]
            columns = list(rows[0])
            write_csv(temporary / "solutions.csv", rows, columns)
            write_csv(temporary / "pareto_solutions.csv", [row for row in rows if row["is_pareto"]], columns)
            write_routing_json(temporary / "routes.json", {"schema_version": 1, "problem_type": "routing", "scene_name": task.scene_name,
                "frame": asdict(frame), "data_version": metadata["data_version"], "routes": saved})
            write_routing_json(temporary / "resolved_config.json", {**task.model_dump(), "experiment_name": name,
                "start_local": problem.start, "end_local": problem.end})
            write_routing_json(temporary / "data_metadata.json", metadata)
            write_routing_json(temporary / "run_summary.json", {"schema_version": 1, "is_case": True, "algorithm": "routing_workspace", "problem_type": "routing",
                "display_name": name, "scene_name": task.scene_name, "source_experiment_id": source.parent.name,
                "saved_at": datetime.now(timezone.utc).isoformat(), "data_version": metadata["data_version"],
                "objective_names": OBJECTIVE_NAMES, "n_solutions": len(rows), "n_feasible": sum(e.is_feasible for e in evaluations),
                "n_pareto": len(front), "clearance_status": "净空未校核"})
            temporary.rename(output_root / experiment_id)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return experiment_id, len(saved)
