from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import torch
from torch import nn
import torch.nn.functional as F

from algorithms.common.scalarization import (
    compute_normalization_from_samples,
    generate_weight_grid,
    scalarize_tchebycheff_torch_batched,
)
from algorithms.common.weiszfeld import compute_demand_ideal_value
from config.project_config import AlgorithmCommonConfig, ModelingConfig, VAELikeMultiheadConfig
from modeling.evaluator import compute_hard_constraints, evaluate_site_objectives
from modeling.pose import decode_raw_pose


@dataclass(frozen=True)
class VAELikeMultiheadProblem:
    dem: np.ndarray
    obstacle_mask: np.ndarray
    road_segments: np.ndarray
    dem_tensor: torch.Tensor
    obstacle_tensor: torch.Tensor
    road_segments_tensor: torch.Tensor
    road_voronoi_tensor: torch.Tensor
    demand_points: np.ndarray
    demand_weights: np.ndarray | None
    demand_points_tensor: torch.Tensor
    demand_weights_tensor: torch.Tensor | None
    device: torch.device


@dataclass(frozen=True)
class VAELikeMultiheadResult:
    normalization: dict[str, float | int]
    training_history: list[dict[str, Any]]
    solutions: list[dict[str, Any]]
    model: "VAELikeMultiheadModel"


