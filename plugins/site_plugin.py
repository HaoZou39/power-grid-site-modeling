"""Siting decision schemas for CMA-ES and multi-start Adam.

VAE-like is not registered here. These plugins call the existing search
entries and do not reimplement the optimizers.
"""

from __future__ import annotations

import json

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.domain.plugins import PluginResult, PluginSpec
from plugins.schema import plugin_schema as _schema, inline_local_refs as _inline_local_refs
from config.project_config import CUDA_DEVICE_PATTERN, GUIDED_SEARCH_DEVICE_PATTERN, load_default_config

# 表单默认值全部取自 config/default_config.json；这里只写字段范围和界面文字。
_DEFAULTS = load_default_config()


def _seed_field(default: int, *, minimum: int | None = None) -> Any:
    return Field(
        default=default,
        title="随机 seed",
        ge=minimum,
        description="算法随机种子，用于复现搜索中的随机选择。它不是需求点 seed。",
        json_schema_extra={"x-group": "identity"},
    )


def _parse(model: type[BaseModel], config: dict[str, Any]) -> BaseModel:
    if hasattr(model, "model_validate"):
        return model.model_validate(config)
    return model.parse_obj(config)


class LocalExclusionZone(BaseModel):
    """One hand-drawn no-build polygon in local meters."""

    model_config = ConfigDict(extra="forbid")

    points: list[tuple[float, float]] = Field(min_length=3, title="顶点")


class ObjectiveWeights(BaseModel):
    """Preference weights in objective order dem_soft, road_distance, demand_distance."""

    model_config = ConfigDict(extra="forbid")

    dem_soft: float = Field(default=1 / 3, ge=0, le=1, title="地形平整度权重")
    road_distance: float = Field(default=1 / 3, ge=0, le=1, title="道路距离权重")
    demand_distance: float = Field(default=1 / 3, ge=0, le=1, title="需求点距离权重")

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "ObjectiveWeights":
        total = self.dem_soft + self.road_distance + self.demand_distance
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"objective weights must sum to 1, got {total}")
        return self


class SiteDecisionConfig(BaseModel):
    """Decision-maker fields shared by every siting plugin."""

    model_config = ConfigDict(extra="forbid")

    experiment_name: str = Field(
        min_length=1,
        title="实验名称",
        description="用作输出目录名。不能包含路径分隔符。",
        json_schema_extra={"x-group": "identity"},
    )
    overwrite_existing: bool = Field(
        default=False,
        title="覆盖已有同名实验结果",
        json_schema_extra={"x-group": "identity"},
    )
    seed: int = _seed_field(_DEFAULTS.guided_search.seed)
    rect_w_m: float = Field(
        default=_DEFAULTS.modeling.rect_w_m,
        gt=0,
        title="建筑矩形宽度",
        description=f"110 kV 变电站默认占地宽度 {_DEFAULTS.modeling.rect_w_m:g} m，可以修改。",
        json_schema_extra={"x-group": "site", "x-unit": "m"},
    )
    rect_h_m: float = Field(
        default=_DEFAULTS.modeling.rect_h_m,
        gt=0,
        title="建筑矩形高度",
        description=f"110 kV 变电站默认占地高度 {_DEFAULTS.modeling.rect_h_m:g} m，可以修改。",
        json_schema_extra={"x-group": "site", "x-unit": "m"},
    )
    demand_on_buildable_only: bool = Field(
        default=False,
        title="只在可建设区域生成需求点",
        description="只记录该选择。此任务不会重采样已经生成的需求点。",
        json_schema_extra={"x-group": "site"},
    )
    scene_name: str = Field(
        default=_DEFAULTS.default_scene,
        min_length=1,
        title="场景",
        description="优化读取这个已经构建好的场景，不会在这次搜索里重新生成 DEM、道路或需求点。",
        json_schema_extra={"x-group": "site"},
    )
    target_resolution_m: float = Field(
        default=1.0,
        ge=1,
        le=1,
        title="分辨率",
        description="已生成的数据网格分辨率，不能在这里修改。",
        json_schema_extra={"x-group": "site", "x-unit": "m", "x-readonly": True},
    )
    mountain_policy: Literal["blocked", "allowed"] = Field(
        default="allowed",
        title="山体策略",
        description="allowed 表示山体能否建设看坡度和进站条件，不按类别禁止。blocked 表示山体一律不可建设。",
        json_schema_extra={"x-group": "site"},
    )
    field_policy: Literal["blocked", "allowed", "costly"] = Field(
        default="allowed",
        title="农田策略",
        description="allowed 表示农田能否建设看坡度和进站条件。blocked 表示一律不可建设。costly 表示允许建设并计入软约束。",
        json_schema_extra={"x-group": "site"},
    )
    field_cost: float = Field(
        default=0.5,
        gt=0,
        le=1,
        title="农田代价系数",
        description="只在农田策略为允许建设时使用。1 与硬禁止的软代价相同，更小表示代价更低。",
        json_schema_extra={"x-group": "site"},
    )
    road_setback_m: float = Field(
        default=_DEFAULTS.modeling.road_setback_m,
        ge=0,
        title="道路最小退距",
        description="遥感道路与 OSM 道路中心线并集向外扩展的建筑禁建距离，单位米。0 表示只禁止压到道路格子本身。不改变进站路径。",
        json_schema_extra={"x-group": "site", "x-unit": "m"},
    )
    water_setback_m: float = Field(
        default=_DEFAULTS.modeling.water_setback_m,
        ge=0,
        title="水体最小退距",
        description="遥感与官方水体合并区域向外扩展的建筑禁建距离，单位米。默认 5；0 表示只禁止建筑压到水体本身，不影响进站道路。",
        json_schema_extra={"x-group": "site", "x-unit": "m"},
    )
    highway_setback_m: float = Field(default=_DEFAULTS.modeling.highway_setback_m, ge=0, title="高速及匝道建筑退距", json_schema_extra={"x-group": "site", "x-unit": "m"})
    exclusion_zones: list[LocalExclusionZone] = Field(
        default_factory=list,
        title="手绘禁区",
        description="局部米坐标多边形。这些范围在本次优化中禁止建设。",
        json_schema_extra={"x-group": "site"},
    )
    feasible_zones: list[LocalExclusionZone] = Field(
        default_factory=list,
        title="可行域",
        description="局部米坐标多边形。有这些范围时，搜索只能落在它们的并集内。",
        json_schema_extra={"x-group": "site"},
    )
    objective_weights: ObjectiveWeights = Field(
        default_factory=ObjectiveWeights,
        title="目标权重",
        description="权重总和必须为 1。所有目标当前按最小化解释。",
        json_schema_extra={"x-group": "preference"},
    )


