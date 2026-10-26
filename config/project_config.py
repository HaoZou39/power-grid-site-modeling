from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, fields
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

# API 镜像不装 PyTorch，只读配置时不能导入它。
if TYPE_CHECKING:
    import torch


@dataclass(frozen=True)
class DataConfig:
    dem_path: Path
    landuse_path: Path
    osm_roads_path: Path
    reference_geotiff_path: Path
    display_max_size_px: int
    target_grid: dict[str, Any]
    road_kind_rules: dict[str, Any]
    road_import_clip_buffer_m: float
    road_import_excluded_classes: tuple[str, ...]
    output_dir: Path
    landuse_input_resolution_m: float
    target_resolution_m: float
    obstacle_classes: tuple[int, ...]
    road_dp_tolerance_m: float
    road_resolution_m: float
    road_voronoi_backend: str
    road_voronoi_device: str
    road_voronoi_chunk_points: int
    road_voronoi_segment_tile: int
    n_demand_points: int
    demand_seed: int
    demand_on_buildable_only: bool
    # Total width of a new access road. Permanent farmland is dilated by half of this.
    protected_farmland_access_width_m: float

# 建模与算法参数的取值只写在 default_config.json，这里只定义字段和类型。
# JSON 缺字段或多字段时，构造 dataclass 直接 TypeError。
DEFAULT_CONFIG_PATH = Path(__file__).with_name("default_config.json")

# modeling.device 同时是所有插件表单的默认设备，所以只接受 CMA-ES 和 Adam 也能用的 CUDA 写法。
# 引导搜索的请求另外接受 auto 和 cpu。插件表单与运行入口共用这两条规则。
CUDA_DEVICE_PATTERN = r"^cuda(:\d+)?$"
GUIDED_SEARCH_DEVICE_PATTERN = r"^(auto|cpu|cuda(:\d+)?)$"


@dataclass(frozen=True)
class ModelingConfig:
    rect_w_m: float
    rect_h_m: float
    soft_mask_sharpness: float
    device: str
    objective_scales: dict[str, float]
    highway_setback_m: float
    road_setback_m: float
    water_setback_m: float


@dataclass(frozen=True)
class CMAESConfig:
    algorithm_name: str
    seed: int
    popsize: int
    sigma0: float
    max_iters: int
    restarts_per_weight: int


@dataclass(frozen=True)
class GuidedSearchConfig:
    algorithm_name: str
    evolution_backend: str
    seed: int
    popsize: int
    evaluation_batch_size: int
    initialization: str
    generations: int
    sigma0: float
    guide_steps: int
    guide_lr: float
    guide_obstacle_penalty: float
    guide_batch_size: int
    refine_sigma: float
    anneal_last_generations: int
    anneal_sigma_end: float
    adaptive_sigma: bool
    sigma_shrink: float
    sigma_patience: int
    sigma_floor: float
    include_demand: bool
    diagonal_access: bool
    access_elevation_weight: float


@dataclass(frozen=True)
class RoutingConfig:
    algorithm_name: str
    seed: int
    popsize: int
    max_evaluations: int
    reference_count: int
    mutation_scale: float
    expansion_interval: int
    expansion_step: int
    repair_attempts: int
    navigation_step_m: int

    def __post_init__(self) -> None:
        if self.algorithm_name != "routing_nsga2":
            raise ValueError("routing.algorithm_name must be routing_nsga2")
        for name in ("seed", "popsize", "max_evaluations", "reference_count", "expansion_interval",
                     "expansion_step", "repair_attempts", "navigation_step_m"):
            value = getattr(self, name)
            minimum = 0 if name == "seed" else 1
            if type(value) is not int or value < minimum:
                raise ValueError(f"routing.{name} must be an integer >= {minimum}")
        if self.popsize < 4 or self.max_evaluations < self.popsize:
            raise ValueError("routing requires popsize >= 4 and max_evaluations >= popsize")
        if isinstance(self.mutation_scale, bool) or not math.isfinite(self.mutation_scale) or not 0 < self.mutation_scale <= 1:
            raise ValueError("routing.mutation_scale must be in (0, 1]")


@dataclass(frozen=True)
class AlgorithmCommonConfig:
    normalization_samples: int
    normalization_scale_percentile: float
    normalization_seed: int
    weight_grid_step: float
    min_weight: float
    obstacle_penalty_scale: float
    scalarization_eps: float
    weiszfeld_max_iters: int
    weiszfeld_tol: float
    weiszfeld_eps: float


@dataclass(frozen=True)
class MultiStartAdamConfig:
    algorithm_name: str
    seed: int
    starts_per_weight: int
    max_steps: int
    learning_rate: float
    init_eps: float


@dataclass(frozen=True)
class VAELikeMultiheadConfig:
    algorithm_name: str
    training_seed: int
    sampling_seed: int
    hidden_dim: int
    backbone_depth: int
    n_heads: int
    samples_per_head: int
    preference_batch_size: int
    total_steps: int
    learning_rate: float
    sigma_eps: float
    tau_start: float
    tau_end: float
    mu_tau_start: float
    mu_tau_end: float
    mu_weight_start: float
    mu_weight_end: float
    entropy_weight_start: float
    entropy_weight_end: float
    diversity_weight: float
    diversity_bandwidth: float
    max_grad_norm: float
    eval_samples_per_head: int
    checkpoint_interval: int
    validation_preferences_path: Path
    validation_interval: int


