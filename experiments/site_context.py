"""Prepare siting constraints and haul fields from a published scene."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np

from config.project_config import ModelingConfig
from experiments.constraint_mask import (
    LandusePolicy, access_policy, compose_constraint_masks, parse_max_elevation,
    polygons_from_form, policy_from_form, rasterize_exclusions,
)
from experiments.protected_farmland import access_road_width_m, burn_farmland, dilate_mask
from modeling.context import SiteProblemContext
from modeling.haul_field import HaulField


def access_constraint_mask(landuse: np.ndarray, policy: LandusePolicy,
                           feasible: list[list[tuple[float, float]]], farmland: np.ndarray | None) -> np.ndarray:
    """Hard access mask before applying the road-width buffer to permanent farmland."""
    hard, _ = compose_constraint_masks(landuse, [], access_policy(policy), feasible)
    return burn_farmland(hard, hard, farmland)[0]


def access_connector_mask(farmland: np.ndarray | None) -> np.ndarray | None:
    return None if farmland is None else dilate_mask(farmland, access_road_width_m())


def walkable_access_cells(hard: np.ndarray, connector_blocked: np.ndarray | None) -> np.ndarray:
    walkable = hard == 0
    return walkable if connector_blocked is None else walkable & ~connector_blocked


def haul_origin(form: dict[str, Any]) -> tuple[float, float] | None:
    """进货原点。不填就不比较沿路运输长度。"""

    x = form.get("origin_x")
    y = form.get("origin_y")
    if x is None and y is None:
        return None
    if x is None or y is None:
        raise ValueError("进货原点需要同时给出 x 和 y")
    return float(x), float(y)


def constrained_problem(form: dict[str, Any], device: Any, modeling: ModelingConfig) -> tuple[SiteProblemContext, dict[str, Any]]:
    from experiments.scene_store import DEFAULT_SCENE, read_scene_snapshot
    name = str(form.get("scene_name") or DEFAULT_SCENE)
    snapshot = read_scene_snapshot(name, writable=True)
    expected = form.get("expected_revision")
    if expected and snapshot["metadata"]["data_version"]["scene_revision"] != expected:
        raise ValueError("场景版本已变化，请刷新后重新计算。")
    return _constrained_problem(form, device, modeling, snapshot=snapshot)


def _constrained_problem(
    form: dict[str, Any], device: Any, modeling: ModelingConfig, *, snapshot: dict,
) -> tuple[SiteProblemContext, dict[str, Any]]:
    """已构建的场景加上表单里的用地策略、禁区和可行域。"""

    from experiments.problem_context import with_constraint_masks
    from experiments.scene_store import DEFAULT_SCENE, load_scene
    from modeling.context import require_road_setback_m, require_water_setback_m

    max_elevation_m = parse_max_elevation(form.get("max_elevation_m"))
    setback = require_road_setback_m(form.get("road_setback_m", modeling.road_setback_m))
    water_setback = require_water_setback_m(form.get("water_setback_m", modeling.water_setback_m))
    problem, metadata = load_scene(
        str(form.get("scene_name") or DEFAULT_SCENE),
        device,
        road_setback_m=setback,
        water_setback_m=water_setback,
        highway_setback_m=require_road_setback_m(form.get("highway_setback_m", modeling.highway_setback_m)),
        snapshot=snapshot,
    )
    zones = polygons_from_form(form)
    feasible = polygons_from_form(form, "feasible_zones")

    # 禁区和遥感道路类别 3 只禁止建站。进站掩膜不含这两者，建站掩膜保留类别 3 再叠禁区。
    policy = policy_from_form(form)
    hard_mask, soft_mask = compose_constraint_masks(problem.landuse, [], policy, feasible)
    hard_mask, soft_mask = burn_farmland(hard_mask, soft_mask, snapshot["farmland"])
    access_mask = access_constraint_mask(problem.landuse, policy, feasible, snapshot["farmland"])
    if zones:
        drawn = rasterize_exclusions(zones, hard_mask.shape)
        hard_mask = np.maximum(hard_mask, drawn)
        soft_mask = np.maximum(soft_mask, drawn)
    connector_blocked = access_connector_mask(snapshot["farmland"])
    metadata = {
        **metadata,
        "field_policy": str(form.get("field_policy") or "allowed"),
        "mountain_policy": str(form.get("mountain_policy") or "allowed"),
        "field_cost": float(form.get("field_cost", 0.5)),
        "exclusion_zone_count": len(zones),
        "feasible_zone_count": len(feasible),
        "road_setback_m": setback,
        "water_setback_m": water_setback,
        "highway_setback_m": float(form.get("highway_setback_m", modeling.highway_setback_m)),
        "max_elevation_m": max_elevation_m,
        "elevation_unit": "m",
        # 场景 DEM 只记录源 CRS 和米制重采样，没有垂直基准。
        "elevation_vertical_datum": None,
    }
    problem = with_constraint_masks(
        problem,
        hard_mask,
        soft_mask,
        road_setback_m=setback,
        water_setback_m=water_setback,
        access_mask=access_mask,
        max_elevation_m=max_elevation_m,
    )
    problem = replace(
        problem,
        initialization_feasible_zones=tuple(tuple(ring) for ring in feasible),
        initialization_exclusion_zones=tuple(tuple(ring) for ring in zones),
        access_connector_blocked=connector_blocked,
    )
    return problem, metadata


def shared_haul_field(
    problem: SiteProblemContext,
    metadata: dict[str, Any],
    form: dict[str, Any],
    access_elevation_weight: float = 1.0,
) -> HaulField:
    """Use the scene volume so Worker and API can share one compatible field."""

    from experiments.haul_field_cache import (
        compatible_haul_field,
        get_or_build_haul_field,
        haul_memory_identity,
        remember_compatible_haul_field,
    )
    origin = haul_origin(form)
    identity = haul_memory_identity(
        metadata["scene_dir"],
        form,
        origin,
        access_elevation_weight,
        uses_landuse=True,
        diagonal=True,
        source_signature=metadata.get("scene_signature"),
    )
    # 只改禁区时道路掩膜不变，同一进程直接复用已校验的距离场，不再读约 2 GB 的磁盘缓存。
    reused = compatible_haul_field(identity)
    if reused is not None:
        return reused
    connector_blocked = problem.access_connector_blocked
    walkable = walkable_access_cells(problem.obstacle_mask, connector_blocked)
    result = get_or_build_haul_field(
        metadata["scene_dir"],
        problem.dem,
        walkable,
        problem.road_segments,
        origin,
        form,
        uses_landuse=True,
        access_elevation_weight=access_elevation_weight,
        connector_blocked=connector_blocked,
        segment_kinds=problem.road_segment_kinds,
        source_signature=metadata.get("scene_signature"),
    )
    # The disk key already checked this field. Later reports reuse the object, not a copy.
    remember_compatible_haul_field(identity, result.field)
    return result.field
