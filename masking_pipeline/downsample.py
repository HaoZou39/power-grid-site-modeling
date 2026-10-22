#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Downsample routing coarse mask to a target grid size.

- Default: match ``mask_gray_3.npy`` (or ``--target-npy``) H×W.
- Or: pass ``--target-height`` and ``--target-width`` together for an explicit output shape.

Nearest-neighbor zoom for categorical labels. Saves *_downsampled.npy and a legend PNG.
"""
import argparse
import os
import sys
import numpy as np
from scipy import ndimage
from datetime import datetime
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
LOG_DIR = os.path.join(SCRIPT_DIR, "log")


def _ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)

# Same as segment_landcover_routing ROUTE_CLASSES for visualization
ROUTE_CLASSES = {
    0: ("other", "#666666"),
    1: ("field", "#f2d16b"),
    2: ("building", "#d81b60"),
    3: ("road", "#ff4d4d"),
    4: ("mountain_natural", "#2ecc71"),
    5: ("water", "#1f5fd1"),
}


def default_target_mask_path() -> str:
    """Prefer project-root mask_gray_3 (matches dsop/constants MAP_PATH), else image_process/."""
    for p in (
        os.path.join(PROJECT_DIR, "mask_gray_3.npy"),
        os.path.join(SCRIPT_DIR, "mask_gray_3.npy"),
    ):
        if os.path.isfile(p):
            return p
    return os.path.join(PROJECT_DIR, "mask_gray_3.npy")


def hex_to_rgb(hex_color: str):
    return tuple(int(hex_color[i : i + 2], 16) / 255.0 for i in (1, 3, 5))  # #RRGGBB


def save_mask_vis(mask: np.ndarray, out_path: str):
    """Save single-panel mask visualization with legend."""
    rgb = np.ones((*mask.shape, 3), dtype=np.float32) * 0.4
    for idx, (_, color_hex) in ROUTE_CLASSES.items():
        rgb[mask == idx] = hex_to_rgb(color_hex)
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(rgb, origin="upper")
    ax.set_title("Routing coarse classes (downsampled)", fontsize=12)
    ax.axis("off")
    legend = [Patch(facecolor=hex_to_rgb(c), label=f"{k}: {n}") for k, (n, c) in ROUTE_CLASSES.items()]
    ax.legend(handles=legend, loc="upper left", fontsize=8)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()


def downsample_mask_nearest(mask: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    """Downsample categorical mask using nearest-neighbor (order=0)."""
    zoom_factors = (target_h / mask.shape[0], target_w / mask.shape[1])
    return ndimage.zoom(mask.astype(np.float32), zoom_factors, order=0).astype(mask.dtype)


def downsample_routing_mask(
    coarse_npy: str,
    output_dir: str = None,
    target_height: int = None,
    target_width: int = None,
    target_npy: str = None,
    save_png: bool = True,
) -> dict:
    """
    Downsample a routing coarse mask to target H×W.

    Returns dict with keys: downsampled_npy, downsampled_png (optional), shape.
    """
    _ensure_log_dir()

    h_set = target_height is not None
    w_set = target_width is not None
    if h_set ^ w_set:
        raise ValueError("target_height and target_width must be given together")
    if h_set and w_set:
        if target_height < 1 or target_width < 1:
            raise ValueError("target_height and target_width must be >= 1")
        use_custom_size = True
    else:
        use_custom_size = False

    coarse_path = os.path.abspath(coarse_npy)
    out_dir = os.path.abspath(output_dir) if output_dir else os.path.dirname(coarse_path)
    os.makedirs(out_dir, exist_ok=True)

    log_lines = [f"[{datetime.now().isoformat()}] downsample.py"]
    log_lines.append(f"coarse: {coarse_path}")
    log_lines.append(f"output_dir: {out_dir}")

    if use_custom_size:
        target_h, target_w = target_height, target_width
        log_lines.append(f"target: custom shape {target_h} x {target_w}")
    else:
        target_path = os.path.abspath(target_npy) if target_npy else default_target_mask_path()
        log_lines.append(f"target_npy: {target_path}")
        if not os.path.isfile(target_path):
            raise FileNotFoundError(f"target mask not found: {target_path}")
        target_mask = np.load(target_path, allow_pickle=True)
        if target_mask.ndim != 2:
            raise ValueError("target .npy must be 2D")
        target_h, target_w = target_mask.shape
        log_lines.append(f"target shape (from file): {target_h} x {target_w}")

    if not os.path.isfile(coarse_path):
        raise FileNotFoundError(f"routing mask not found: {coarse_path}")

    routing_mask = np.load(coarse_path, allow_pickle=True)
    if routing_mask.ndim != 2:
        raise ValueError("coarse mask must be 2D")
    src_h, src_w = routing_mask.shape
    log_lines.append(f"source routing mask shape: {src_h} x {src_w}")

    print("Downsampling mask...")
    down_mask = downsample_mask_nearest(routing_mask, target_h, target_w)
    log_lines.append(f"downsampled mask shape: {down_mask.shape}")

    base = os.path.splitext(os.path.basename(coarse_path))[0]
    out_mask_path = os.path.join(out_dir, f"{base}_downsampled.npy")
    np.save(out_mask_path, down_mask)
    log_lines.append(f"saved: {out_mask_path}")
    print(f"Saved downsampled mask: {out_mask_path}")

    result = {
        "downsampled_npy": out_mask_path,
        "shape": (int(down_mask.shape[0]), int(down_mask.shape[1])),
    }

    if save_png:
        if base.endswith("_routing_coarse_mask"):
            stem = base[: -len("_routing_coarse_mask")]
        else:
            stem = base
        out_png_path = os.path.join(out_dir, f"{stem}_routing_coarse_downsampled.png")
        save_mask_vis(down_mask, out_png_path)
        log_lines.append(f"saved_png: {out_png_path}")
        print(f"Saved PNG: {out_png_path}")
        result["downsampled_png"] = out_png_path

    print(f"Target size: {target_h} x {target_w}")
    _write_log(log_lines)
    return result


def _write_log(log_lines):
    _ensure_log_dir()
    with open(os.path.join(LOG_DIR, "downsample_to_mask_gray.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Downsample *_routing_coarse_mask.npy to a target H×W: "
            "either match a reference .npy (default mask_gray_3) or set --target-height/--target-width."
        )
    )
    parser.add_argument(
        "--coarse-npy",
        type=str,
        required=True,
        help="Full-resolution routing coarse mask from segment.py",
    )
    parser.add_argument(
        "--target-npy",
        type=str,
        default=None,
        help="Reference .npy whose 2D shape sets output H×W; ignored if --target-height/--target-width are set",
    )
    parser.add_argument(
        "--target-height",
        type=int,
        default=None,
        metavar="H",
        help="Output row count (height). Must be used with --target-width; overrides --target-npy shape",
    )
    parser.add_argument(
        "--target-width",
        type=int,
        default=None,
        metavar="W",
        help="Output column count (width). Must be used with --target-height; overrides --target-npy shape",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Where to save downsampled .npy and PNG; default: same directory as --coarse-npy",
    )
    parser.add_argument(
        "--no-png",
        action="store_true",
        help="Skip legend visualization PNG",
    )
    args = parser.parse_args()

    h_set = args.target_height is not None
    w_set = args.target_width is not None
    if h_set ^ w_set:
        parser.error("--target-height and --target-width must be given together (or omit both to use --target-npy)")

    try:
        downsample_routing_mask(
            coarse_npy=args.coarse_npy,
            output_dir=args.output_dir,
            target_height=args.target_height,
            target_width=args.target_width,
            target_npy=args.target_npy,
            save_png=not args.no_png,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
