"""Shared document layout for full workspace cases and filtered versions."""

import json
from pathlib import Path

from experiments.output_writer import write_csv


def write_documents(directory: Path, documents: dict) -> None:
    for filename, value in documents.items():
        (directory / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def write_site_case(directory: Path, form: dict, solutions: list[dict], metadata: dict, summary: dict, columns=None) -> None:
    columns = columns or list(dict.fromkeys(key for row in solutions for key in row))
    write_csv(directory / "solutions.csv", solutions, columns)
    write_csv(directory / "pareto_solutions.csv", [row for row in solutions if row.get("is_pareto")], columns)
    write_documents(directory, {
        "site_form_snapshot.json": form,
        "resolved_config.json": {"scene_name": form["scene_name"], "modeling": {
            "rect_w_m": form["rect_w_m"], "rect_h_m": form["rect_h_m"],
        }},
        "data_metadata.json": metadata,
        "workspace_solutions.json": {"format": "workspace-solutions-v1", "solutions": solutions},
        "run_summary.json": summary,
    })


def number_routing_routes(routes: list[dict]) -> list[dict]:
    """Assign on the complete source once; subsets and reopened cases retain their numbers."""
    numbered = [{"number": route.get("number", index + 1), **route} for index, route in enumerate(routes)]
    numbers = [route["number"] for route in numbered]
    if any(type(number) is not int or number < 1 for number in numbers) or len(set(numbers)) != len(numbers):
        raise ValueError("线路显示编号无效或重复。")
    return numbered


def write_routing_case(directory: Path, routes: list[dict], task: dict, frame: dict, metadata: dict, summary: dict) -> None:
    routes = number_routing_routes(routes)
    rows = [{"number": route["number"], **route["objectives"], "is_feasible": route["is_feasible"],
             "is_pareto": route["is_pareto"], **route["violations"]} for route in routes]
    columns = list(dict.fromkeys(key for row in rows for key in row))
    write_csv(directory / "solutions.csv", rows, columns)
    write_csv(directory / "pareto_solutions.csv", [row for row in rows if row["is_pareto"]], columns)
    write_documents(directory, {
        "routes.json": {"schema_version": 1, "problem_type": "routing", "scene_name": task["scene_name"],
                        "frame": frame, "data_version": metadata["data_version"], "routes": routes},
        "resolved_config.json": task, "data_metadata.json": metadata, "run_summary.json": summary,
    })