class CmaEsSiteConfig(SiteDecisionConfig):
    seed: int = _seed_field(_DEFAULTS.cma_es.seed, minimum=1)
    popsize: int = Field(default=_DEFAULTS.cma_es.popsize, ge=1, title="种群大小", json_schema_extra={"x-group": "algorithm"})
    sigma0: float = Field(default=_DEFAULTS.cma_es.sigma0, gt=0, title="初始步长", json_schema_extra={"x-group": "algorithm"})
    max_iters: int = Field(default=_DEFAULTS.cma_es.max_iters, ge=1, title="迭代次数", json_schema_extra={"x-group": "algorithm"})
    restarts_per_weight: int = Field(
        default=_DEFAULTS.cma_es.restarts_per_weight,
        ge=1,
        title="每个权重的重启次数",
        json_schema_extra={"x-group": "algorithm"},
    )
    device: str = Field(
        default=_DEFAULTS.modeling.device,
        pattern=CUDA_DEVICE_PATTERN,
        title="计算设备",
        description="当前实验入口要求 CUDA，填写 cuda 或 cuda:编号。",
        json_schema_extra={"x-group": "algorithm"},
    )


class GuidedSiteConfig(SiteDecisionConfig):
    origin_x: float | None = Field(default=None, title="进货原点 x", json_schema_extra={"x-group": "site", "x-unit": "m"})
    origin_y: float | None = Field(default=None, title="进货原点 y", json_schema_extra={"x-group": "site", "x-unit": "m"})
    include_demand: bool = Field(
        default=_DEFAULTS.guided_search.include_demand,
        title="比较需求点距离",
        description="需求点目前是随机生成的，默认不参加支配比较和梯度引导。有真实负荷后再打开。",
        json_schema_extra={"x-group": "site"},
    )
    diagonal_access: bool = Field(
        default=True,
        title="进站允许斜向",
        description="固定开启。进站走八连通，斜向一步，两侧格子都必须可通行，不能从障碍角切过。",
        json_schema_extra={"x-group": "site", "x-readonly": True},
    )
    seed: int = _seed_field(_DEFAULTS.guided_search.seed)
    popsize: int = Field(default=_DEFAULTS.guided_search.popsize, ge=4, title="种群大小", json_schema_extra={"x-group": "algorithm"})
    evolution_backend: Literal["tensor", "numpy"] = Field(
        default=_DEFAULTS.guided_search.evolution_backend, title="演化后端", json_schema_extra={"x-group": "algorithm"},
    )
    evaluation_batch_size: int = Field(
        default=_DEFAULTS.guided_search.evaluation_batch_size, ge=1, title="评价批大小", json_schema_extra={"x-group": "algorithm"},
    )
    initialization: Literal["gaussian", "uniform", "taguchi"] = Field(
        default=_DEFAULTS.guided_search.initialization, title="初始化方式", json_schema_extra={"x-group": "algorithm"},
    )
    generations: int = Field(default=_DEFAULTS.guided_search.generations, ge=1, title="进化代数", json_schema_extra={"x-group": "algorithm"})
    sigma0: float = Field(default=_DEFAULTS.guided_search.sigma0, gt=0, title="Gaussian 初始化分布宽度", description="仅 Gaussian 初始化使用 sigma0；uniform 和 taguchi 不使用，进化变异由 refine_sigma 控制。", json_schema_extra={"x-group": "algorithm"})

    @model_validator(mode="after")
    def taguchi_population_is_square(self) -> "GuidedSiteConfig":
        if self.initialization == "taguchi" and math.isqrt(self.popsize) ** 2 != self.popsize:
            raise ValueError("taguchi initialization requires a square popsize, such as 10000")
        # Old forms may still send false. New runs stay on the eight-connected field.
        self.diagonal_access = True
        return self

    device: str = Field(
        default=_DEFAULTS.modeling.device,
        pattern=GUIDED_SEARCH_DEVICE_PATTERN,
        title="计算设备",
        description="填写 auto、cpu、cuda 或 cuda:编号。优先使用 CUDA；无可用 CUDA 时使用原版 NumPy 演化和 CPU 评价。",
        json_schema_extra={"x-group": "algorithm"},
    )


