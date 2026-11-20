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
from experiments.case_artifacts import number_routing_routes, write_routing_case
from experiments.protected_farmland import MASK_NAME as FARMLAND_MASK, META_NAME as FARMLAND_METADATA
from experiments.routing_output import json_safe
from experiments.scene_lock import scene_write_lock
from experiments.scene_store import ensure_scene_readable, scene_directory, scenes_root
from experiments.scene_version import scene_data_version
from modeling.routing.evaluator import RouteEvaluator
from modeling.routing.geometry import turn_angles
from modeling.routing.types import OBJECTIVE_NAMES, Route, RoutingFrame


def read_workspace_routes(source: Path) -> dict:
    """Reuse the result panel's recorded selection, rather than run a second deduplication."""
    original = json.loads(source.read_text(encoding="utf-8"))
    if source.name == "filter_snapshot.json":
        # File → Save experiment keeps its existing re-evaluation semantics, including gray candidates.
        return {**original, "frame": original["context"]["frame"], "routes": [
            {**item["data"], "number": item["original_number"]} for item in original["candidates"]]}
    original["routes"] = number_routing_routes(original["routes"])
    manifest_path = source.parent / "routing_portfolio_manifest.json"
    if not manifest_path.is_file():
        return original
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") == "legacy_published_only":
        return original
    ids = manifest.get("filtered_route_ids")
    if manifest.get("status") != "complete" or not isinstance(ids, list):
        raise ValueError("来源实验没有完整的筛选方案清单，无法另存；请重新选线。")
    if not ids:
        raise ValueError("筛选方案为空，没有可保存的线路。")
    if any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids) or manifest.get("filtered_count") != len(ids):
        raise ValueError("筛选方案清单的编号或数量无效。")
    complete = json.loads((source.parent / "routes_all_pareto.json").read_text(encoding="utf-8"))
    if complete.get("scene_name") != original.get("scene_name") or complete.get("frame") != original.get("frame"):
        raise ValueError("筛选方案与来源线路的场景或坐标网格不一致。")
    by_id = {route["id"]: route for route in number_routing_routes(complete["routes"])}
    if len(by_id) != len(complete["routes"]) or any(key not in by_id for key in ids):
        raise ValueError("筛选方案清单引用的线路缺失或重复。")
    return {**complete, "routes": [by_id[key] for key in ids]}


def save_routing_workspace(output_root: Path, name: str, task, source: Path) -> tuple[str, int]:
    original = read_workspace_routes(source)
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
            saved.append({"number": item["number"], "id": route_id, "objectives": dict(zip(OBJECTIVE_NAMES, evaluation.objectives)),
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
            summary = {"schema_version": 1, "is_case": True, "algorithm": "routing_workspace", "problem_type": "routing",
                "display_name": name, "scene_name": task.scene_name, "source_experiment_id": source.parent.name,
                "saved_at": datetime.now(timezone.utc).isoformat(), "data_version": metadata["data_version"],
                "objective_names": OBJECTIVE_NAMES, "n_solutions": len(saved), "n_feasible": sum(e.is_feasible for e in evaluations),
                "n_pareto": len(front), "clearance_status": "净空未校核"}
            write_routing_case(temporary, json_safe(saved), json_safe({**task.model_dump(), "experiment_name": name,
                "start_local": problem.start, "end_local": problem.end}), json_safe(asdict(frame)), json_safe(metadata), json_safe(summary))
            temporary.rename(output_root / experiment_id)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return experiment_id, len(saved)
