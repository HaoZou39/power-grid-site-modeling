"""Compose one optimization's hard mask and soft-cost mask from a saved land-use grid."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FIELD = 1
BUILDING = 2
ROAD = 3
WATER = 5
MOUNTAIN = 4
KNOWN_CLASSES = frozenset({0, 1, 2, 3, 4, 5})
DEFAULT_HARD_CLASSES = (FIELD, BUILDING, ROAD, WATER)
DEFAULT_FIELD_COST = 0.5

CLASS_COLORS: dict[str, tuple[int, tuple[int, int, int, int]]] = {
    "field": (FIELD, (230, 190, 40, 150)),
    "building": (BUILDING, (214, 48, 140, 160)),
    "road": (ROAD, (220, 48, 48, 160)),
    "water": (WATER, (36, 112, 214, 160)),
}


@dataclass(frozen=True)
class LandusePolicy:
    """Hard classes block construction. Costly classes stay feasible and add soft cost."""

    hard_classes: tuple[int, ...] = DEFAULT_HARD_CLASSES
    costly: tuple[tuple[int, float], ...] = ()


def default_policy() -> LandusePolicy:
    return LandusePolicy()


def policy_from_form(form: dict) -> LandusePolicy:
    mode = str(form.get("field_policy") or "allowed")
    cost = float(form.get("field_cost", DEFAULT_FIELD_COST))
    mountain_mode = str(form.get("mountain_policy") or "allowed")
    if mountain_mode not in {"blocked", "allowed"}:
        raise ValueError("mountain_policy must be blocked or allowed")
    if mode not in {"blocked", "allowed", "costly"}:
        raise ValueError("field_policy must be blocked, allowed, or costly")
    hard = [BUILDING, ROAD, WATER]
    if mode == "blocked":
        hard.append(FIELD)
    if mountain_mode == "blocked":
        hard.append(MOUNTAIN)
    if mode == "costly":
        _check_cost(cost)
        return LandusePolicy(hard_classes=tuple(hard), costly=((FIELD, cost),))
    return LandusePolicy(hard_classes=tuple(hard))


def polygons_from_form(form: dict, key: str = "exclusion_zones") -> list[list[tuple[float, float]]]:
    zones = form.get(key) or []
    if not isinstance(zones, list):
        raise ValueError(f"{key} must be a list")
    name = "feasible zone" if key == "feasible_zones" else "exclusion zone"
    rings: list[list[tuple[float, float]]] = []
    for zone in zones:
        points = zone.get("points") if isinstance(zone, dict) else zone
        if not isinstance(points, list) or len(points) < 3:
            raise ValueError(f"each {name} needs at least three points")
        ring = [(float(point[0]), float(point[1])) for point in points]
        rings.append(ring)
    return rings


def compose_constraint_masks(
    landuse: np.ndarray,
    polygons: list[list[tuple[float, float]]],
    policy: LandusePolicy | None = None,
    feasible: list[list[tuple[float, float]]] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return hard and soft masks. This does not write the scene files."""

    if landuse.ndim != 2 or landuse.size == 0:
        raise ValueError("landuse must be a non-empty 2D array")
    unknown = set(np.unique(landuse).astype(int).tolist()) - KNOWN_CLASSES
    if unknown:
        raise ValueError(f"unknown landuse class ids: {sorted(unknown)}")
    chosen = policy or default_policy()
    costly_ids = {class_id for class_id, _cost in chosen.costly}
    if costly_ids & set(chosen.hard_classes):
        raise ValueError("a landuse class cannot be both hard and costly")
    hard = np.isin(landuse, np.array(chosen.hard_classes, dtype=np.int32)).astype(np.float32)
    soft = hard.copy()
    for class_id, cost in chosen.costly:
        _check_cost(cost)
        soft[landuse == class_id] = np.float32(cost)
    if feasible:
        allowed = rasterize_exclusions(feasible, landuse.shape, "feasible")
        outside = np.float32(1) - allowed
        hard = np.maximum(hard, outside)
        soft = np.maximum(soft, outside)
    if polygons:
        drawn = rasterize_exclusions(polygons, landuse.shape)
        hard = np.maximum(hard, drawn)
        soft = np.maximum(soft, drawn)
    return hard, soft


def rasterize_exclusions(
    polygons: list[list[tuple[float, float]]],
    shape: tuple[int, int],
    name: str = "exclusion",
) -> np.ndarray:
    """Burn local-meter polygons onto the 1 m grid. Vertices outside the grid are rejected."""

    from rasterio.features import rasterize
    from rasterio.transform import Affine

    label = "feasible zone" if name == "feasible" else "exclusion zone"
    vertex = "feasible zone" if name == "feasible" else "exclusion"
    height, width = shape
    shapes = []
    for ring in polygons:
        if len(ring) < 3:
            raise ValueError(f"each {label} needs at least three points")
        coords: list[tuple[float, float]] = []
        for x_coord, y_coord in ring:
            if not (np.isfinite(x_coord) and np.isfinite(y_coord)):
                raise ValueError(f"{vertex} vertices must be finite")
            if x_coord < 0 or y_coord < 0 or x_coord > width or y_coord > height:
                raise ValueError(f"{vertex} vertex is outside the site")
            coords.append((float(x_coord), float(y_coord)))
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        shapes.append({"type": "Polygon", "coordinates": [coords]})
    burned = rasterize(
        shapes,
        out_shape=(height, width),
        transform=Affine(1, 0, 0, 0, 1, 0),
        fill=0,
        default_value=1,
        dtype=np.float32,
        all_touched=True,
    )
    return np.asarray(burned, dtype=np.float32)


def _check_cost(cost: float) -> None:
    if not np.isfinite(cost) or cost <= 0 or cost > 1:
        raise ValueError("field cost must be in (0, 1]")