class GaussianCandidateHead(nn.Module):
    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.mu_layer = nn.Linear(hidden_dim, 3)
        self.raw_std_layer = nn.Linear(hidden_dim, 3)

    def forward(self, hidden: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        return self.mu_layer(hidden), self.raw_std_layer(hidden)


class VAELikeMultiheadModel(nn.Module):
    def __init__(self, hidden_dim: int, backbone_depth: int, n_heads: int, sigma_eps: float) -> None:
        super().__init__()
        if hidden_dim <= 0 or backbone_depth <= 0 or n_heads <= 0 or sigma_eps <= 0:
            raise ValueError("hidden_dim, backbone_depth, n_heads, and sigma_eps must be positive")
        layers: list[nn.Module] = []
        input_dim = 3
        for _ in range(backbone_depth):
            layers.extend([nn.Linear(input_dim, hidden_dim), nn.SiLU()])
            input_dim = hidden_dim
        self.backbone = nn.Sequential(*layers)
        self.heads = nn.ModuleList(GaussianCandidateHead(hidden_dim) for _ in range(n_heads))
        self.n_heads = n_heads
        self.sigma_eps = float(sigma_eps)

    def forward(self, preferences: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        if preferences.ndim != 2 or preferences.shape[1] != 3:
            raise ValueError(f"preferences must have shape [B, 3], got {tuple(preferences.shape)}")
        hidden = self.backbone(preferences)
        outputs = [head(hidden) for head in self.heads]
        mu_raw = torch.stack([output[0] for output in outputs], dim=1)
        raw_std = torch.stack([output[1] for output in outputs], dim=1)
        sigma_raw = F.softplus(raw_std) + self.sigma_eps
        return mu_raw, sigma_raw


def _validate_config(config: VAELikeMultiheadConfig) -> None:
    if config.algorithm_name != "vae_like_multihead":
        raise ValueError(f"algorithm_name must be 'vae_like_multihead', got {config.algorithm_name!r}")
    positive_ints = (
        config.hidden_dim,
        config.backbone_depth,
        config.n_heads,
        config.samples_per_head,
        config.preference_batch_size,
        config.total_steps,
        config.eval_samples_per_head,
        config.checkpoint_interval,
        config.validation_interval,
    )
    if any(value <= 0 for value in positive_ints):
        raise ValueError("VAE-like integer configuration values must be positive")
    positive_floats = (
        config.learning_rate,
        config.sigma_eps,
        config.tau_start,
        config.tau_end,
        config.mu_tau_start,
        config.mu_tau_end,
        config.diversity_bandwidth,
        config.max_grad_norm,
    )
    if any(value <= 0 for value in positive_floats):
        raise ValueError("VAE-like positive float configuration values must be positive")
    non_negative = (
        config.mu_weight_start,
        config.mu_weight_end,
        config.entropy_weight_start,
        config.entropy_weight_end,
        config.diversity_weight,
    )
    if any(value < 0 for value in non_negative):
        raise ValueError("VAE-like loss weights must be non-negative")


def _linear(start: float, end: float, step: int, total_steps: int) -> float:
    if total_steps <= 1:
        return float(end)
    progress = step / float(total_steps - 1)
    return float(start + (end - start) * progress)


def _softmin(scores: torch.Tensor, temperature: float, dim: int) -> torch.Tensor:
    if temperature <= 0:
        raise ValueError("softmin temperature must be positive")
    return -temperature * torch.logsumexp(-scores / temperature, dim=dim)


def _diversity_loss(mu_raw: torch.Tensor, bandwidth: float) -> torch.Tensor:
    if mu_raw.shape[1] == 1:
        return mu_raw.new_zeros(())
    centers = torch.sigmoid(mu_raw)
    distances = torch.cdist(centers, centers, p=2).square()
    mask = torch.triu(torch.ones_like(distances, dtype=torch.bool), diagonal=1)
    return torch.exp(-distances[mask] / bandwidth).mean()


def _mean_pairwise_center_distance(mu_raw: torch.Tensor) -> torch.Tensor:
    if mu_raw.shape[1] == 1:
        return mu_raw.new_zeros(())
    distances = torch.cdist(torch.sigmoid(mu_raw), torch.sigmoid(mu_raw), p=2)
    mask = torch.triu(torch.ones_like(distances, dtype=torch.bool), diagonal=1)
    return distances[mask].mean()


def _evaluate_objectives(
    problem: VAELikeMultiheadProblem,
    modeling: ModelingConfig,
    raw_pose: torch.Tensor,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    pose = decode_raw_pose(raw_pose, problem.dem.shape, modeling.rect_w_m, modeling.rect_h_m)
    objectives = evaluate_site_objectives(
        problem.dem_tensor,
        problem.obstacle_tensor,
        problem.road_segments_tensor,
        problem.road_voronoi_tensor,
        problem.demand_points_tensor,
        problem.demand_weights_tensor,
        pose,
        modeling.rect_w_m,
        modeling.rect_h_m,
        modeling.soft_mask_sharpness,
    )
    return pose, objectives


def _scores(
    objectives: dict[str, torch.Tensor],
    weights: torch.Tensor,
    normalization: dict[str, float | int],
    common: AlgorithmCommonConfig,
) -> torch.Tensor:
    return scalarize_tchebycheff_torch_batched(
        objectives,
        weights,
        normalization,
        common.obstacle_penalty_scale,
        common.scalarization_eps,
    )


def _compute_normalization(
    problem: VAELikeMultiheadProblem,
    modeling: ModelingConfig,
    common: AlgorithmCommonConfig,
) -> dict[str, float | int]:
    rng = np.random.default_rng(common.normalization_seed)
    raw_np = rng.normal(size=(common.normalization_samples, 3)).astype(np.float32)
    raw = torch.as_tensor(raw_np, device=problem.device)
    with torch.no_grad():
        _, objectives_t = _evaluate_objectives(problem, modeling, raw)
    objectives = {name: value.cpu().numpy().astype(np.float64) for name, value in objectives_t.items()}
    demand_ideal = compute_demand_ideal_value(
        problem.demand_points,
        problem.demand_weights,
        common.weiszfeld_max_iters,
        common.weiszfeld_tol,
        common.weiszfeld_eps,
    )
    return compute_normalization_from_samples(
        objectives,
        demand_ideal,
        common.normalization_scale_percentile,
        common.normalization_samples,
        common.normalization_seed,
    )


def _validation_loss(
    model: VAELikeMultiheadModel,
    problem: VAELikeMultiheadProblem,
    modeling: ModelingConfig,
    common: AlgorithmCommonConfig,
    normalization: dict[str, float | int],
    preferences: torch.Tensor,
) -> float:
    model.eval()
    with torch.no_grad():
        mu_raw, _ = model(preferences)
        b, h, _ = mu_raw.shape
        _, objectives = _evaluate_objectives(problem, modeling, mu_raw.reshape(b * h, 3))
        weights = preferences[:, None, :].expand(b, h, 3).reshape(b * h, 3)
        scores = _scores(objectives, weights, normalization, common).reshape(b, h)
        value = scores.min(dim=1).values.mean().item()
    model.train()
    return float(value)


def _train(
    model: VAELikeMultiheadModel,
    problem: VAELikeMultiheadProblem,
    modeling: ModelingConfig,
    common: AlgorithmCommonConfig,
    config: VAELikeMultiheadConfig,
    normalization: dict[str, float | int],
    validation_preferences: torch.Tensor,
    writer: Any | None,
    checkpoint_callback: Callable[[int, nn.Module, torch.optim.Optimizer], None] | None,
) -> list[dict[str, Any]]:
    weight_grid = torch.as_tensor(
        np.stack(generate_weight_grid(common.weight_grid_step, common.min_weight)),
        dtype=torch.float32,
        device=problem.device,
    )
    generator = torch.Generator(device=problem.device)
    generator.manual_seed(config.training_seed)
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    history: list[dict[str, Any]] = []
    model.train()
    for step in range(config.total_steps):
        indices = torch.randint(
            weight_grid.shape[0],
            (config.preference_batch_size,),
            generator=generator,
            device=problem.device,
        )
        preferences = weight_grid[indices]
        tau = _linear(config.tau_start, config.tau_end, step, config.total_steps)
        mu_tau = _linear(config.mu_tau_start, config.mu_tau_end, step, config.total_steps)
        mu_weight = _linear(config.mu_weight_start, config.mu_weight_end, step, config.total_steps)
        entropy_weight = _linear(
            config.entropy_weight_start,
            config.entropy_weight_end,
            step,
            config.total_steps,
        )
        mu_raw, sigma_raw = model(preferences)
        b, h, _ = mu_raw.shape
        epsilon = torch.randn(
            (b, h, config.samples_per_head, 3),
            generator=generator,
            dtype=mu_raw.dtype,
            device=problem.device,
        )
        sample_raw = mu_raw[:, :, None, :] + sigma_raw[:, :, None, :] * epsilon
        flat_sample_raw = sample_raw.reshape(b * h * config.samples_per_head, 3)
        _, sample_objectives = _evaluate_objectives(problem, modeling, flat_sample_raw)
        sample_weights = (
            preferences[:, None, None, :]
            .expand(b, h, config.samples_per_head, 3)
            .reshape(b * h * config.samples_per_head, 3)
        )
        candidate_scores = _scores(sample_objectives, sample_weights, normalization, common).reshape(
            b, h * config.samples_per_head
        )
        candidate_loss = _softmin(candidate_scores, tau, dim=1).mean()
        _, mu_objectives = _evaluate_objectives(problem, modeling, mu_raw.reshape(b * h, 3))
        mu_weights = preferences[:, None, :].expand(b, h, 3).reshape(b * h, 3)
        mu_scores = _scores(mu_objectives, mu_weights, normalization, common).reshape(b, h)
        mu_loss = _softmin(mu_scores, mu_tau, dim=1).mean()
        entropy_loss = -torch.log(sigma_raw).mean()
        diversity_loss = _diversity_loss(mu_raw, config.diversity_bandwidth)
        total_loss = (
            candidate_loss
            + mu_weight * mu_loss
            + entropy_weight * entropy_loss
            + config.diversity_weight * diversity_loss
        )
        if not torch.isfinite(total_loss):
            raise ValueError(f"non-finite VAE-like loss at step {step}")
        optimizer.zero_grad()
        total_loss.backward()
        grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), config.max_grad_norm)
        if not torch.isfinite(grad_norm):
            raise ValueError(f"non-finite VAE-like gradient at step {step}")
        optimizer.step()
        head_winners = torch.argmin(candidate_scores.reshape(b, h, config.samples_per_head).min(dim=2).values, dim=1)
        usage = torch.bincount(head_winners, minlength=h).float() / float(b)
        row: dict[str, Any] = {
            "step": step,
            "total_loss": float(total_loss.detach().cpu().item()),
            "candidate_loss": float(candidate_loss.detach().cpu().item()),
            "mu_loss": float(mu_loss.detach().cpu().item()),
            "entropy_loss": float(entropy_loss.detach().cpu().item()),
            "diversity_loss": float(diversity_loss.detach().cpu().item()),
            "tau": tau,
            "mu_tau": mu_tau,
            "mu_weight": mu_weight,
            "entropy_weight": entropy_weight,
            "sigma_mean": float(sigma_raw.detach().mean().cpu().item()),
            "sigma_min": float(sigma_raw.detach().min().cpu().item()),
            "sigma_max": float(sigma_raw.detach().max().cpu().item()),
            "mean_pairwise_mu_distance": float(
                _mean_pairwise_center_distance(mu_raw.detach()).cpu().item()
            ),
        }
        for head_id, ratio in enumerate(usage.detach().cpu().tolist()):
            row[f"head_{head_id}_usage_ratio"] = float(ratio)
        if writer is not None:
            writer.add_scalar("loss/train", row["total_loss"], step)
            writer.add_scalar("sigma/mean", row["sigma_mean"], step)
        if step % config.validation_interval == 0 or step == config.total_steps - 1:
            validation_loss = _validation_loss(
                model,
                problem,
                modeling,
                common,
                normalization,
                validation_preferences,
            )
            row["validation_loss"] = validation_loss
            if writer is not None:
                writer.add_scalar("loss/validation", validation_loss, step)
        history.append(row)
        if checkpoint_callback is not None and (
            (step + 1) % config.checkpoint_interval == 0 or step == config.total_steps - 1
        ):
            checkpoint_callback(step + 1, model, optimizer)
    return history


def _generate_solutions(
    model: VAELikeMultiheadModel,
    problem: VAELikeMultiheadProblem,
    modeling: ModelingConfig,
    common: AlgorithmCommonConfig,
    config: VAELikeMultiheadConfig,
    normalization: dict[str, float | int],
) -> list[dict[str, Any]]:
    weights_np = np.stack(generate_weight_grid(common.weight_grid_step, common.min_weight)).astype(np.float32)
    weights = torch.as_tensor(weights_np, device=problem.device)
    generator = torch.Generator(device=problem.device)
    generator.manual_seed(config.sampling_seed)
    raw_parts: list[torch.Tensor] = []
    weight_parts: list[torch.Tensor] = []
    metadata: list[dict[str, Any]] = []
    model.eval()
    with torch.no_grad():
        for start in range(0, weights.shape[0], config.preference_batch_size):
            preference_batch = weights[start : start + config.preference_batch_size]
            mu_raw, sigma_raw = model(preference_batch)
            b, h, _ = mu_raw.shape
            center_weights = preference_batch[:, None, :].expand(b, h, 3).reshape(b * h, 3)
            raw_parts.append(mu_raw.reshape(b * h, 3))
            weight_parts.append(center_weights)
            for local_id in range(b):
                weight_index = start + local_id
                for head_id in range(h):
                    metadata.append(
                        {
                            "inference_mode": "center",
                            "weight_index": weight_index,
                            "head_id": head_id,
                            "sample_id": -1,
                            "mu_raw": mu_raw[local_id, head_id].detach().cpu().numpy(),
                            "sigma_raw": sigma_raw[local_id, head_id].detach().cpu().numpy(),
                        }
                    )
            epsilon = torch.randn(
                (b, h, config.eval_samples_per_head, 3),
                generator=generator,
                dtype=mu_raw.dtype,
                device=problem.device,
            )
            samples = mu_raw[:, :, None, :] + sigma_raw[:, :, None, :] * epsilon
            sample_weights = (
                preference_batch[:, None, None, :]
                .expand(b, h, config.eval_samples_per_head, 3)
                .reshape(b * h * config.eval_samples_per_head, 3)
            )
            raw_parts.append(samples.reshape(b * h * config.eval_samples_per_head, 3))
            weight_parts.append(sample_weights)
            for local_id in range(b):
                weight_index = start + local_id
                for head_id in range(h):
                    for sample_id in range(config.eval_samples_per_head):
                        metadata.append(
                            {
                                "inference_mode": "sample",
                                "weight_index": weight_index,
                                "head_id": head_id,
                                "sample_id": sample_id,
                                "mu_raw": mu_raw[local_id, head_id].detach().cpu().numpy(),
                                "sigma_raw": sigma_raw[local_id, head_id].detach().cpu().numpy(),
                            }
                        )
    all_raw = torch.cat(raw_parts, dim=0)
    all_weights = torch.cat(weight_parts, dim=0)
    solutions: list[dict[str, Any]] = []
    chunk_size = max(1, config.preference_batch_size * config.n_heads * config.eval_samples_per_head)
    offset = 0
    with torch.no_grad():
        for start in range(0, all_raw.shape[0], chunk_size):
            raw_chunk = all_raw[start : start + chunk_size]
            weights_chunk = all_weights[start : start + chunk_size]
            pose, objectives = _evaluate_objectives(problem, modeling, raw_chunk)
            scalars = _scores(objectives, weights_chunk, normalization, common)
            hard = compute_hard_constraints(
                problem.dem,
                problem.obstacle_mask,
                pose,
                modeling.rect_w_m,
                modeling.rect_h_m,
                device=str(problem.device),
            )
            for row_id in range(raw_chunk.shape[0]):
                meta = metadata[offset + row_id]
                mu = meta["mu_raw"]
                sigma = meta["sigma_raw"]
                solutions.append(
                    {
                        "run_id": offset + row_id,
                        "inference_mode": meta["inference_mode"],
                        "weight_index": meta["weight_index"],
                        "head_id": meta["head_id"],
                        "sample_id": meta["sample_id"],
                        "sampling_seed": config.sampling_seed,
                        "weight_dem": float(weights_chunk[row_id, 0].cpu().item()),
                        "weight_road": float(weights_chunk[row_id, 1].cpu().item()),
                        "weight_demand": float(weights_chunk[row_id, 2].cpu().item()),
                        "raw_x": float(raw_chunk[row_id, 0].cpu().item()),
                        "raw_y": float(raw_chunk[row_id, 1].cpu().item()),
                        "raw_theta": float(raw_chunk[row_id, 2].cpu().item()),
                        "mu_raw_x": float(mu[0]),
                        "mu_raw_y": float(mu[1]),
                        "mu_raw_theta": float(mu[2]),
                        "sigma_raw_x": float(sigma[0]),
                        "sigma_raw_y": float(sigma[1]),
                        "sigma_raw_theta": float(sigma[2]),
                        "x": float(pose[row_id, 0].cpu().item()),
                        "y": float(pose[row_id, 1].cpu().item()),
                        "theta": float(pose[row_id, 2].cpu().item()),
                        "scalar": float(scalars[row_id].cpu().item()),
                        "dem_soft": float(objectives["dem_soft"][row_id].cpu().item()),
                        "obstacle_soft": float(objectives["obstacle_soft"][row_id].cpu().item()),
                        "road_distance": float(objectives["road_distance"][row_id].cpu().item()),
                        "demand_distance": float(objectives["demand_distance"][row_id].cpu().item()),
                        "dem_hard_var": float(hard["dem_hard_var"][row_id].cpu().item()),
                        "dem_hard_range": float(hard["dem_hard_range"][row_id].cpu().item()),
                        "obstacle_hard_count": float(hard["obstacle_hard_count"][row_id].cpu().item()),
                        "obstacle_hard_ratio": float(hard["obstacle_hard_ratio"][row_id].cpu().item()),
                        "is_feasible": bool(hard["is_feasible"][row_id].cpu().item()),
                    }
                )
            offset += raw_chunk.shape[0]
    return solutions


def run_vae_like_multihead(
    problem: VAELikeMultiheadProblem,
    modeling: ModelingConfig,
    common: AlgorithmCommonConfig,
    config: VAELikeMultiheadConfig,
    validation_preferences: torch.Tensor,
    writer: Any | None = None,
    checkpoint_callback: Callable[[int, nn.Module, torch.optim.Optimizer], None] | None = None,
) -> VAELikeMultiheadResult:
    _validate_config(config)
    torch.manual_seed(config.training_seed)
    torch.cuda.manual_seed_all(config.training_seed)
    model = VAELikeMultiheadModel(
        config.hidden_dim,
        config.backbone_depth,
        config.n_heads,
        config.sigma_eps,
    ).to(problem.device)
    normalization = _compute_normalization(problem, modeling, common)
    history = _train(
        model,
        problem,
        modeling,
        common,
        config,
        normalization,
        validation_preferences,
        writer,
        checkpoint_callback,
    )
    solutions = _generate_solutions(model, problem, modeling, common, config, normalization)
    return VAELikeMultiheadResult(normalization, history, solutions, model)
