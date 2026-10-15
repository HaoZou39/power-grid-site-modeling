"""Write the stable on-disk contract consumed by the result browser."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping, Sequence

from config.project_config import ProjectConfig
from data_tools.io_utils import write_json
from figures import plot_candidate_map, write_pareto_3d_html
from modeling.context import SiteProblemContext


def write_csv(
    path: Path,
    records: Sequence[Mapping[str, Any]],
    fieldnames: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(fieldnames))
        writer.writeheader()
        for record in records:
            writer.writerow({name: record.get(name, "") for name in fieldnames})


def write_standard_outputs(
    config: ProjectConfig,
    output_dir: Path,
    context: SiteProblemContext,
    normalization: Mapping[str, Any],
    solution_records: Sequence[Mapping[str, Any]],
    pareto_records: Sequence[Mapping[str, Any]],
    *,
    run_records: Sequence[Mapping[str, Any]] | None = None,
    summary_extra: Mapping[str, Any] | None = None,
    objective_names: Sequence[str],
) -> None:
    """Write the shared CSV, map, Pareto, and run-summary outputs.

    Algorithm runners call this function instead of duplicating output naming,
    feasibility counting, or figure generation.
    """

    write_json(output_dir / "normalization.json", dict(normalization))
    if run_records is not None:
        run_fields = list(run_records[0].keys()) if run_records else ["run_id"]
        write_csv(output_dir / "runs.csv", run_records, run_fields)
    solution_fields = list(solution_records[0].keys()) if solution_records else ["run_id"]
    write_csv(output_dir / "solutions.csv", solution_records, solution_fields)
    write_csv(output_dir / "pareto_solutions.csv", pareto_records, solution_fields)

    # Only hard-feasible candidates are shown in the candidate maps. Soft
    # objective values remain in CSV for analysis and are never discarded.
    feasible = [record for record in solution_records if bool(record["is_feasible"])]
    maps = (
        ("all_candidates_points_map.png", feasible, "points", "Hard feasible candidates"),
        ("all_candidates_footprints_map.png", feasible, "footprints", "Hard feasible candidate footprints"),
        ("pareto_points_map.png", pareto_records, "points", "Pareto optimal candidates"),
        ("pareto_footprints_map.png", pareto_records, "footprints", "Pareto optimal footprints"),
    )
    for filename, records, mode, title in maps:
        plot_candidate_map(
            output_dir / filename,
            context.dem,
            context.obstacle_mask,
            context.road_segments,
            context.demand_points,
            records,
            config.modeling.rect_w_m,
            config.modeling.rect_h_m,
            mode,
            title,
        )
    if len(objective_names) < 3:
        raise ValueError("Pareto 3D figure needs at least three objectives")
    write_pareto_3d_html(
        output_dir / "pareto_3d_interactive.html",
        pareto_records,
        "Pareto 3D Front",
        axes=objective_names[:3],
        hover_fields=objective_names[3:],
    )
    summary = {
        **(summary_extra or {}),
        "n_solutions": len(solution_records),
        "n_feasible": len(feasible),
        "n_pareto": len(pareto_records),
        "no_feasible_solution": len(feasible) == 0,
    }
    write_json(output_dir / "run_summary.json", summary)
