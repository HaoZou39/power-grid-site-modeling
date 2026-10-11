"""CMA-ES experiment entry point: config -> context -> search -> outputs."""

from __future__ import annotations

from pathlib import Path

from algorithms.common.pareto import extract_feasible_pareto_front
from config.project_config import load_project_config, save_config, validate_cuda_device
from data_tools.io_utils import write_json
from experiments.output_writer import write_standard_outputs
from experiments.problem_context import build_site_problem_context

from .cma_es import run_cma_es_search


def main(config_path: str | Path = "config/default_config.json", output_dir: str | Path = "outputs/cmaes_region") -> None:
    """Run one configured CMA-ES experiment and write its standard artifacts."""
    config = load_project_config(config_path)
    device = validate_cuda_device(config.modeling.device)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    save_config(config, out / "resolved_config.json")
    problem, metadata = build_site_problem_context(config, out, device)
    write_json(out / "data_metadata.json", metadata)
    result = run_cma_es_search(problem, config.modeling, config.common, config.cma_es)
    pareto_records = extract_feasible_pareto_front(result.solutions, ("dem_soft", "road_distance", "demand_distance"))
    write_standard_outputs(
        config,
        out,
        problem,
        result.normalization,
        result.solutions,
        pareto_records,
        run_records=result.runs,
        summary_extra={"n_runs": len(result.runs)},
    )
    print(f"CMA-ES outputs: {out}")


if __name__ == "__main__":
    main()