class PartitionedGuidedSiteConfig(GuidedSiteConfig):
    """Decision fields for parallel searches over rectangular scene partitions."""

    partition_count: Literal[4, 6] = Field(
        default=4,
        title="矩形分区数量",
        description="将整个搜索中心范围等分为 4 或 6 个矩形区域，分别运行相同的引导式搜索。",
        json_schema_extra={"x-group": "algorithm"},
    )
    max_parallel_tiles: int = Field(
        default=2,
        ge=1,
        le=6,
        title="最大并行分区数",
        description="限制同时使用计算设备的子搜索数量；不必与分区数量相同。",
        json_schema_extra={"x-group": "algorithm"},
    )
    search_bounds_m: tuple[float, float, float, float] | None = Field(
        default=None,
        title="搜索矩形",
        description="可选的站址中心搜索范围 [x_min, y_min, x_max, y_max]，单位米；留空时使用整个场景的安全范围。",
        json_schema_extra={"x-group": "site", "x-unit": "m"},
    )

    @model_validator(mode="after")
    def validate_partition_settings(self) -> "PartitionedGuidedSiteConfig":
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.max_parallel_tiles > self.partition_count:
            raise ValueError("max_parallel_tiles cannot exceed partition_count")
        if self.search_bounds_m is not None:
            xmin, ymin, xmax, ymax = self.search_bounds_m
            if not all(math.isfinite(value) for value in self.search_bounds_m):
                raise ValueError("search_bounds_m must contain finite values")
            if xmax <= xmin or ymax <= ymin:
                raise ValueError("search_bounds_m must be a non-empty rectangle")
        return self


class MultiStartAdamSiteConfig(SiteDecisionConfig):
    seed: int = _seed_field(_DEFAULTS.multistart_adam.seed)
    starts_per_weight: int = Field(
        default=_DEFAULTS.multistart_adam.starts_per_weight, ge=1, title="每个权重的起点数量", json_schema_extra={"x-group": "algorithm"},
    )
    max_steps: int = Field(default=_DEFAULTS.multistart_adam.max_steps, ge=1, title="迭代步数", json_schema_extra={"x-group": "algorithm"})
    learning_rate: float = Field(
        default=_DEFAULTS.multistart_adam.learning_rate, gt=0, title="学习率", json_schema_extra={"x-group": "algorithm"},
    )
    init_eps: float = Field(
        default=_DEFAULTS.multistart_adam.init_eps,
        gt=0,
        lt=0.5,
        title="起点边界余量",
        description="起点采样离开参数边界的比例。",
        json_schema_extra={"x-group": "algorithm"},
    )
    device: str = Field(
        default=_DEFAULTS.modeling.device,
        pattern=CUDA_DEVICE_PATTERN,
        title="计算设备",
        description="当前实验入口要求 CUDA，填写 cuda 或 cuda:编号。",
        json_schema_extra={"x-group": "algorithm"},
    )


