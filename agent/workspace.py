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


class WorkspaceSnapshot(_Model):
    scene_name: str = Field(min_length=1)
    site: SiteSize
    building: SiteSize
    policies: Policies
    origin: Point | None
    regions: list[Region]
    poses: list[Pose]
    selected_pose_id: str | None
    experiment_id: str | None = None


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


_EDIT_OP_MODELS = (
    SetBuilding,
    SetPolicies,
    SetOrigin,
    ClearOrigin,
    AddRegion,
    RemoveRegion,
    UpdatePose,
    SelectPose,
    RunSearch,
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
        return self


def edit_op_kinds() -> list[str]:
    return [get_args(model.model_fields["kind"].annotation)[0] for model in _EDIT_OP_MODELS]


def validate_ops(snapshot: WorkspaceSnapshot, ops: list[EditOp]) -> None:
    """Reject a proposal that the map cannot apply. Checks run in order."""

    if not ops:
        raise ValueError("提案没有任何操作")
    width = snapshot.site.width_m
    height = snapshot.site.height_m
    regions = {region.id for region in snapshot.regions}
    poses = {pose.id: (pose.x, pose.y, pose.theta) for pose in snapshot.poses}
    for index, op in enumerate(ops, start=1):
        try:
            _check_op(op, regions, poses, width, height)
        except ValueError as exc:
            raise ValueError(f"第 {index} 个操作无效：{exc}") from exc


def _check_op(
    op: EditOp,
    regions: set[str],
    poses: dict[str, tuple[float, float, float]],
    width: float,
    height: float,
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
    elif isinstance(op, SelectPose):
        if op.pose_id not in poses:
            raise ValueError(f"没有这个方案：{op.pose_id}")
    elif not isinstance(op, (ClearOrigin, RunSearch)):
        raise ValueError(f"不认识的操作：{op}")


def _positive_size(width_m: float, height_m: float) -> None:
    if not math.isfinite(width_m) or not math.isfinite(height_m) or width_m <= 0 or height_m <= 0:
        raise ValueError("建筑宽和高必须大于 0")


def _field_cost(value: float) -> None:
    if not math.isfinite(value) or value <= 0 or value > 1:
        raise ValueError("农田代价系数必须在 0 到 1 之间")


def _inside(x: float, y: float, width: float, height: float) -> None:
    if not math.isfinite(x) or not math.isfinite(y) or x < 0 or y < 0 or x > width or y > height:
        raise ValueError("坐标不在选址范围内")
