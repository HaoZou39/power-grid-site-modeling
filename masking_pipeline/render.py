#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Render a routing coarse class mask (.npy) to an RGB PNG at **native resolution**.

Uses the same class colours as ``downsample_to_mask_gray.save_mask_vis`` and
``segment_landcover_routing.ROUTE_CLASSES`` (not the satellite overlay — pure class map).

Example
-------
  python image_process/render_routing_coarse_mask_to_png.py \\
    image_process/outputs/satellite_27.548982_120.377612_r2.00km_z19_full_epsg3857_routing_coarse_mask.npy

Writes by default: <stem>_class_map.png next to the .npy, and <stem>_class_map_legend.png (small legend only).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Dict, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch
from PIL import Image

# Same palette as downsample_to_mask_gray / segment_landcover_routing.ROUTE_CLASSES
ROUTE_CLASSES: Dict[int, Tuple[str, str]] = {
    0: ("other", "#666666"),
    1: ("field", "#f2d16b"),
    2: ("building", "#d81b60"),
    3: ("road", "#ff4d4d"),
    4: ("mountain_natural", "#2ecc71"),
    5: ("water", "#1f5fd1"),
}

UNKNOWN_RGB = (136, 136, 136)


def hex_to_rgb_u8(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def build_palette() -> np.ndarray:
    """shape (256, 3) uint8, index = class id."""
    pal = np.zeros((256, 3), dtype=np.uint8)
    pal[:] = UNKNOWN_RGB
    for idx, (_, hx) in ROUTE_CLASSES.items():
        if 0 <= idx < 256:
            pal[idx] = hex_to_rgb_u8(hx)
    return pal


def mask_to_rgb(mask: np.ndarray, palette: np.ndarray) -> np.ndarray:
    m = np.asarray(mask, dtype=np.intp)
    m = np.clip(m, 0, palette.shape[0] - 1)
    return palette[m]


def save_legend_png(out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(4.0, 3.2))
    ax.axis("off")
    handles = [
        Patch(
            facecolor=tuple(c / 255.0 for c in hex_to_rgb_u8(col)),
            label=f"{k}: {name}",
        )
        for k, (name, col) in sorted(ROUTE_CLASSES.items())
    ]
    ax.legend(handles=handles, loc="center", fontsize=10, frameon=False)
    plt.tight_layout()
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    default_npy = (
        script_dir
        / "outputs"
        / "satellite_27.548982_120.377612_r2.00km_z19_full_epsg3857_routing_coarse_mask.npy"
    )

    ap = argparse.ArgumentParser(description="Render routing coarse .npy mask to full-res RGB PNG.")
    ap.add_argument(
        "npy",
        nargs="?",
        type=Path,
        default=default_npy,
        help="Path to routing coarse mask .npy (H,W integer labels 0..5)",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output RGB PNG path (default: <npy_stem>_class_map.png beside .npy)",
    )
    ap.add_argument(
        "--no-legend",
        action="store_true",
        help="Do not write the separate small legend PNG",
    )
    args = ap.parse_args()

    npy_path = Path(args.npy).resolve()
    if not npy_path.is_file():
        raise FileNotFoundError(npy_path)

    mask = np.load(str(npy_path), allow_pickle=True)
    if mask.ndim != 2:
        raise ValueError(f"Expected 2D mask, got shape {mask.shape}")

    palette = build_palette()
    rgb = mask_to_rgb(mask, palette)

    out_png = args.output
    if out_png is None:
        out_png = npy_path.with_name(npy_path.stem + "_class_map.png")
    else:
        out_png = Path(out_png).resolve()

    out_png.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(out_png, compress_level=6)
    print(f"Wrote {out_png}  shape={mask.shape[0]}x{mask.shape[1]}  (RGB, full resolution)")

    if not args.no_legend:
        leg_path = out_png.with_name(out_png.stem + "_legend.png")
        save_legend_png(leg_path)
        print(f"Wrote {leg_path}  (legend only)")


if __name__ == "__main__":
    main()
