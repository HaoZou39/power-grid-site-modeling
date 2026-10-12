"""Adapters from experiment Pareto CSV files to preference candidates."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Sequence

from agent.preference.models import Candidate


def load_pareto_csv(path: str | Path, objective_names: Sequence[str]) -> list[Candidate]:
    csv_path = Path(path)
    if not csv_path.is_file():
        raise FileNotFoundError(csv_path)
    candidates: list[Candidate] = []
    with csv_path.open("r", newline="", encoding="utf-8") as file:
        rows = csv.DictReader(file)
        if not rows.fieldnames:
            raise ValueError("Pareto CSV has no header")
        names = tuple(objective_names)
        missing = [name for name in names if name not in rows.fieldnames]
        if missing:
            raise ValueError(f"Pareto CSV is missing objectives: {', '.join(missing)}")
        for index, row in enumerate(rows):
            if str(row.get("is_feasible", "true")).strip().lower() in {"0", "false", "no"}:
                continue
            candidate_id = _first_value(row, "candidate_id", "id", "solution_id", "run_id") or f"pareto-{index + 1}"
            objectives = {name: _float_field(row, name) for name in names}
            variables = {
                key: _float_field(row, key)
                for key in ("x", "y", "theta", "center_x", "center_y")
                if row.get(key, "") not in (None, "")
            }
            candidates.append(Candidate(candidate_id, objectives, variables, dict(row)))
    if not candidates:
        raise ValueError("Pareto CSV contains no feasible candidates")
    return candidates


def _first_value(row: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = row.get(name)
        if value:
            return str(value)
    return None


def _float_field(row: dict[str, str], name: str) -> float:
    try:
        return float(row[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Pareto CSV field {name!r} is not numeric") from exc
