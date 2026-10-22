"""Multi-start Adam experiment entry point."""

from __future__ import annotations

from pathlib import Path

from algorithms.common.pareto import extract_feasible_pareto_front
from config.project_config import load_project_config, save_config, validate_cuda_device
from data_tools.io_utils import write_json
from experiments.output_writer import write_standard_outputs
from experiments.problem_context import build_site_problem_context

from .multistart_adam import run_multistart_adam_search


def main(config_path: str | Path = "config/default_config.json", output_dir: str | Path = "outputs/multistart_adam_region") -> None:
    """Run the configured search and write the common experiment artifacts."""
    config = load_project_config(config_path)
    device = validate_cuda_device(config.modeling.device)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    save_config(config, out / "resolved_config.json")
    problem, metadata = build_site_problem_context(config, out, device)
    write_json(out / "data_metadata.json", metadata)
    result = run_multistart_adam_search(problem, config.modeling, config.common, config.multistart_adam)
    pareto_records = extract_feasible_pareto_front(result.solutions, ("dem_soft", "road_distance", "demand_distance"))
    write_standard_outputs(
        config,
        out,
        problem,
        result.normalization,
        result.solutions,
        pareto_records,
        run_records=result.runs,
        objective_names=("dem_soft", "road_distance", "demand_distance"),
        summary_extra={
            "n_preferences": len(result.runs),
            "n_starts_per_preference": int(config.multistart_adam.starts_per_weight),
        },
    )
    print(f"Multi-start Adam outputs: {out}")


if __name__ == "__main__":
    main()
