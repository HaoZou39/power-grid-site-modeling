"""Save the retained workspace poses as a new, independently named experiment."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from experiments.haul_field_cache import scene_source_signature
from experiments.launch_site_run import evaluate_form_poses
from experiments.output_writer import write_csv
from experiments.scene_store import ensure_scene_readable, scene_directory, scenes_root


def save_workspace(
    output_root: Path,
    name: str,
    form: dict[str, Any],
    poses: list[dict[str, Any]],
    source_experiment_id: str | None,
) -> str:
    scene = scene_directory(scenes_root(None), form["scene_name"])
    ensure_scene_readable(scene)
    signature = scene_source_signature(scene, uses_landuse=True)
    # Hidden poses may still have old display metrics. Evaluate the captured set together.
    measured = evaluate_form_poses(form, [(p["x"], p["y"], p["theta"]) for p in poses])
    if len(measured) != len(poses):
        raise ValueError("评价返回的方案数量不一致，未保存。")
    if signature != scene_source_signature(scene, uses_landuse=True):
        raise ValueError("评价期间场景数据已变化，请重新保存。")
    solutions = [
        {**row, **pose, "run_id": pose["id"],
         "is_pareto": row["is_feasible"] and not pose["manual"] and pose["pareto_layer"] == 1}
        for pose, row in zip(poses, measured)
    ]
    pareto = [row for row in solutions if row["is_pareto"]]
    summary = {
        "algorithm": "workspace_snapshot", "display_name": name,
        "scene_name": form["scene_name"], "source_experiment_id": source_experiment_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "n_runs": len(solutions), "n_feasible": sum(row["is_feasible"] for row in solutions),
        "n_pareto": len(pareto),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    experiment_id = f"saved-{uuid4().hex}"
    temporary = Path(tempfile.mkdtemp(prefix=".saving-", dir=output_root))
    try:
        columns = [*measured[0], "id", "manual", "pareto_layer", "derived_from", "is_pareto"]
        write_csv(temporary / "solutions.csv", solutions, columns)
        write_csv(temporary / "pareto_solutions.csv", pareto, columns)
        documents = {
            "site_form_snapshot.json": form,
            "resolved_config.json": {"scene_name": form["scene_name"], "modeling": {
                "rect_w_m": form["rect_w_m"], "rect_h_m": form["rect_h_m"],
            }},
            "data_metadata.json": json.loads((scene / "data_metadata.json").read_text(encoding="utf-8")),
            "workspace_solutions.json": {"format": "workspace-solutions-v1", "solutions": solutions},
            "run_summary.json": summary,
        }
        for filename, value in documents.items():
            (temporary / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        # The catalog sees the result only after every artifact is complete.
        temporary.rename(output_root / experiment_id)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return experiment_id