@dataclass(frozen=True)
class ProjectConfig:
    default_scene: str
    data: DataConfig
    modeling: ModelingConfig
    common: AlgorithmCommonConfig
    cma_es: CMAESConfig
    guided_search: GuidedSearchConfig
    routing: RoutingConfig
    multistart_adam: MultiStartAdamConfig
    vae_like_multihead: VAELikeMultiheadConfig
    experiment_name: str


def _to_path(value: str | Path) -> Path:
    return value if isinstance(value, Path) else Path(value)


def load_project_config(path: str | Path) -> ProjectConfig:
    cfg_path = _to_path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(cfg_path)
    raw = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    expected = {field.name for field in fields(ProjectConfig)}
    if not isinstance(raw, dict) or set(raw) != expected:
        actual = set(raw) if isinstance(raw, dict) else set()
        raise ValueError(f"project config fields mismatch: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}")
    scene_name = raw["default_scene"]
    if not isinstance(scene_name,str) or not scene_name.strip() or scene_name in {".",".."} or "/" in scene_name or "\\" in scene_name:
        raise ValueError("default_scene must be a single scene name")
    data_raw = raw["data"]
    if "display_max_size_px" in data_raw and (
        type(data_raw["display_max_size_px"]) is not int or data_raw["display_max_size_px"] <= 0
    ):
        raise ValueError("data.display_max_size_px must be a positive integer")
    grid = data_raw.get("target_grid")
    if not isinstance(grid, dict) or set(grid) != {"crs", "transform", "width", "height"}:
        raise ValueError("data.target_grid must explicitly contain crs, transform, width and height")
    if not re.fullmatch(r"EPSG:(326|327)(0[1-9]|[1-5][0-9]|60)", str(grid["crs"])):
        raise ValueError("data.target_grid must use WGS84 UTM")
    transform = grid["transform"]
    if not isinstance(transform, list) or len(transform) != 6 or not all(type(v) in (int,float) and math.isfinite(v) for v in transform):
        raise ValueError("data.target_grid transform must contain six finite numbers")
    if transform[:2] != [1,0] or transform[3:5] != [0,-1]:
        raise ValueError("data.target_grid must be an unrotated 1 m grid")
    if any(type(grid[key]) is not int or grid[key] <= 0 for key in ("width", "height")):
        raise ValueError("data.target_grid dimensions must be positive integers")
    for key in ("dem_path", "landuse_path", "osm_roads_path", "reference_geotiff_path", "output_dir"):
        data_raw[key] = Path(data_raw[key])
    data_raw["obstacle_classes"] = tuple(int(x) for x in data_raw["obstacle_classes"])
    data_raw["road_import_excluded_classes"] = tuple(data_raw["road_import_excluded_classes"])
    vae_raw = dict(raw["vae_like_multihead"])
    vae_raw["validation_preferences_path"] = Path(vae_raw["validation_preferences_path"])
    modeling = ModelingConfig(**raw["modeling"])
    if not re.fullmatch(CUDA_DEVICE_PATTERN, modeling.device):
        raise ValueError(f"modeling.device must be cuda or cuda:<index>, got {modeling.device!r}")
    return ProjectConfig(
        default_scene=raw["default_scene"],
        data=DataConfig(**data_raw),
        modeling=modeling,
        common=AlgorithmCommonConfig(**raw["common"]),
        cma_es=CMAESConfig(**raw["cma_es"]),
        guided_search=GuidedSearchConfig(**raw["guided_search"]),
        routing=RoutingConfig(**raw["routing"]),
        multistart_adam=MultiStartAdamConfig(**raw["multistart_adam"]),
        vae_like_multihead=VAELikeMultiheadConfig(**vae_raw),
        experiment_name=raw["experiment_name"],
    )


@lru_cache(maxsize=1)
def load_default_config() -> ProjectConfig:
    """表单默认值、助手说明和测试共用的那一份默认参数。"""

    return load_project_config(DEFAULT_CONFIG_PATH)


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
    import torch

    if not re.fullmatch(CUDA_DEVICE_PATTERN, device):
        raise ValueError(f"device must be cuda or cuda:<index>, got {device!r}")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required but torch.cuda.is_available() is False")
    if torch.cuda.device_count() < 1:
        raise RuntimeError("CUDA is required but no CUDA devices are visible")
    return torch.device(device)


def resolve_guided_search_device(device: str = "auto") -> torch.device:
    """Prefer CUDA for guided search, using CPU when CUDA is unavailable."""
    import torch

    if not re.fullmatch(GUIDED_SEARCH_DEVICE_PATTERN, device):
        raise ValueError(f"guided search device must be auto, cpu, or cuda[:index], got {device!r}")
    if device == "cpu":
        return torch.device("cpu")
    target = torch.device("cuda" if device == "auto" else device)
    if not torch.cuda.is_available() or torch.cuda.device_count() == 0:
        return torch.device("cpu")
    if target.index is not None and target.index >= torch.cuda.device_count():
        raise ValueError(f"CUDA device index is out of range: {target.index}")
    return target
