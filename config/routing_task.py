"""Routing task schemas shared by plugins, CLI and experiments."""

from dataclasses import asdict, fields
import math
from typing import Annotated, get_type_hints

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, create_model, model_validator

from config.project_config import PilotRoutingConfig, RoutingConfig, load_default_config, parse_pilot_config

_DEFAULTS = load_default_config()
_TYPES = get_type_hints(RoutingConfig)


def _pilot_parameters(value):
    # Saved tasks predate newly added research parameters; resolve them from JSON.
    if isinstance(value, dict):
        missing_initialization_mode = "initialization_mode" not in value
        defaults = asdict(_DEFAULTS.routing.pilot)
        value = {**defaults, **value}
        if missing_initialization_mode:
            # Historical pilot tasks used the legacy reference initializer.
            value["initialization_mode"] = "legacy"
        if isinstance(value.get("core"), dict):
            value["core"] = {**defaults["core"], **value["core"]}
    return parse_pilot_config(value)


def _fill_generations(value):
    # Tasks saved before generation stopping keep their previous generation ceiling.
    if isinstance(value, dict) and "max_generations" not in value:
        evaluations, population = value.get("max_evaluations"), value.get("popsize")
        if type(evaluations) is int and type(population) is int and population > 0:
            value = {**value, "max_generations": math.ceil(evaluations / population)}
    return value


def _ensure_generations(cls, value):
    return _fill_generations(value)


_TYPES["pilot"] = Annotated[PilotRoutingConfig, BeforeValidator(_pilot_parameters)]
RoutingParameters = create_model("RoutingParameters", __config__=ConfigDict(extra="forbid", strict=True), __validators__={
    "_ensure_generations": model_validator(mode="before")(_ensure_generations),
}, **{
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
    algorithm: Annotated[RoutingParameters, BeforeValidator(_fill_generations)] = Field(default_factory=RoutingParameters, title="算法配置")
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


