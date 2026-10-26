"""Write the stable on-disk contract consumed by the result browser."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping, Sequence

from config.project_config import ProjectConfig
from data_tools.io_utils import write_json
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
    """Write the shared CSV and run-summary outputs.

    Algorithm runners call this function instead of duplicating output naming
    or feasibility counting. Maps and the Pareto HTML stay out of this path.
    """

    del config, context, objective_names
    write_json(output_dir / "normalization.json", dict(normalization))
    if run_records is not None:
        run_fields = list(run_records[0].keys()) if run_records else ["run_id"]
        write_csv(output_dir / "runs.csv", run_records, run_fields)
    solution_fields = list(solution_records[0].keys()) if solution_records else ["run_id"]
    write_csv(output_dir / "solutions.csv", solution_records, solution_fields)
    write_csv(output_dir / "pareto_solutions.csv", pareto_records, solution_fields)

    feasible = [record for record in solution_records if bool(record["is_feasible"])]
    summary = {
        **(summary_extra or {}),
        "n_solutions": len(solution_records),
        "n_feasible": len(feasible),
        "n_pareto": len(pareto_records),
        "no_feasible_solution": len(feasible) == 0,
    }
    write_json(output_dir / "run_summary.json", summary)
