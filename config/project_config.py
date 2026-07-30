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
class ProjectConfig:
    data: DataConfig
    modeling: ModelingConfig = field(default_factory=ModelingConfig)
    common: AlgorithmCommonConfig = field(default_factory=AlgorithmCommonConfig)
    cma_es: CMAESConfig = field(default_factory=CMAESConfig)
    multistart_adam: MultiStartAdamConfig = field(default_factory=MultiStartAdamConfig)
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
    return ProjectConfig(
        data=DataConfig(**data_raw),
        modeling=ModelingConfig(**raw.get("modeling", {})),
        common=AlgorithmCommonConfig(**raw.get("common", {})),
        cma_es=CMAESConfig(**raw.get("cma_es", {})),
        multistart_adam=MultiStartAdamConfig(**raw.get("multistart_adam", {})),
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
