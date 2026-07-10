from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


LOCAL_COORD_CONVENTION = {
    "origin": "upper_left",
    "x_positive": "right",
    "y_positive": "down",
    "unit": "meter",
    "cell_center": "x=col+0.5, y=row+0.5",
}


def ensure_2d_finite(name: str, array: np.ndarray) -> None:
    if array.ndim != 2:
        raise ValueError(f"{name} must be 2D, got shape {array.shape}")
    if array.size == 0:
        raise ValueError(f"{name} must not be empty")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} contains NaN or Inf")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def save_array_product(path: Path, array: np.ndarray, metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, array)
    write_json(path.with_suffix(".json"), metadata)

