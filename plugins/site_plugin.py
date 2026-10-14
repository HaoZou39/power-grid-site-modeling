"""Siting decision schemas for CMA-ES and multi-start Adam.

VAE-like is not registered here. These plugins call the existing search
entries and do not reimplement the optimizers.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.domain.plugins import PluginResult, PluginSpec


def _schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema() if hasattr(model, "model_json_schema") else model.schema()
    return _inline_local_refs(raw)


def _inline_local_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Publish nested models as concrete properties so the form does not need $ref."""

    definitions = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            name = str(node["$ref"]).rsplit("/", 1)[-1]
            target = walk(definitions[name])
            rest = {key: value for key, value in node.items() if key != "$ref"}
            return {**target, **rest}
        current = node
        if "allOf" in current:
            merged: dict[str, Any] = {}
            for item in current["allOf"]:
                merged.update(walk(item))
            rest = {key: value for key, value in current.items() if key != "allOf"}
            merged.update(rest)
            current = merged
        if "properties" in current:
            current = {
                **current,
                "properties": {key: walk(value) for key, value in current["properties"].items()},
            }
        return current

    inlined = walk(schema)
    if isinstance(inlined, dict):
        inlined.pop("$defs", None)
    return inlined


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
    seed: int = Field(
        default=123,
        title="随机 seed",
        description="算法随机种子，用于复现搜索中的随机选择。它不是需求点 seed。",
        json_schema_extra={"x-group": "identity"},
    )
    rect_w_m: float = Field(
        default=77.0,
        gt=0,
        title="建筑矩形宽度",
        description="110 kV 变电站默认占地宽度 77 m，可以修改。",
        json_schema_extra={"x-group": "site", "x-unit": "m"},
    )
    rect_h_m: float = Field(
        default=51.5,
        gt=0,
        title="建筑矩形高度",
        description="110 kV 变电站默认占地高度 51.5 m，可以修改。",
        json_schema_extra={"x-group": "site", "x-unit": "m"},
    )
    demand_on_buildable_only: bool = Field(
        default=False,
        title="只在可建设区域生成需求点",
        description="只记录该选择。此任务不会重采样已经生成的需求点。",
        json_schema_extra={"x-group": "site"},
    )
    scene_name: str = Field(
        default="cangnan",
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
    popsize: int = Field(default=8, ge=1, title="种群大小", json_schema_extra={"x-group": "algorithm"})
    sigma0: float = Field(default=1.0, gt=0, title="初始步长", json_schema_extra={"x-group": "algorithm"})
    max_iters: int = Field(default=40, ge=1, title="迭代次数", json_schema_extra={"x-group": "algorithm"})
    restarts_per_weight: int = Field(
        default=1,
        ge=1,
        title="每个权重的重启次数",
        json_schema_extra={"x-group": "algorithm"},
    )
    device: Literal["cuda"] = Field(
        default="cuda",
        title="计算设备",
        description="当前实验入口要求 CUDA。",
        json_schema_extra={"x-group": "algorithm"},
    )


class GuidedSiteConfig(SiteDecisionConfig):
    origin_x: float | None = Field(default=None, title="进货原点 x", json_schema_extra={"x-group": "site", "x-unit": "m"})
    origin_y: float | None = Field(default=None, title="进货原点 y", json_schema_extra={"x-group": "site", "x-unit": "m"})
    include_demand: bool = Field(
        default=False,
        title="比较需求点距离",
        description="需求点目前是随机生成的，默认不参加支配比较和梯度引导。有真实负荷后再打开。",
        json_schema_extra={"x-group": "site"},
    )
    popsize: int = Field(default=40, ge=4, title="种群大小", json_schema_extra={"x-group": "algorithm"})
    generations: int = Field(default=90, ge=1, title="进化代数", json_schema_extra={"x-group": "algorithm"})
    sigma0: float = Field(default=1.0, gt=0, title="变异步长", json_schema_extra={"x-group": "algorithm"})
    device: Literal["cuda"] = Field(
        default="cuda",
        title="计算设备",
        description="当前实验入口要求 CUDA。",
        json_schema_extra={"x-group": "algorithm"},
    )


class MultiStartAdamSiteConfig(SiteDecisionConfig):
    starts_per_weight: int = Field(default=8, ge=1, title="每个权重的起点数量", json_schema_extra={"x-group": "algorithm"})
    max_steps: int = Field(default=80, ge=1, title="迭代步数", json_schema_extra={"x-group": "algorithm"})
    learning_rate: float = Field(default=0.05, gt=0, title="学习率", json_schema_extra={"x-group": "algorithm"})
    init_eps: float = Field(
        default=0.01,
        gt=0,
        lt=0.5,
        title="起点边界余量",
        description="起点采样离开参数边界的比例。",
        json_schema_extra={"x-group": "algorithm"},
    )
    device: Literal["cuda"] = Field(
        default="cuda",
        title="计算设备",
        description="当前实验入口要求 CUDA。",
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
        "预计产物包括 solutions.csv、pareto_solutions.csv、pareto_footprints_map.png 和 pareto_3d_interactive.html。"
    )
    model = GuidedSiteConfig
    expected_artifacts = (
        "solutions.csv",
        "pareto_solutions.csv",
        "pareto_footprints_map.png",
        "pareto_3d_interactive.html",
    )


class CmaEsSitePlugin(_SitePlugin):
    id = "site.cma_es"
    algorithm = "cma_es"
    plugin_name = "CMA-ES 选址"
    plugin_description = (
        "读取已构建的场景，再沿项目配置里的权重网格运行现有 CMA-ES 入口，写出帕累托方案。"
        "预计产物包括 solutions.csv、pareto_solutions.csv、pareto_footprints_map.png 和 pareto_3d_interactive.html。"
    )
    model = CmaEsSiteConfig
    expected_artifacts = (
        "solutions.csv",
        "pareto_solutions.csv",
        "pareto_footprints_map.png",
        "pareto_3d_interactive.html",
    )


class PrepareSceneConfig(BaseModel):
    """Fields for the offline data stage. This model does not start a search."""

    model_config = ConfigDict(extra="forbid")

    scene_name: str = Field(
        default="cangnan",
        min_length=1,
        title="场景",
        description="写入 scenes/ 下的这个目录。已有同名场景会被这次构建更新。",
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
        from experiments.scene_store import prepare_scene

        scene_name = parsed.scene_name if hasattr(parsed, "scene_name") else config["scene_name"]
        path = prepare_scene(str(scene_name), reporter)
        return PluginResult(
            status="succeeded",
            metrics={},
            data={"optimizer_executed": False, "scene_id": path.name, "stage": "scene"},
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
