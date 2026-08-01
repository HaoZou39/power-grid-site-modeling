from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import torch


@dataclass(frozen=True)
class DataConfig:
    dem_path: Path
    landuse_path: Path
    osm_roads_path: Path
    reference_geotiff_path: Path
    output_dir: Path = Path("outputs/validate_modeling")
    landuse_input_resolution_m: float = 1.0
    target_resolution_m: float = 1.0
    obstacle_classes: tuple[int, ...] = (1, 2, 3, 5)
    road_dp_tolerance_m: float = 2.0
    road_resolution_m: float = 1.0
    n_demand_points: int = 64
    demand_seed: int = 42
    demand_on_buildable_only: bool = False


@dataclass(frozen=True)
class ModelingConfig:
    rect_w_m: float = 80.0
    rect_h_m: float = 50.0
    soft_mask_sharpness: float = 8.0
    device: str = "cuda"
    objective_scales: dict[str, float] = field(
        default_factory=lambda: {
            "dem": 1.0,
            "obstacle": 1.0,
            "road": 1.0,
            "demand": 1.0,
        }
    )


@dataclass(frozen=True)
class CMAESConfig:
    algorithm_name: str = "cma_es"
    seed: int = 123
    popsize: int = 8
    sigma0: float = 1.0
    max_iters: int = 40
    restarts_per_weight: int = 1


@dataclass(frozen=True)
class AlgorithmCommonConfig:
    normalization_samples: int = 512
    normalization_scale_percentile: float = 95.0
    normalization_seed: int = 123
    weight_grid_step: float = 0.01
    min_weight: float = 0.0
    obstacle_penalty_scale: float = 100.0
    scalarization_eps: float = 0.0
    weiszfeld_max_iters: int = 512
    weiszfeld_tol: float = 1e-6
    weiszfeld_eps: float = 1e-8


@dataclass(frozen=True)
class MultiStartAdamConfig:
    algorithm_name: str = "multistart_adam"
    seed: int = 123
    starts_per_weight: int = 8
    max_steps: int = 80
    learning_rate: float = 0.05
    init_eps: float = 0.01


@dataclass(frozen=True)
class VAELikeMultiheadConfig:
    algorithm_name: str = "vae_like_multihead"
    training_seed: int = 123
    sampling_seed: int = 456
    hidden_dim: int = 128
    backbone_depth: int = 2
    n_heads: int = 4
    samples_per_head: int = 4
    preference_batch_size: int = 8
    total_steps: int = 1000
    learning_rate: float = 1e-3
    sigma_eps: float = 1e-6
    tau_start: float = 1.0
    tau_end: float = 0.05
    mu_tau_start: float = 1.0
    mu_tau_end: float = 0.05
    mu_weight_start: float = 0.1
    mu_weight_end: float = 1.0
    entropy_weight_start: float = 0.01
    entropy_weight_end: float = 0.0
    diversity_weight: float = 0.01
    diversity_bandwidth: float = 0.1
    max_grad_norm: float = 10.0
    eval_samples_per_head: int = 8
    checkpoint_interval: int = 100
    validation_preferences_path: Path = Path("validation_data/preferences_step_0.1.csv")
    validation_interval: int = 20


@dataclass(frozen=True)
class ProjectConfig:
    data: DataConfig
    modeling: ModelingConfig = field(default_factory=ModelingConfig)
    common: AlgorithmCommonConfig = field(default_factory=AlgorithmCommonConfig)
    cma_es: CMAESConfig = field(default_factory=CMAESConfig)
    multistart_adam: MultiStartAdamConfig = field(default_factory=MultiStartAdamConfig)
    vae_like_multihead: VAELikeMultiheadConfig = field(default_factory=VAELikeMultiheadConfig)
    experiment_name: str = "validate_modeling"


def _to_path(value: str | Path) -> Path:
    return value if isinstance(value, Path) else Path(value)


def load_project_config(path: str | Path) -> ProjectConfig:
    cfg_path = _to_path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(cfg_path)
    raw = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    data_raw = raw["data"]
    for key in ("dem_path", "landuse_path", "osm_roads_path", "reference_geotiff_path", "output_dir"):
        data_raw[key] = Path(data_raw[key])
    data_raw["obstacle_classes"] = tuple(int(x) for x in data_raw["obstacle_classes"])
    vae_raw = dict(raw.get("vae_like_multihead", {}))
    if "validation_preferences_path" in vae_raw:
        vae_raw["validation_preferences_path"] = Path(vae_raw["validation_preferences_path"])
    return ProjectConfig(
        data=DataConfig(**data_raw),
        modeling=ModelingConfig(**raw.get("modeling", {})),
        common=AlgorithmCommonConfig(**raw.get("common", {})),
        cma_es=CMAESConfig(**raw.get("cma_es", {})),
        multistart_adam=MultiStartAdamConfig(**raw.get("multistart_adam", {})),
        vae_like_multihead=VAELikeMultiheadConfig(**vae_raw),
        experiment_name=raw.get("experiment_name", "validate_modeling"),
    )


def save_config(config: ProjectConfig, path: str | Path) -> None:
    out = _to_path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    def convert(obj: Any) -> Any:
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, tuple):
            return list(obj)
        if isinstance(obj, dict):
            return {k: convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [convert(v) for v in obj]
        return obj

    out.write_text(json.dumps(convert(asdict(config)), indent=2), encoding="utf-8")


def validate_cuda_device(device: str) -> torch.device:
    if device != "cuda" and not device.startswith("cuda:"):
        raise ValueError(f"device must be cuda, got {device!r}")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required but torch.cuda.is_available() is False")
    if torch.cuda.device_count() < 1:
        raise RuntimeError("CUDA is required but no CUDA devices are visible")
    return torch.device(device)
