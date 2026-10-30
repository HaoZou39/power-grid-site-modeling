"""Workspace snapshot and the only write contract the assistant may emit.

Coordinates are 1 m local meters. The origin is the top-left of the site frame,
x increases east, and y increases south. theta is radians; 0 faces the width edge east.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal, Union, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.memory import MemoryOp


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SiteSize(_Model):
    width_m: float = Field(gt=0)
    height_m: float = Field(gt=0)


class Policies(_Model):
    mountain_policy: Literal["blocked", "allowed"]
    field_policy: Literal["blocked", "allowed", "costly"]
    field_cost: float


class Point(_Model):
    x: float
    y: float


class Region(_Model):
    id: str = Field(min_length=1)
    kind: Literal["exclusion", "feasible"]
    ring: list[Point]


class Pose(_Model):
    id: str = Field(min_length=1)
    x: float
    y: float
    theta: float
    objectives: dict[str, float] | None = None
    feasible: bool | None = None
    # 由哪个方案局部优化得到。优化器原本给出的方案没有这一项。
    derived_from: str | None = None


class LayerState(_Model):
    visible: bool = False
    available: bool = False


class DemLayerState(LayerState):
    opacity: float = Field(default=0.6, ge=0, le=1)


class LanduseLayerState(_Model):
    field: LayerState = Field(default_factory=LayerState)
    building: LayerState = Field(default_factory=LayerState)
    road: LayerState = Field(default_factory=LayerState)
    water: LayerState = Field(default_factory=LayerState)


class RegionLayerState(_Model):
    exclusion: bool = True
    feasible: bool = True


class WorkspaceLayers(_Model):
    panel_open: bool = False
    scene_ready: bool = False
    dem: DemLayerState = Field(default_factory=DemLayerState)
    landuse: LanduseLayerState = Field(default_factory=LanduseLayerState)
    osm_roads: LayerState = Field(default_factory=LayerState)
    regions: RegionLayerState = Field(default_factory=RegionLayerState)


class WorkspaceSnapshot(_Model):
    problem_type: Literal["site", "routing"] = "site"
    scene_name: str = Field(min_length=1)
    site: SiteSize
    building: SiteSize
    policies: Policies
    origin: Point | None
    regions: list[Region]
    poses: list[Pose]
    selected_pose_id: str | None
    experiment_id: str | None = None
    layers: WorkspaceLayers = Field(default_factory=WorkspaceLayers)


class SetBuilding(_Model):
    kind: Literal["set_building"]
    width_m: float
    height_m: float


class SetPolicies(_Model):
    kind: Literal["set_policies"]
    mountain_policy: Literal["blocked", "allowed"] | None = None
    field_policy: Literal["blocked", "allowed", "costly"] | None = None
    field_cost: float | None = None


class SetOrigin(_Model):
    kind: Literal["set_origin"]
    x: float
    y: float


class ClearOrigin(_Model):
    kind: Literal["clear_origin"]


class ClearPoses(_Model):
    kind: Literal["clear_poses"]


class AddRegion(_Model):
    kind: Literal["add_region"]
    region_kind: Literal["exclusion", "feasible"]
    ring: list[Point]


class RemoveRegion(_Model):
    kind: Literal["remove_region"]
    region_id: str = Field(min_length=1)


class UpdatePose(_Model):
    kind: Literal["update_pose"]
    pose_id: str = Field(min_length=1)
    x: float | None = None
    y: float | None = None
    theta: float | None = None


class SelectPose(_Model):
    kind: Literal["select_pose"]
    pose_id: str = Field(min_length=1)


class RunSearch(_Model):
    kind: Literal["run_search"]
    plugin_id: Literal["site.guided_search"]


class RefinePose(_Model):
    """在方案周围边长 2×half_width_m 的方框里再跑一次 site.guided_search。界限与前端 REFINE_HALF_WIDTH_M 一致。"""

    kind: Literal["refine_pose"]
    pose_id: str = Field(min_length=1)
    half_width_m: float = Field(default=150, ge=30, le=400)


class SetLayerVisibility(_Model):
    kind: Literal["set_layer_visibility"]
    layer: Literal["dem", "field", "building", "road", "water", "osm_roads", "exclusion", "feasible"]
    visible: bool


class SetDemOpacity(_Model):
    kind: Literal["set_dem_opacity"]
    opacity: float = Field(ge=0, le=1)


class SetLayerPanelOpen(_Model):
    kind: Literal["set_layer_panel_open"]
    open: bool


_EDIT_OP_MODELS = (
    SetBuilding,
    SetPolicies,
    SetOrigin,
    ClearOrigin,
    ClearPoses,
    AddRegion,
    RemoveRegion,
    UpdatePose,
    SelectPose,
    RunSearch,
    RefinePose,
    SetLayerVisibility,
    SetDemOpacity,
    SetLayerPanelOpen,
)
EditOp = Annotated[Union[_EDIT_OP_MODELS], Field(discriminator="kind")]


class Proposal(_Model):
    rationale: str = Field(min_length=1)
    ops: list[EditOp] = Field(default_factory=list)
    memory: list[MemoryOp] = Field(default_factory=list)

    @model_validator(mode="after")
    def _not_empty(self) -> Proposal:
        if not self.ops and not self.memory:
            raise ValueError("提案没有任何操作")
        if any(isinstance(op, ClearPoses) for op in self.ops) and self.memory:
            raise ValueError("清空方案不能和记忆修改放在同一个提案里")
        return self


def edit_op_kinds() -> list[str]:
    return [get_args(model.model_fields["kind"].annotation)[0] for model in _EDIT_OP_MODELS]


def validate_ops(snapshot: WorkspaceSnapshot, ops: list[EditOp]) -> None:
    """Reject a proposal that the map cannot apply. Checks run in order."""

    if snapshot.problem_type == "routing":
        raise ValueError("选线模式不支持站址编辑，请使用选线面板")
    if not ops:
        raise ValueError("提案没有任何操作")
    clear_poses = sum(isinstance(op, ClearPoses) for op in ops)
    if clear_poses:
        if len(ops) != 1:
            raise ValueError("清空方案必须是提案中唯一的地图操作")
        if not snapshot.poses:
            raise ValueError("当前没有方案可以清空")
    if snapshot.poses and any(isinstance(op, (SetOrigin, ClearOrigin)) for op in ops):
        raise ValueError("当前方案已绑定进货原点，请先清空当前方案后再修改")
    refines = sum(isinstance(op, RefinePose) for op in ops)
    if refines > 1:
        raise ValueError("一次只能局部优化一个方案")
    if refines and any(isinstance(op, RunSearch) for op in ops):
        raise ValueError("重新搜索和局部优化不能放在同一个提案里")
    width = snapshot.site.width_m
    height = snapshot.site.height_m
    regions = {region.id for region in snapshot.regions}
    poses = {pose.id: (pose.x, pose.y, pose.theta) for pose in snapshot.poses}
    for index, op in enumerate(ops, start=1):
        try:
            _check_op(op, regions, poses, width, height, snapshot.layers)
        except ValueError as exc:
            raise ValueError(f"第 {index} 个操作无效：{exc}") from exc


def _check_op(
    op: EditOp,
    regions: set[str],
    poses: dict[str, tuple[float, float, float]],
    width: float,
    height: float,
    layers: WorkspaceLayers,
) -> None:
    if isinstance(op, SetBuilding):
        _positive_size(op.width_m, op.height_m)
    elif isinstance(op, SetPolicies):
        if op.mountain_policy is None and op.field_policy is None and op.field_cost is None:
            raise ValueError("策略修改至少要改一项")
        if op.field_cost is not None:
            _field_cost(op.field_cost)
    elif isinstance(op, SetOrigin):
        _inside(op.x, op.y, width, height)
    elif isinstance(op, AddRegion):
        if len(op.ring) < 3:
            raise ValueError("范围至少需要三个顶点")
        for point in op.ring:
            _inside(point.x, point.y, width, height)
    elif isinstance(op, RemoveRegion):
        if op.region_id not in regions:
            raise ValueError(f"没有这个范围：{op.region_id}")
        regions.remove(op.region_id)
    elif isinstance(op, UpdatePose):
        if op.pose_id not in poses:
            raise ValueError(f"没有这个方案：{op.pose_id}")
        if op.x is None and op.y is None and op.theta is None:
            raise ValueError("修改方案至少要改一项")
        current = poses[op.pose_id]
        x = current[0] if op.x is None else op.x
        y = current[1] if op.y is None else op.y
        theta = current[2] if op.theta is None else op.theta
        _inside(x, y, width, height)
        if not math.isfinite(theta):
            raise ValueError("朝向必须是有限数值")
        poses[op.pose_id] = (x, y, theta)
    elif isinstance(op, (SelectPose, RefinePose)):
        if op.pose_id not in poses:
            raise ValueError(f"没有这个方案：{op.pose_id}")
    elif isinstance(op, SetLayerVisibility):
        if op.visible and op.layer in {"dem", "field", "building", "road", "water", "osm_roads"}:
            _available_layer(op.layer, layers)
    elif isinstance(op, SetDemOpacity):
        _available_layer("dem", layers)
    elif isinstance(op, SetLayerPanelOpen):
        pass
    elif not isinstance(op, (ClearOrigin, ClearPoses, RunSearch)):
        raise ValueError(f"不认识的操作：{op}")


def _available_layer(layer: str, layers: WorkspaceLayers) -> None:
    if not layers.scene_ready:
        raise ValueError("场景尚未准备完成，无法使用这个 GIS 图层")
    state = layers.osm_roads if layer == "osm_roads" else layers.dem if layer == "dem" else getattr(layers.landuse, layer)
    if not state.available:
        raise ValueError(f"当前场景没有可用的 {layer} 图层资源")


def _positive_size(width_m: float, height_m: float) -> None:
    if not math.isfinite(width_m) or not math.isfinite(height_m) or width_m <= 0 or height_m <= 0:
        raise ValueError("建筑宽和高必须大于 0")


def _field_cost(value: float) -> None:
    if not math.isfinite(value) or value <= 0 or value > 1:
        raise ValueError("农田代价系数必须在 0 到 1 之间")


def _inside(x: float, y: float, width: float, height: float) -> None:
    if not math.isfinite(x) or not math.isfinite(y) or x < 0 or y < 0 or x > width or y > height:
        raise ValueError("坐标不在选址范围内")
