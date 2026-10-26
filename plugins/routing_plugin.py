"""Explicit routing job configuration, independent of site plugin inheritance."""

from dataclasses import fields
from typing import get_type_hints

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from backend.app.domain.plugins import PluginResult, PluginSpec
from config.project_config import RoutingConfig, load_default_config
from plugins.schema import plugin_schema

_DEFAULTS = load_default_config()
_TYPES = get_type_hints(RoutingConfig)
RoutingParameters = create_model("RoutingParameters", __config__=ConfigDict(extra="forbid", strict=True), **{
    field.name: (_TYPES[field.name], Field(default=getattr(_DEFAULTS.routing, field.name)))
    for field in fields(RoutingConfig)
})


class ConnectionPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, title="经度")
    lat: float = Field(ge=-90, le=90, title="纬度")


class RoutingRunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    scene_name: str = Field(default=_DEFAULTS.default_scene, min_length=1, title="场景")
    experiment_name: str = Field(min_length=1, title="实验名称")
    overwrite_existing: bool = False
    start: ConnectionPoint
    end: ConnectionPoint
    max_span_m: float = Field(gt=0, strict=True, title="最大档距（m）")
    tower_radius_m: float = Field(gt=0, strict=True, title="塔基控制半径（m）")
    max_turn_deg: float = Field(ge=0, le=180, strict=True, title="最大允许转角（°）")
    road_setback_m: float = Field(default=_DEFAULTS.modeling.road_setback_m, ge=0, title="普通道路控制距离（m）")
    highway_setback_m: float = Field(default=_DEFAULTS.modeling.highway_setback_m, ge=0, title="高速及匝道控制距离（m）")
    algorithm: RoutingParameters = Field(default_factory=RoutingParameters, title="算法配置")
    no_tower_zones: list[list[tuple[float, float]]] = Field(default_factory=list, title="禁止落塔区域（局部米坐标）")
    no_cross_zones: list[list[tuple[float, float]]] = Field(default_factory=list, title="禁止跨越区域（局部米坐标）")

    @model_validator(mode="after")
    def validate_task(self):
        RoutingConfig(**self.algorithm.model_dump())
        for value in (self.scene_name, self.experiment_name):
            if value.strip() in {"", ".", ".."} or "/" in value or "\\" in value:
                raise ValueError("scene and experiment names must be single directory names")
        if self.start == self.end:
            raise ValueError("start and end must be different connection points")
        from shapely.geometry import Polygon
        for ring in [*self.no_tower_zones, *self.no_cross_zones]:
            if len(ring) < 3:
                raise ValueError("region requires at least three points")
            polygon = Polygon(ring)
            if not polygon.is_valid or polygon.area <= 0:
                raise ValueError("region must be a valid polygon with positive area")
        return self


class RoutingPlugin:
    id = "routing.nsga2"
    version = "0.1.0"

    def describe(self) -> PluginSpec:
        schema = plugin_schema(RoutingRunConfig)
        # Generic forms and the routing UI share the resolved schema defaults.
        schema["properties"]["algorithm"]["default"] = _DEFAULTS.routing.__dict__.copy()
        return PluginSpec(self.id, self.version, "algorithm", "四目标杆塔选线",
            "固定接入点，优化新增塔数、DEM三维长度、水平曲折度与等权跨越长度；净空未校核。", schema)

    def validate_config(self, config: dict) -> None:
        RoutingRunConfig.model_validate(config)

    def run(self, config: dict, reporter) -> PluginResult:
        from experiments.launch_routing_run import launch_routing_run
        directory = launch_routing_run(RoutingRunConfig.model_validate(config), reporter)
        return PluginResult("succeeded", {}, {"experiment_id": directory.name, "problem_type": "routing",
            "optimizer_executed": True, "expected_artifacts": ["routes.json", "run_summary.json", "solutions.csv", "pareto_solutions.csv"]})
