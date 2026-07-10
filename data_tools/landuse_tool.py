from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.ndimage import zoom

from .io_utils import LOCAL_COORD_CONVENTION, ensure_2d_finite, save_array_product, write_json


LANDUSE_CLASS_MAPPING: dict[int, dict[str, object]] = {
    0: {
        "code": "other",
        "zh": "其他区域",
        "typical_color": "灰色",
        "buildability": "buildable",
        "obstacle_mask_value": 0,
    },
    1: {
        "code": "field",
        "zh": "农田区域",
        "typical_color": "黄色",
        "buildability": "non_buildable",
        "obstacle_mask_value": 1,
    },
    2: {
        "code": "building",
        "zh": "建筑区域",
        "typical_color": "品红/粉红",
        "buildability": "non_buildable",
        "obstacle_mask_value": 1,
    },
    3: {
        "code": "road",
        "zh": "道路区域",
        "typical_color": "红色",
        "buildability": "non_buildable",
        "obstacle_mask_value": 1,
    },
    4: {
        "code": "mountain_natural",
        "zh": "山体/自然区域（裸地、草地、林地等合并）",
        "typical_color": "绿色",
        "buildability": "buildable",
        "obstacle_mask_value": 0,
    },
    5: {
        "code": "water",
        "zh": "水体区域",
        "typical_color": "蓝色",
        "buildability": "non_buildable",
        "obstacle_mask_value": 1,
    },
}

DEFAULT_BUILDABLE_CLASSES: tuple[int, ...] = (0, 4)
DEFAULT_OBSTACLE_CLASSES: tuple[int, ...] = (1, 2, 3, 5)


def build_landuse_product(
    landuse_path: Path,
    obstacle_classes: tuple[int, ...],
    expected_shape: tuple[int, int] | None = None,
    output_landuse_path: Path | None = None,
    output_obstacle_path: Path | None = None,
    landuse_input_resolution_m: float = 1.0,
    target_resolution_m: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, dict]:
    landuse_path = Path(landuse_path)
    if not landuse_path.exists():
        raise FileNotFoundError(landuse_path)
    if not obstacle_classes:
        raise ValueError("obstacle_classes must not be empty")
    unknown_obstacles = sorted(set(obstacle_classes) - set(LANDUSE_CLASS_MAPPING))
    if unknown_obstacles:
        raise ValueError(f"unknown obstacle class ids: {unknown_obstacles}")
    if landuse_input_resolution_m <= 0 or target_resolution_m <= 0:
        raise ValueError("landuse resolutions must be positive")
    landuse_raw = np.loadtxt(landuse_path, delimiter=",")
    ensure_2d_finite("landuse_raw", landuse_raw)
    scale = landuse_input_resolution_m / target_resolution_m
    if abs(scale - 1.0) > 1e-9:
        landuse = zoom(landuse_raw, zoom=scale, order=0)
    else:
        landuse = landuse_raw
    landuse = landuse.astype(np.int32)
    ensure_2d_finite("landuse", landuse)
    if expected_shape is not None and landuse.shape != expected_shape:
        raise ValueError(f"landuse shape {landuse.shape} does not match expected {expected_shape}")
    unknown_values = sorted(set(np.unique(landuse).astype(int).tolist()) - set(LANDUSE_CLASS_MAPPING))
    if unknown_values:
        raise ValueError(f"landuse contains undefined class ids: {unknown_values}")
    obstacle_mask = np.isin(landuse, np.array(obstacle_classes, dtype=np.int32)).astype(np.float32)
    buildable_classes = sorted(set(LANDUSE_CLASS_MAPPING) - set(obstacle_classes))
    metadata = {
        "source_path": str(landuse_path),
        "raw_shape": list(landuse_raw.shape),
        "shape": list(landuse.shape),
        "input_resolution_m": landuse_input_resolution_m,
        "target_resolution_m": target_resolution_m,
        "interpolation": "nearest",
        "obstacle_classes": list(obstacle_classes),
        "buildable_classes": buildable_classes,
        "obstacle_mapping": {
            "mask_value_0": "buildable",
            "mask_value_1": "non_buildable",
            "buildable_class_ids": buildable_classes,
            "non_buildable_class_ids": list(obstacle_classes),
        },
        "landuse_class_mapping": LANDUSE_CLASS_MAPPING,
        "local_coord_convention": LOCAL_COORD_CONVENTION,
    }
    if output_landuse_path is not None:
        save_array_product(output_landuse_path, landuse, metadata)
    if output_obstacle_path is not None:
        save_array_product(output_obstacle_path, obstacle_mask, metadata)
    return landuse, obstacle_mask, metadata