class _SitePlugin:
    id = ""
    version = "0.1.0"
    algorithm = ""
    plugin_name = ""
    plugin_description = ""
    model: type[BaseModel] = SiteDecisionConfig
    expected_artifacts: tuple[str, ...] = ()

    def describe(self) -> PluginSpec:
        return PluginSpec(
            id=self.id,
            version=self.version,
            kind="algorithm",
            name=self.plugin_name,
            description=self.plugin_description,
            config_schema=_schema(self.model),
        )

    def validate_config(self, config: dict[str, Any]) -> None:
        _parse(self.model, config)

    def run(self, config: dict[str, Any], reporter) -> PluginResult:
        parsed = _parse(self.model, config)
        from experiments.launch_site_run import launch_site_run

        output_dir = launch_site_run(parsed.model_dump() if hasattr(parsed, "model_dump") else parsed.dict(), self.algorithm, reporter)
        return PluginResult(
            status="succeeded",
            metrics={},
            data={
                "data_version": json.loads((output_dir / "data_metadata.json").read_text(encoding="utf-8")).get("data_version"),
                "optimizer_executed": True,
                "experiment_id": output_dir.name,
                "expected_artifacts": list(self.expected_artifacts),
            },
        )


class GuidedSitePlugin(_SitePlugin):
    id = "site.guided_search"
    algorithm = "guided_search"
    plugin_name = "引导式多目标选址"
    plugin_description = (
        "读取已构建的场景，用引导式多目标搜索比较脚印平整度、进站长度和进站累计高差；有进货原点时再加上沿路长度。需求点距离默认不比较。"
        "建筑、道路、水体以及手绘禁区仍是硬约束：不可行个体排在可行个体之后。"
        "预计产物包括 solutions.csv、pareto_solutions.csv、normalization.json 和 run_summary.json。"
    )
    model = GuidedSiteConfig
    expected_artifacts = (
        "solutions.csv",
        "pareto_solutions.csv",
        "normalization.json",
        "run_summary.json",
    )


class PartitionedGuidedSitePlugin(_SitePlugin):
    id = "site.partitioned_guided_search"
    algorithm = "partitioned_guided_search"
    plugin_name = "矩形分区并行选址"
    plugin_description = (
        "将一个场景的安全搜索范围划分成 4 或 6 个矩形分区，共享同一份全局数据和进场距离场并行运行引导式多目标搜索，"
        "再按全局坐标复核并汇总成一个实验结果。前端不负责分区。"
    )
    model = PartitionedGuidedSiteConfig
    expected_artifacts = (
        "solutions.csv",
        "pareto_solutions.csv",
        "normalization.json",
        "run_summary.json",
        "partition_manifest.json",
        "partitions.csv",
    )

    def run(self, config: dict[str, Any], reporter) -> PluginResult:
        parsed = _parse(self.model, config)
        from experiments.partitioned_search import launch_partitioned_site_run

        payload = parsed.model_dump() if hasattr(parsed, "model_dump") else parsed.dict()
        output_dir = launch_partitioned_site_run(payload, reporter)
        return PluginResult(
            status="succeeded",
            metrics={},
            data={
                "data_version": json.loads((output_dir / "data_metadata.json").read_text(encoding="utf-8")).get("data_version"),
                "optimizer_executed": True,
                "experiment_id": output_dir.name,
                "expected_artifacts": list(self.expected_artifacts),
            },
        )


class CmaEsSitePlugin(_SitePlugin):
    id = "site.cma_es"
    algorithm = "cma_es"
    plugin_name = "CMA-ES 选址"
    plugin_description = (
        "读取已构建的场景，再沿项目配置里的权重网格运行现有 CMA-ES 入口，写出帕累托方案。"
        "预计产物包括 solutions.csv、pareto_solutions.csv、runs.csv、normalization.json 和 run_summary.json。"
    )
    model = CmaEsSiteConfig
    expected_artifacts = (
        "solutions.csv",
        "pareto_solutions.csv",
        "runs.csv",
        "normalization.json",
        "run_summary.json",
    )


