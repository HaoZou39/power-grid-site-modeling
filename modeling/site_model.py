"""目标和硬约束的类。

一个目标是一个 `SiteObjective` 子类，一条硬约束是一个 `SiteConstraint` 子类。
`SiteModel` 把当前要用的目标和约束装在一起。搜索只调用它，不重写公式。
具体数值公式仍在 `dem_model.py`、`road_model.py`、`demand_model.py`、`obstacle_model.py`。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import torch

from .demand_model import compute_demand_distance_loss
from .dem_model import compute_dem_hard_loss, compute_dem_soft_loss
from .masks import compute_hard_footprint_indices, compute_soft_footprint
from .obstacle_model import compute_obstacle_hard_loss, compute_obstacle_soft_loss
from .road_model import compute_road_distance_loss


@dataclass
class ObjectiveBatch:
    """一批站址和计算目标时允许读取的张量。

    `footprint` 是这批站址共用的软足迹。子类从这里取输入，不再自己找数据文件。
    """

    dem_tensor: torch.Tensor
    obstacle_tensor: torch.Tensor
    road_segments_tensor: torch.Tensor
    road_voronoi_tensor: torch.Tensor
    demand_points_tensor: torch.Tensor
    demand_weights_tensor: torch.Tensor | None
    pose_batch: torch.Tensor
    rect_w_m: float
    rect_h_m: float
    soft_mask_sharpness: float
    footprint: dict[str, torch.Tensor]


class SiteObjective(ABC):
    """一个目标。

    `name` 要和 `OBJECTIVE_NAMES` 里的名字一致，软惩罚 `obstacle_soft` 除外。
    子类的 `evaluate` 返回 shape `[B]` 的张量。改公式时优先改对应的 `*_model.py`。
    """

    name: str = ""

    @abstractmethod
    def evaluate(self, batch: ObjectiveBatch) -> torch.Tensor:
        """Return one value per pose, shape ``[B]``."""


class DemSoft(SiteObjective):
    """地形平整度。数值来自 `dem_model.compute_dem_soft_loss`。"""

    name = "dem_soft"

    def evaluate(self, batch: ObjectiveBatch) -> torch.Tensor:
        return compute_dem_soft_loss(batch.dem_tensor, batch.footprint["grid"], batch.footprint["weights"])


class ObstacleSoft(SiteObjective):
    """不可建设区域的软重叠。它是惩罚项，不是帕累托比较用的三个目标之一。"""

    name = "obstacle_soft"

    def evaluate(self, batch: ObjectiveBatch) -> torch.Tensor:
        return compute_obstacle_soft_loss(batch.obstacle_tensor, batch.footprint["grid"], batch.footprint["weights"])


class RoadDistance(SiteObjective):
    """站址中心到道路的距离。数值来自 `road_model.compute_road_distance_loss`。"""

    name = "road_distance"

    def evaluate(self, batch: ObjectiveBatch) -> torch.Tensor:
        return compute_road_distance_loss(batch.road_segments_tensor, batch.road_voronoi_tensor, batch.pose_batch)


class DemandDistance(SiteObjective):
    """站址中心到需求点的加权距离。数值来自 `demand_model.compute_demand_distance_loss`。"""

    name = "demand_distance"

    def evaluate(self, batch: ObjectiveBatch) -> torch.Tensor:
        return compute_demand_distance_loss(batch.demand_points_tensor, batch.demand_weights_tensor, batch.pose_batch)


class SiteConstraint(ABC):
    """一条硬约束。

    `metrics` 必须返回 `constraint_violation`。数值为 0 表示这批站址可行。
    新增坡度、进站等限制时继承这个类，并在 `default_site_model` 里换上新对象。
    """

    @abstractmethod
    def metrics(
        self,
        dem: np.ndarray,
        obstacle_mask: np.ndarray,
        pose_batch: torch.Tensor,
        rect_w_m: float,
        rect_h_m: float,
        device: str = "cuda",
    ) -> dict[str, torch.Tensor]:
        """Return hard metrics. ``constraint_violation`` of 0 means feasible."""


class ObstacleCountConstraint(SiteConstraint):
    """当前的硬约束：建筑足迹压到禁止格则不可行。

    违例等于压到的格子数。地形硬方差和硬极差一并返回，只用于报告。
    """

    def metrics(
        self,
        dem: np.ndarray,
        obstacle_mask: np.ndarray,
        pose_batch: torch.Tensor,
        rect_w_m: float,
        rect_h_m: float,
        device: str = "cuda",
    ) -> dict[str, torch.Tensor]:
        hard_indices = compute_hard_footprint_indices(pose_batch, rect_w_m, rect_h_m, dem.shape)
        dem_metrics = compute_dem_hard_loss(dem, hard_indices, device=device)
        obstacle_metrics = compute_obstacle_hard_loss(obstacle_mask, hard_indices, device=device)
        violation = obstacle_metrics["obstacle_hard_count"]
        return {**dem_metrics, **obstacle_metrics, "constraint_violation": violation, "is_feasible": violation == 0}


class SiteModel:
    """一次搜索使用的目标列表和硬约束。

    换掉 `objectives` 里的某个子类就换了对应目标。换掉 `constraint` 就换了可行性规则。
    目标名字不能重复。
    """

    def __init__(self, objectives: tuple[SiteObjective, ...], constraint: SiteConstraint) -> None:
        names = [item.name for item in objectives]
        if len(names) != len(set(names)):
            raise ValueError(f"objective names must be unique, got {names}")
        self.objectives = objectives
        self.constraint = constraint

    def evaluate_objectives(
        self,
        dem_tensor: torch.Tensor,
        obstacle_tensor: torch.Tensor,
        road_segments_tensor: torch.Tensor,
        road_voronoi_tensor: torch.Tensor,
        demand_points_tensor: torch.Tensor,
        demand_weights_tensor: torch.Tensor | None,
        pose_batch: torch.Tensor,
        rect_w_m: float,
        rect_h_m: float,
        soft_mask_sharpness: float,
    ) -> dict[str, torch.Tensor]:
        footprint = compute_soft_footprint(pose_batch, rect_w_m, rect_h_m, dem_tensor.shape[-2:], soft_mask_sharpness)
        batch = ObjectiveBatch(
            dem_tensor,
            obstacle_tensor,
            road_segments_tensor,
            road_voronoi_tensor,
            demand_points_tensor,
            demand_weights_tensor,
            pose_batch,
            rect_w_m,
            rect_h_m,
            soft_mask_sharpness,
            footprint,
        )
        return {item.name: item.evaluate(batch) for item in self.objectives}

    def hard_metrics(
        self,
        dem: np.ndarray,
        obstacle_mask: np.ndarray,
        pose_batch: torch.Tensor,
        rect_w_m: float,
        rect_h_m: float,
        device: str = "cuda",
    ) -> dict[str, torch.Tensor]:
        return self.constraint.metrics(dem, obstacle_mask, pose_batch, rect_w_m, rect_h_m, device)


def default_site_model() -> SiteModel:
    """默认模型：三个帕累托目标、软重叠惩罚，以及按禁止格计数的硬约束。"""

    return SiteModel(
        (DemSoft(), ObstacleSoft(), RoadDistance(), DemandDistance()),
        ObstacleCountConstraint(),
    )
