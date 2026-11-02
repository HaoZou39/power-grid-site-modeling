"""Explicit whole-workspace evaluation; no search and no partial publication."""
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.domain.plugins import PluginResult, PluginSpec
from plugins.site_plugin import SiteDecisionConfig, _DEFAULTS
from plugins.schema import plugin_schema


class EvaluationPose(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(min_length=1)
    x: float
    y: float
    theta: float


class ReevaluateConfig(SiteDecisionConfig):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    origin_x: float | None = None
    origin_y: float | None = None
    include_demand: bool = _DEFAULTS.guided_search.include_demand
    diagonal_access: bool = _DEFAULTS.guided_search.diagonal_access
    expected_revision: str = Field(min_length=1)
    poses: list[EvaluationPose] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self):
        if (self.origin_x is None) != (self.origin_y is None):
            raise ValueError("进货原点需要同时给出 x 和 y")
        if len({p.id for p in self.poses}) != len(self.poses):
            raise ValueError("评价方案 id 不能重复")
        return self


class ReevaluatePosesPlugin:
    id = "site.reevaluate_poses"
    version = "0.1.0"

    def describe(self):
        return PluginSpec(self.id, self.version, "evaluation", "重新评价旧方案", "固定场景版本，评价全部指定位置，不搜索。",
                          plugin_schema(ReevaluateConfig))

    def validate_config(self, config: dict[str, Any]):
        ReevaluateConfig.model_validate(config)

    def run(self, config, reporter):
        from dataclasses import replace
        from config.project_config import load_default_config, resolve_guided_search_device
        from experiments.launch_site_run import constrained_problem, _shared_haul_field, _haul_origin
        from algorithms.guided_search.search import pose_records

        parsed = ReevaluateConfig.model_validate(config)
        form = parsed.model_dump(exclude={"poses"})
        defaults = load_default_config()
        device = resolve_guided_search_device(defaults.modeling.device)
        modeling = replace(defaults.modeling, rect_w_m=parsed.rect_w_m, rect_h_m=parsed.rect_h_m, device=str(device))
        reporter(0.02, "context", "正在读取本轮评价的场景快照")
        problem, metadata = constrained_problem(form, device, modeling)
        reporter(0.1, "haul_field", "正在准备共享距离场")
        field = _shared_haul_field(problem, metadata, form, defaults.guided_search.access_elevation_weight)
        items = []
        for start in range(0, len(parsed.poses), 200):
            reporter(0.2 + 0.75 * start / len(parsed.poses), "evaluating", f"正在评价 {start}/{len(parsed.poses)} 个方案")
            group = parsed.poses[start:start + 200]
            records = pose_records(problem, modeling, _haul_origin(form),
                                   np.asarray([(p.x, p.y, p.theta) for p in group]), field=field)
            items.extend({"id": pose.id, "pose": pose.model_dump(), "metrics": metrics}
                         for pose, metrics in zip(group, records, strict=True))
        reporter(1, "publishing", "评价完成，正在发布整轮结果")
        return PluginResult("succeeded", {"pose_count": len(items)},
                            {"items": items, "data_version": metadata["data_version"], "coordinate_context": metadata["coordinate_context"]})