class PrepareSceneConfig(BaseModel):
    """Fields for the offline data stage. This model does not start a search."""

    model_config = ConfigDict(extra="forbid")

    scene_name: str = Field(
        default=_DEFAULTS.default_scene,
        min_length=1,
        title="场景",
        description="要构建的新场景 id。默认 UTM 场景使用配置登记的原始文件，其他新场景使用 scene.json 记录的原始文件和目标网格；封存历史场景只供查看。rebuild 为 true 时重新生成并融合水系。",
    )
    rebuild: bool = Field(
        default=False,
        title="重新构建",
        description="已就绪场景默认直接复用。设为 true 时重新生成场景数据；网格未变时保留永久基本农田。",
    )


class BuildSceneConfig(BaseModel):
    """Center coordinate and square size for a new scene. This does not start a search."""

    model_config = ConfigDict(extra="forbid")

    lat: float = Field(title="纬度", description="中心纬度，十进制度。")
    lon: float = Field(title="经度", description="中心经度，十进制度。")
    side_length_m: float = Field(
        default=1800,
        gt=0,
        title="边长",
        description="正方形边长，单位米，必须是 2 到 10000 之间的偶数。一格 1 m，网格等于边长乘边长。1800 对应当地 WGS84 UTM 米制网格 1800×1800，卫星下载范围自动覆盖目标网格。",
        json_schema_extra={"x-unit": "m"},
    )
    site_name: str | None = Field(default=None, title="场景名称", description="可选，可以使用中文。只作为显示名，不进入 site_id。")
    zoom: int = Field(default=18, ge=1, title="卫星缩放级别")
    road_buffer_m: float = Field(default=500, ge=0, title="道路缓冲", json_schema_extra={"x-unit": "m"})

    @model_validator(mode="after")
    def coordinates_match_the_pipeline_identity(self) -> "BuildSceneConfig":
        from experiments.coordinate_scene import validate_build_config

        validate_build_config(self.model_dump())
        return self


class BuildScenePlugin(_SitePlugin):
    id = "site.build_scene"
    algorithm = "build_scene"
    plugin_name = "按坐标构建场景"
    plugin_description = (
        "用中心经纬度和正方形边长生成四份站点数据，校验后重建现有场景。"
        "这一步不运行优化。失败会停在对应阶段，并且不会用未通过校验的文件替换已有场景。"
    )
    model = BuildSceneConfig
    expected_artifacts = ()

    def run(self, config: dict[str, Any], reporter) -> PluginResult:
        parsed = _parse(self.model, config)
        from experiments.coordinate_scene import build_scene_from_coordinates

        payload = parsed.model_dump() if hasattr(parsed, "model_dump") else parsed.dict()
        built = build_scene_from_coordinates(payload, reporter)
        return PluginResult(
            status="succeeded",
            metrics={},
            data={
                "optimizer_executed": False,
                "scene_id": built["scene_id"],
                "site_id": built["site_id"],
                "terminal_stage": "ready",
                "message": built["message"],
                "protected_farmland_notice": built.get("protected_farmland_notice") or "",
                "bundle_dir": built["bundle_dir"],
                "scene_dir": built["scene_dir"],
                "elapsed_s": built["elapsed_s"],
                "stage": "ready",
            },
        )


class PrepareScenePlugin(_SitePlugin):
    id = "site.prepare_scene"
    algorithm = "prepare_scene"
    plugin_name = "构建场景数据"
    plugin_description = "从原始 DEM、用地和道路生成 1 m 场景数据。这一步不运行优化。"
    model = PrepareSceneConfig
    expected_artifacts = ()

    def run(self, config: dict[str, Any], reporter) -> PluginResult:
        parsed = _parse(self.model, config)
        from experiments.scene_store import prepare_scene, scene_rebuild_notice

        scene_name = parsed.scene_name if hasattr(parsed, "scene_name") else config["scene_name"]
        rebuild = bool(parsed.rebuild) if hasattr(parsed, "rebuild") else bool(config.get("rebuild", False))
        path = prepare_scene(str(scene_name), reporter, rebuild=rebuild)

        notice = scene_rebuild_notice(path)
        data: dict[str, Any] = {"optimizer_executed": False, "scene_id": path.name, "stage": "scene"}
        if notice:
            data["protected_farmland_notice"] = notice
            data["message"] = f"场景数据已写入。{notice}"
        return PluginResult(
            status="succeeded",
            metrics={},
            data=data,
        )


class MultiStartAdamSitePlugin(_SitePlugin):
    id = "site.multistart_adam"
    algorithm = "multistart_adam"
    plugin_name = "多起点 Adam 选址"
    plugin_description = (
        "用提交的一组目标权重运行现有多起点 Adam 入口。预计产物与 CMA-ES 相同。"
    )
    model = MultiStartAdamSiteConfig
    expected_artifacts = CmaEsSitePlugin.expected_artifacts
