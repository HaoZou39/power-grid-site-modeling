"""Build the one shared site data context used by all algorithm runners."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import numpy as np
import torch

from config.project_config import ProjectConfig
from data_tools.dem_tool import build_dem_product
from data_tools.demand_tool import generate_demand_points
from data_tools.io_utils import write_json
from data_tools.landuse_tool import build_landuse_product
from data_tools.traffic_tool import build_road_product
from modeling.context import (
    SiteProblemContext,
    merge_building_hard_mask,
    highway_building_buffer,
    rasterize_osm_centerlines,
    require_road_setback_m,
    require_water_setback_m,
    road_building_buffer,
    water_building_buffer,
)


def _tensor_4d(
    array: np.ndarray,
    device: torch.device,
    dtype: torch.dtype = torch.float32,
) -> torch.Tensor:
    return torch.as_tensor(array, dtype=dtype, device=device)[None, None, :, :]


def context_from_arrays(
    arrays: dict[str, np.ndarray],
    device: torch.device,
    road_setback_m: float,
    water_setback_m: float,
    highway_setback_m: float,
) -> SiteProblemContext:
    """Turn saved scene arrays into the tensors used by a search."""

    dem = arrays["dem"]
    obstacle_mask = arrays["obstacle_mask"]
    road_segments = arrays["road_segments"]
    road_voronoi = arrays["road_voronoi"]
    kinds = arrays["road_segment_kinds"]
    demand_points = arrays["demand_points"]
    if "landuse" not in arrays:
        raise ValueError("landuse is required to build the road setback")
    landuse = arrays["landuse"]
    if road_voronoi.shape != dem.shape or obstacle_mask.shape != dem.shape or landuse.shape != dem.shape:
        raise ValueError(
            f"scene grids must share one shape, got dem {dem.shape}, "
            f"obstacle {obstacle_mask.shape}, landuse {landuse.shape}, voronoi {road_voronoi.shape}"
        )
    if demand_points.ndim != 2 or demand_points.shape[1] != 2:
        raise ValueError(f"demand_points must have shape [N, 2], got {demand_points.shape}")
    setback = require_road_setback_m(road_setback_m)
    water_setback = require_water_setback_m(water_setback_m)
    osm_road_mask = rasterize_osm_centerlines(road_segments[kinds == 0], dem.shape)
    road_buffer = road_building_buffer(landuse, osm_road_mask, setback)
    water_buffer = water_building_buffer(landuse, water_setback)
    highway_buffer = highway_building_buffer(road_segments, kinds, dem.shape, highway_setback_m)
    building_obstacle_mask = merge_building_hard_mask(obstacle_mask, road_buffer, water_buffer, highway_buffer)
    return SiteProblemContext(
        dem=dem,
        obstacle_mask=obstacle_mask,
        road_segments=road_segments,
        road_segment_kinds=kinds,
        highway_buffer=highway_buffer,
        dem_tensor=_tensor_4d(dem, device),
        obstacle_tensor=_tensor_4d(obstacle_mask, device),
        road_segments_tensor=torch.as_tensor(road_segments, dtype=torch.float32, device=device),
        road_voronoi_tensor=torch.as_tensor(road_voronoi, dtype=torch.long, device=device),
        demand_points=demand_points,
        demand_weights=None,
        demand_points_tensor=torch.as_tensor(demand_points, dtype=torch.float32, device=device),
        demand_weights_tensor=None,
        device=device,
        obstacle_soft_mask=obstacle_mask,
        obstacle_soft_tensor=_tensor_4d(obstacle_mask, device),
        building_soft_tensor=_tensor_4d(np.maximum(obstacle_mask, building_obstacle_mask), device),
        osm_road_mask=osm_road_mask,
        building_obstacle_mask=building_obstacle_mask,
        landuse=landuse,
        road_setback_m=setback,
        road_buffer=road_buffer,
        water_setback_m=water_setback,
        water_buffer=water_buffer,
    )


def with_constraint_masks(
    context: SiteProblemContext,
    hard_mask: np.ndarray,
    soft_mask: np.ndarray,
    road_setback_m: float | None = None,
    water_setback_m: float | None = None,
) -> SiteProblemContext:
    """Return a context that uses this run's masks. The scene arrays stay on disk.

    Road and water buffers are copied onto the building mask only. ``obstacle_mask``
    stays the land hard mask that HaulField walks on, so the water setback does not
    widen the access-road mask.
    """

    if hard_mask.shape != context.dem.shape or soft_mask.shape != context.dem.shape:
        raise ValueError("constraint masks must match the scene grid")
    if context.landuse is None or context.osm_road_mask is None:
        raise ValueError("landuse and the OSM centerline mask are required to rebuild the building hard mask")
    setback = context.road_setback_m if road_setback_m is None else require_road_setback_m(road_setback_m)
    water_setback = (
        context.water_setback_m if water_setback_m is None else require_water_setback_m(water_setback_m)
    )
    if (
        context.road_buffer is not None
        and setback == context.road_setback_m
        and context.road_buffer.shape == hard_mask.shape
    ):
        road_buffer = context.road_buffer
    else:
        road_buffer = road_building_buffer(context.landuse, context.osm_road_mask, setback)
    if (
        context.water_buffer is not None
        and water_setback == context.water_setback_m
        and context.water_buffer.shape == hard_mask.shape
    ):
        water_buffer = context.water_buffer
    else:
        water_buffer = water_building_buffer(context.landuse, water_setback)
    building_obstacle_mask = merge_building_hard_mask(hard_mask, road_buffer, water_buffer, context.highway_buffer)
    return replace(
        context,
        obstacle_mask=np.asarray(hard_mask, dtype=np.float32),
        obstacle_tensor=_tensor_4d(hard_mask, context.device),
        obstacle_soft_mask=np.asarray(soft_mask, dtype=np.float32),
        obstacle_soft_tensor=_tensor_4d(soft_mask, context.device),
        building_soft_tensor=_tensor_4d(np.maximum(soft_mask, building_obstacle_mask), context.device),
        building_obstacle_mask=building_obstacle_mask,
        road_setback_m=setback,
        road_buffer=road_buffer,
        water_setback_m=water_setback,
        water_buffer=water_buffer,
    )


def write_scene_products(
    config: ProjectConfig,
    output_dir: Path,
    on_step: Callable[[str], None] | None = None,
    *,
    reference_frame: dict[str, Any] | None = None,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Run the four data tools once and write their arrays. This does not search."""

    def step(message: str) -> None:
        if on_step is not None:
            on_step(message)

    if reference_frame is not None and (config.data.target_resolution_m != 1 or config.data.road_resolution_m != 1):
        raise ValueError("metric scene products require target_resolution_m=road_resolution_m=1")
    output_dir.mkdir(parents=True, exist_ok=True)
    step("正在读取用地")
    landuse, obstacle_mask, landuse_meta = build_landuse_product(
        config.data.landuse_path,
        config.data.obstacle_classes,
        expected_shape=None,
        output_landuse_path=output_dir / "landuse_1m.npy",
        output_obstacle_path=output_dir / "obstacle_mask_1m.npy",
        landuse_input_resolution_m=config.data.landuse_input_resolution_m,
        target_resolution_m=config.data.target_resolution_m,
        reference_frame=reference_frame,
        reference_geotiff_path=config.data.reference_geotiff_path,
    )
    primary_grid_shape = obstacle_mask.shape
    step("正在对齐高程")
    dem, dem_meta = build_dem_product(
        config.data.dem_path,
        config.data.reference_geotiff_path if reference_frame is None else None,
        primary_grid_shape,
        output_dir / "dem_1m.npy",
        config.data.target_resolution_m,
        reference_frame=reference_frame,
    )
    if landuse.shape != dem.shape:
        raise ValueError(f"landuse shape {landuse.shape} does not match DEM shape {dem.shape}")
    step("正在融合官方水系")
    from data_tools.io_utils import save_array_product
    from experiments.official_water import fuse_official_water

    remote_landuse = np.array(landuse, copy=True)
    landuse, obstacle_mask, water_meta = fuse_official_water(
        landuse,
        dem_meta,
        tuple(config.data.obstacle_classes),
    )
    step("正在按遥感水体补全水系线")
    from experiments.water_lines import fuse_water_lines

    landuse, obstacle_mask, line_meta = fuse_water_lines(
        landuse,
        dem_meta,
        tuple(config.data.obstacle_classes),
        original_landuse=remote_landuse,
    )
    water_meta["added_cells"] = int(water_meta["added_cells"]) - int(line_meta.pop("official_road_excluded_cells")) - int(line_meta.pop("official_building_excluded_cells"))
    water_meta["road_excluded_cells"] = line_meta["road_excluded_cells"]
    water_meta["building_excluded_cells"] = line_meta["building_excluded_cells"]
    landuse_meta = {**landuse_meta, "official_water": water_meta, "water_lines": line_meta}
    save_array_product(output_dir / "landuse_1m.npy", landuse, landuse_meta)
    save_array_product(output_dir / "obstacle_mask_1m.npy", obstacle_mask, landuse_meta)
    primary_grid_shape = landuse.shape
    step("正在处理道路")
    road_segments, road_voronoi, road_kinds, road_meta = build_road_product(
        config.data.osm_roads_path,
        output_dir / "road_segments_local.npy",
        output_dir / "road_voronoi_1m.npy",
        config.data.reference_geotiff_path if reference_frame is None else None,
        primary_grid_shape,
        config.data.road_dp_tolerance_m,
        config.data.road_resolution_m,
        voronoi_backend=config.data.road_voronoi_backend,
        voronoi_device=config.data.road_voronoi_device,
        voronoi_chunk_points=config.data.road_voronoi_chunk_points,
        voronoi_segment_tile=config.data.road_voronoi_segment_tile,
        kind_rules=config.data.road_kind_rules,
        reference_frame=reference_frame,
    )
    if road_voronoi.shape != dem.shape:
        raise ValueError(f"road_voronoi shape {road_voronoi.shape} does not match DEM shape {dem.shape}")
    step("正在生成需求点")
    demand_points, demand_weights, demand_meta = generate_demand_points(
        config.data.n_demand_points,
        config.data.demand_seed,
        primary_grid_shape,
        config.data.demand_on_buildable_only,
        obstacle_mask,
    )
    np.save(output_dir / "demand_points.npy", demand_points)
    write_json(output_dir / "demand_points.json", demand_meta)
    if demand_weights is not None:
        raise ValueError("scene demand weights are not stored; generate_demand_points must return None")
    arrays = {
        "dem": dem,
        "landuse": landuse,
        "obstacle_mask": obstacle_mask,
        "road_segments": road_segments,
        "road_segment_kinds": road_kinds,
        "road_voronoi": road_voronoi,
        "demand_points": demand_points,
    }
    metadata = {
        "dem": dem_meta,
        "landuse": landuse_meta,
        "road": road_meta,
        "demand": demand_meta,
        "official_water": water_meta,
        "water_lines": line_meta,
    }
    from uuid import uuid4
    from data_tools.metric_grid import frame_id
    frame = {"crs": dem_meta["reference_crs"], "transform": dem_meta["target_transform"],
             "width": dem.shape[1], "height": dem.shape[0]}
    metadata.update(frame_id=frame_id(frame), scene_revision=uuid4().hex,
                    coordinate_units="utm_grid_m" if reference_frame is not None else "web_mercator_projected_m")
    return arrays, metadata


def build_site_problem_context(
    config: ProjectConfig,
    output_dir: Path,
    device: torch.device,
) -> tuple[SiteProblemContext, dict[str, Any]]:
    """Build the common data context once for a research entry point.

    The decision UI does not call this during optimization. It loads a scene
    that was written earlier by ``write_scene_products``.
    """

    arrays, metadata = write_scene_products(config, output_dir)
    return context_from_arrays(arrays, device, road_setback_m=config.modeling.road_setback_m,
                               water_setback_m=config.modeling.water_setback_m,
                               highway_setback_m=config.modeling.highway_setback_m), metadata
