"""VAE-like multi-head experiment entry point and checkpoint policy."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import csv
from typing import Any

import numpy as np
import torch

from algorithms.common.pareto import extract_feasible_pareto_front
from algorithms.common.scalarization import generate_weight_grid
from config.project_config import ProjectConfig, load_project_config, save_config, validate_cuda_device
from data_tools.io_utils import write_json
from experiments.output_writer import write_csv, write_standard_outputs
from experiments.problem_context import build_site_problem_context

from .vae_like_multihead import run_vae_like_multihead


def _read_validation_preferences(path: Path, device: torch.device) -> torch.Tensor:
    if not path.exists():
        raise FileNotFoundError(path)
    expected = ["preference_id", "weight_dem", "weight_road", "weight_demand"]
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != expected:
            raise ValueError(f"validation preference fields must be {expected}, got {reader.fieldnames}")
        rows = list(reader)
    if not rows:
        raise ValueError("validation preference CSV must contain at least one row")
    weights: list[list[float]] = []
    for expected_id, row in enumerate(rows):
        if int(row["preference_id"]) != expected_id:
            raise ValueError("validation preference_id must be consecutive from 0")
        weight = [float(row["weight_dem"]), float(row["weight_road"]), float(row["weight_demand"])]
        if not np.isfinite(weight).all() or np.any(np.asarray(weight) < 0) or not np.isclose(sum(weight), 1.0):
            raise ValueError(f"invalid validation preference at row {expected_id}")
        weights.append(weight)
    if len({tuple(weight) for weight in weights}) != len(weights):
        raise ValueError("validation preferences must not contain duplicate rows")
    return torch.as_tensor(weights, dtype=torch.float32, device=device)


def _write_outputs(
    config: ProjectConfig,
    out: Path,
    problem,
    result: Any,
    pareto_records: list[dict[str, Any]],
) -> None:
    history_fields = list(result.training_history[0].keys()) if result.training_history else ["step"]
    for row in result.training_history:
        for name in row:
            if name not in history_fields:
                history_fields.append(name)
    write_csv(out / "training_history.csv", result.training_history, history_fields)
    n_center = sum(record["inference_mode"] == "center" for record in result.solutions)
    n_sample = len(result.solutions) - n_center
    write_standard_outputs(
        config,
        out,
        problem,
        result.normalization,
        result.solutions,
        pareto_records,
        summary_extra={
            "n_preferences": len(generate_weight_grid(config.common.weight_grid_step, config.common.min_weight)),
            "n_heads": config.vae_like_multihead.n_heads,
            "n_center_candidates": n_center,
            "n_random_candidates": n_sample,
        },
    )


def main(
    config_path: str | Path = "config/default_config.json",
    output_dir: str | Path = "outputs/vae_like_multihead_region",
) -> None:
    """Train one configured model and write training plus standard artifacts."""
    try:
        from torch.utils.tensorboard import SummaryWriter
    except ImportError as exc:
        raise ImportError("tensorboard is required for VAE-like training") from exc

    config = load_project_config(config_path)
    device = validate_cuda_device(config.modeling.device)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    save_config(config, out / "resolved_config.json")
    problem, metadata = build_site_problem_context(config, out, device)
    write_json(out / "data_metadata.json", metadata)
    validation_preferences = _read_validation_preferences(
        config.vae_like_multihead.validation_preferences_path,
        device,
    )
    writer = SummaryWriter(log_dir=str(out / "tensorboard"))
    checkpoints = out / "checkpoints"
    checkpoints.mkdir(parents=True, exist_ok=True)

    def save_checkpoint(step: int, model: torch.nn.Module, optimizer: torch.optim.Optimizer) -> None:
        torch.save(
            {
                "step": step,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "algorithm_config": asdict(config.vae_like_multihead),
            },
            checkpoints / f"step_{step:06d}.pt",
        )

    try:
        result = run_vae_like_multihead(
            problem,
            config.modeling,
            config.common,
            config.vae_like_multihead,
            validation_preferences,
            writer=writer,
            checkpoint_callback=save_checkpoint,
        )
    finally:
        writer.close()
    torch.save(
        {
            "model_state_dict": result.model.state_dict(),
            "algorithm_config": asdict(config.vae_like_multihead),
            "normalization": result.normalization,
        },
        out / "model_final.pt",
    )
    pareto_records = extract_feasible_pareto_front(
        result.solutions,
        ("dem_soft", "road_distance", "demand_distance"),
    )
    _write_outputs(config, out, problem, result, pareto_records)
    print(f"VAE-like multi-head outputs: {out}")


if __name__ == "__main__":
    main()
