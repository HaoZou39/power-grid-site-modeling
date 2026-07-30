from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import numpy as np

CandidateMapMode = Literal["points", "footprints"]


def rectangle_corners(x: float, y: float, theta: float, width: float, height: float) -> np.ndarray:
    local = np.array(
        [
            [-width / 2.0, -height / 2.0],
            [width / 2.0, -height / 2.0],
            [width / 2.0, height / 2.0],
            [-width / 2.0, height / 2.0],
        ],
        dtype=np.float64,
    )
    c = np.cos(theta)
    s = np.sin(theta)
    rot = np.array([[c, -s], [s, c]], dtype=np.float64)
    return local @ rot.T + np.array([x, y], dtype=np.float64)


def plot_candidate_map(
    path: Path,
    dem: np.ndarray,
    obstacle_mask: np.ndarray,
    road_segments: np.ndarray,
    demand_points: np.ndarray,
    records: Sequence[Mapping[str, Any]],
    rect_w_m: float,
    rect_h_m: float,
    mode: CandidateMapMode,
    title: str,
) -> None:
    if mode not in ("points", "footprints"):
        raise ValueError(f"unknown plot mode {mode!r}")

    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 9))
    ax.imshow(dem, cmap="terrain", origin="upper")
    masked = np.ma.masked_where(obstacle_mask <= 0, obstacle_mask)
    ax.imshow(masked, cmap="Reds", alpha=0.28, origin="upper")
    for segment in road_segments:
        ax.plot(
            [float(segment[0]), float(segment[2])],
            [float(segment[1]), float(segment[3])],
            color="#202020",
            linewidth=0.45,
            alpha=0.75,
            zorder=2,
        )
    ax.scatter(
        demand_points[:, 0],
        demand_points[:, 1],
        s=14,
        c="#ffd21f",
        edgecolors="black",
        linewidths=0.3,
        label="demand",
    )
    if mode == "points":
        xs = [float(r["x"]) for r in records]
        ys = [float(r["y"]) for r in records]
        if xs:
            ax.scatter(xs, ys, s=20, c="#d7191c", edgecolors="white", linewidths=0.4, label="sites")
    else:
        for record in records:
            corners = rectangle_corners(
                float(record["x"]),
                float(record["y"]),
                float(record["theta"]),
                rect_w_m,
                rect_h_m,
            )
            ax.add_patch(Polygon(corners, closed=True, fill=False, edgecolor="#d7191c", linewidth=0.8))
    ax.set_title(title)
    ax.set_xlim(0, dem.shape[1])
    ax.set_ylim(dem.shape[0], 0)
    ax.set_aspect("equal")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
