#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Remote-sensing land-cover segmentation for routing preprocessing.

Fixes in this version:
- Use the correct 8-class OpenEarthMap label schema.
- Disable the processor's default 384x384 resize during sliding-window inference.
- Fuse overlapping windows with semantic logits instead of hard-label voting.
- Do not downsample large inputs by default; `--max-size 0` keeps the original size.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Tuple

import matplotlib
import numpy as np
import torch
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "log")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "outputs")


def _ensure_dirs():
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

# OpenEarthMap official 8 classes.
OEM_CLASSES = {
    0: ("bareland", "#c49a6c"),
    1: ("rangeland", "#7CFC00"),
    2: ("developed_space", "#b0b0b0"),
    3: ("road", "#ff4d4d"),
    4: ("tree", "#228b22"),
    5: ("water", "#1f5fd1"),
    6: ("agriculture_land", "#f2d16b"),
    7: ("building", "#d81b60"),
}

ROUTE_CLASSES = {
    0: ("other", "#666666"),
    1: ("field", "#f2d16b"),
    2: ("building", "#d81b60"),
    3: ("road", "#ff4d4d"),
    4: ("mountain_natural", "#2ecc71"),
    5: ("water", "#1f5fd1"),
}

# OpenEarthMap fine classes -> routing coarse classes.
OEM_TO_ROUTE = {
    0: 4,  # bareland -> mountain_natural
    1: 4,  # rangeland -> mountain_natural
    2: 0,  # developed_space -> other
    3: 3,  # road -> road
    4: 4,  # tree -> mountain_natural
    5: 5,  # water -> water
    6: 1,  # agriculture_land -> field
    7: 2,  # building -> building
}

DEFAULT_ROUTE_COSTS = {
    0: 8.0,    # other
    1: 4.0,    # field
    2: 80.0,   # building
    3: 2.0,    # road
    4: 10.0,   # mountain_natural
    5: 255.0,  # water
}


@dataclass
class GeoMeta:
    crs: Optional[object] = None
    transform: Optional[object] = None
    width: Optional[int] = None
    height: Optional[int] = None
    driver: str = "GTiff"


def build_window_starts(length: int, patch_size: int, stride: int):
    if stride <= 0:
        raise ValueError(f"stride must be > 0, got {stride}")
    if patch_size <= 0:
        raise ValueError(f"patch_size must be > 0, got {patch_size}")
    last = max(length - patch_size, 0)
    starts = list(range(0, last + 1, stride))
    if not starts:
        starts = [0]
    if starts[-1] != last:
        starts.append(last)
    return starts


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def mask_to_rgb(
    pred: np.ndarray,
    class_map: Dict[int, Tuple[str, str]],
    default: Tuple[int, int, int] = (128, 128, 128),
) -> np.ndarray:
    rgb = np.zeros((pred.shape[0], pred.shape[1], 3), dtype=np.uint8)
    rgb[:] = default
    for idx, (_, color_hex) in class_map.items():
        rgb[pred == idx] = hex_to_rgb(color_hex)
    return rgb


# 行分块高度。one-hot 单块显存约为 (rows+2*halo) × width × num_classes × 4B，
# 512 行在 34906 列 6 类时约 0.9 GiB（含池化输出与 argmax），大图不再一次性占几十 GiB。
_SMOOTH_BLOCK_ROWS = 512


def majority_smooth(
    mask: np.ndarray, num_classes: int, kernel: int = 3, device: str = "cpu", chunk_rows: int = _SMOOTH_BLOCK_ROWS
) -> np.ndarray:
    if kernel <= 1:
        return mask
    if kernel % 2 == 0:
        raise ValueError("smooth kernel must be odd")
    if not isinstance(chunk_rows, int) or chunk_rows <= 0:
        raise ValueError("chunk_rows must be a positive integer")
    if not isinstance(num_classes, int) or not 1 <= num_classes <= 256:
        raise ValueError("num_classes must be an integer in [1, 256]")
    if mask.ndim != 2 or not np.issubdtype(mask.dtype, np.integer):
        raise ValueError("mask must be a 2D integer class array")
    if mask.size and (mask.min() < 0 or mask.max() >= num_classes):
        raise ValueError(f"mask classes must be in [0, {num_classes})")

    # 整图 one-hot 要 H*W*C 个数，18 km 场景约 58 GB。按行分块，并多读 kernel//2 行重叠，结果与整图一次算完全一致。
    pad = kernel // 2
    h = mask.shape[0]
    out = np.empty(mask.shape, dtype=np.uint8)
    for y0 in range(0, h, chunk_rows):
        y1 = min(y0 + chunk_rows, h)
        a0, a1 = max(0, y0 - pad), min(h, y1 + pad)
        x = torch.from_numpy(np.ascontiguousarray(mask[a0:a1])).to(device)
        classes = torch.arange(num_classes, device=device)
        onehot = (x.unsqueeze(0) == classes[:, None, None]).unsqueeze(0).float()
        pooled = torch.nn.functional.avg_pool2d(onehot, kernel_size=kernel, stride=1, padding=pad)
        out[y0:y1] = pooled.argmax(dim=1)[0, y0 - a0 : y1 - a0].cpu().numpy().astype(np.uint8)
        del x, onehot, pooled
    return out


def remap_mask(mask: np.ndarray, mapping: Dict[int, int], default: int = 0) -> np.ndarray:
    out = np.full(mask.shape, default, dtype=np.uint8)
    for src, dst in mapping.items():
        out[mask == src] = dst
    return out


def make_weight_map(patch_size: int) -> np.ndarray:
    if patch_size <= 1:
        return np.ones((patch_size, patch_size), dtype=np.float32)
    wy = np.hanning(patch_size)
    wx = np.hanning(patch_size)
    w = np.outer(wy, wx).astype(np.float32)
    w = np.maximum(w, 1e-3)
    return w


def open_image_with_optional_geo(path: str) -> Tuple[Image.Image, Optional[GeoMeta]]:
    ext = os.path.splitext(path)[1].lower()
    if ext in {".tif", ".tiff"}:
        try:
            import rasterio

            with rasterio.open(path) as ds:
                arr = ds.read()
                if arr.ndim != 3:
                    raise ValueError(f"Unexpected raster shape: {arr.shape}")
                if arr.shape[0] == 1:
                    arr = np.repeat(arr, 3, axis=0)
                elif arr.shape[0] >= 3:
                    arr = arr[:3]
                arr = np.transpose(arr, (1, 2, 0))
                if arr.dtype != np.uint8:
                    if arr.max() <= 1.0:
                        arr = (arr * 255.0).clip(0, 255).astype(np.uint8)
                    else:
                        arr = arr.clip(0, 255).astype(np.uint8)
                img = Image.fromarray(arr, mode="RGB")
                geo = GeoMeta(crs=ds.crs, transform=ds.transform, width=ds.width, height=ds.height)
                return img, geo
        except Exception as exc:
            print(f"[WARN] GeoTIFF read via rasterio failed, fallback to PIL: {exc}")

    img = Image.open(path).convert("RGB")
    return img, None


def save_mask_geotiff(mask: np.ndarray, out_path: str, geo: GeoMeta):
    try:
        import rasterio
        from rasterio.transform import Affine

        transform = geo.transform
        if geo.width and geo.height and (mask.shape[1] != geo.width or mask.shape[0] != geo.height):
            sx = geo.width / mask.shape[1]
            sy = geo.height / mask.shape[0]
            transform = geo.transform * Affine.scale(sx, sy)

        with rasterio.open(
            out_path,
            "w",
            driver="GTiff",
            height=mask.shape[0],
            width=mask.shape[1],
            count=1,
            dtype=mask.dtype,
            crs=geo.crs,
            transform=transform,
            compress="lzw",
        ) as dst:
            dst.write(mask, 1)
    except Exception as exc:
        print(f"[WARN] Failed to save GeoTIFF mask {out_path}: {exc}")


def save_visualization(
    original_rgb: np.ndarray,
    mask: np.ndarray,
    class_map: Dict[int, Tuple[str, str]],
    title: str,
    out_path: str,
    overlay_alpha: Optional[float] = None,
    max_display_side: int = 4096,
):
    unique = np.unique(mask)
    # 图只有约 1000 px 宽，先抽稀再画；整张大图交给 matplotlib 会占几十 GB 内存。
    step = max(1, -(-max(original_rgb.shape[:2]) // max_display_side))
    original_rgb = original_rgb[::step, ::step]
    mask = mask[::step, ::step]
    seg_rgb = mask_to_rgb(mask, class_map)
    alpha = overlay_alpha if overlay_alpha is not None else 0.40

    # Compute figsize so each subplot exactly matches the image aspect ratio.
    # This prevents imshow (aspect='equal') from leaving horizontal whitespace inside subplots.
    h_img, w_img = original_rgb.shape[:2]
    img_aspect = w_img / h_img          # e.g. 1.0 for a square satellite tile

    # Layout constants (fractions of figure height/width)
    left_frac, right_frac = 0.01, 0.99  # nearly full width for the two subplots
    top_frac, bot_frac = 0.10, 0.28     # title gap (top) + legend area (bottom)
    wspace_frac = 0.02                  # tiny gap between the two panels

    # Each subplot gets half the usable horizontal space (minus the wspace gap).
    fig_w = 7.0
    usable_w = fig_w * (right_frac - left_frac)
    sw = (usable_w - fig_w * wspace_frac) / 2  # single subplot width in inches
    sh = sw / img_aspect                         # subplot height to match image ratio
    usable_h_frac = 1.0 - top_frac - bot_frac
    fig_h = sh / usable_h_frac                  # total figure height

    # Prefer Times New Roman when available; otherwise fall back silently.
    available = {f.name for f in matplotlib.font_manager.fontManager.ttflist}
    font_family = "Times New Roman" if "Times New Roman" in available else "DejaVu Serif"
    font_props = {"family": font_family, "size": 11}
    fig, axes = plt.subplots(1, 2, figsize=(fig_w, fig_h))

    axes[0].imshow(original_rgb)
    axes[0].set_title("Original", fontdict=font_props)
    axes[0].axis("off")

    axes[1].imshow(original_rgb)
    axes[1].imshow(seg_rgb, alpha=alpha)
    axes[1].set_title("Overlay", fontdict=font_props)
    axes[1].axis("off")

    legend_items = []
    for k in sorted(unique.tolist()):
        if int(k) in class_map:
            name, color_hex = class_map[int(k)]
            rgb = [v / 255.0 for v in hex_to_rgb(color_hex)]
            legend_items.append(Patch(facecolor=rgb, label=f"{k}: {name}"))
    if legend_items:
        fig.legend(
            handles=legend_items,
            loc="upper center",
            bbox_to_anchor=(0.5, bot_frac - 0.02),
            ncol=3,
            prop={"family": font_family, "size": 10},
            frameon=True,
        )

    fig.subplots_adjust(
        left=left_frac, right=right_frac,
        top=1.0 - top_frac, bottom=bot_frac,
        wspace=wspace_frac,
    )
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()


def save_cost_visualization(cost_map: np.ndarray, out_path: str):
    fig = plt.figure(figsize=(8, 8))
    plt.imshow(cost_map, cmap="magma")
    plt.colorbar(fraction=0.046, pad=0.04)
    plt.title("Routing Cost Map")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def resolve_inference_device() -> str:
    """Use CUDA when it is available. ``MASKING_DEVICE`` can force ``cpu`` or ``cuda``."""
    forced = os.environ.get("MASKING_DEVICE", "auto").strip().lower()
    if forced in {"", "auto"}:
        return "cuda" if torch.cuda.is_available() else "cpu"
    if forced == "cpu":
        return "cpu"
    if forced == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("MASKING_DEVICE=cuda but CUDA is not available")
        return "cuda"
    raise RuntimeError("MASKING_DEVICE must be auto, cpu, or cuda")


def configure_hf_hub(endpoint: Optional[str] = None) -> Optional[str]:
    """
    Point huggingface_hub at a mirror (e.g. https://hf-mirror.com on CN servers).
    Must run before ``from_pretrained``. Also honors existing HF_ENDPOINT env.
    """
    ep = (endpoint or os.environ.get("HF_ENDPOINT") or "").strip().rstrip("/")
    if not ep:
        return None
    os.environ["HF_ENDPOINT"] = ep
    os.environ.setdefault("HUGGINGFACE_HUB_ENDPOINT", ep)
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", os.environ.get("HF_HUB_DOWNLOAD_TIMEOUT", "300"))
    print(f"[INFO] HuggingFace Hub endpoint: {ep}")
    return ep


def load_mask2former_remote(device: str, model_id: str):
    from transformers import Mask2FormerForUniversalSegmentation, Mask2FormerImageProcessor

    processor = Mask2FormerImageProcessor.from_pretrained(model_id, do_resize=False)
    processor.do_resize = False
    model = Mask2FormerForUniversalSegmentation.from_pretrained(model_id)
    model.to(device).eval()
    return processor, model


def infer_mask2former_num_classes(model) -> int:
    num_labels = getattr(model.config, "num_labels", None)
    if num_labels is not None:
        return int(num_labels)

    id2label = getattr(model.config, "id2label", None) or {}
    if id2label:
        return len(id2label)

    class_predictor = getattr(model, "class_predictor", None)
    if class_predictor is not None and hasattr(class_predictor, "out_features"):
        return int(class_predictor.out_features) - 1

    raise RuntimeError("Unable to infer the number of Mask2Former semantic classes")


def build_mask2former_semantic_logits(outputs, target_size: Tuple[int, int]) -> torch.Tensor:
    class_queries_logits = outputs.class_queries_logits
    masks_queries_logits = outputs.masks_queries_logits

    masks_classes = class_queries_logits.softmax(dim=-1)[..., :-1]
    masks_probs = torch.nn.functional.interpolate(
        masks_queries_logits,
        size=target_size,
        mode="bilinear",
        align_corners=False,
    ).sigmoid()
    return torch.einsum("bqc, bqhw -> bchw", masks_classes, masks_probs)


def finalize_semantic_prediction(logit_sum, weight_sum, chunk_rows: int = 128) -> np.ndarray:
    h, w, _ = logit_sum.shape
    pred = np.zeros((h, w), dtype=np.uint8)

    for y0 in range(0, h, chunk_rows):
        y1 = min(y0 + chunk_rows, h)
        logits_chunk = np.asarray(logit_sum[y0:y1], dtype=np.float32)
        weights_chunk = np.maximum(np.asarray(weight_sum[y0:y1], dtype=np.float32), 1e-6)
        pred[y0:y1] = np.argmax(logits_chunk / weights_chunk[..., None], axis=-1).astype(np.uint8)

    return pred


def count_uncovered_pixels(weight_sum, chunk_rows: int = 512) -> int:
    h = weight_sum.shape[0]
    uncovered = 0
    for y0 in range(0, h, chunk_rows):
        y1 = min(y0 + chunk_rows, h)
        uncovered += int(np.sum(np.asarray(weight_sum[y0:y1]) <= 0))
    return uncovered


@torch.no_grad()
def segment_image_mask2former(
    processor,
    model,
    img_pil: Image.Image,
    patch_size: int,
    stride: int,
    device: str,
    num_classes: int,
    batch_size: int = 4,
) -> np.ndarray:
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")
    img_arr = np.array(img_pil)
    h, w = img_arr.shape[:2]
    ys = build_window_starts(h, patch_size, stride)
    xs = build_window_starts(w, patch_size, stride)
    windows = [(y0, x0) for y0 in ys for x0 in xs]

    use_memmap = (h * w * num_classes * np.dtype(np.float32).itemsize) > 1_500_000_000
    full_weight = make_weight_map(patch_size)

    with tempfile.TemporaryDirectory(prefix="mask2former_acc_", dir=OUTPUT_DIR if os.path.isdir(OUTPUT_DIR) else None) as tmp_dir:
        if use_memmap:
            print("[INFO] Using disk-backed accumulators for large-image logits fusion...")
            logit_sum = np.memmap(
                os.path.join(tmp_dir, "logit_sum.dat"),
                dtype=np.float32,
                mode="w+",
                shape=(h, w, num_classes),
            )
            weight_sum = np.memmap(
                os.path.join(tmp_dir, "weight_sum.dat"),
                dtype=np.float32,
                mode="w+",
                shape=(h, w),
            )
            logit_sum[:] = 0.0
            weight_sum[:] = 0.0
        else:
            logit_sum = np.zeros((h, w, num_classes), dtype=np.float32)
            weight_sum = np.zeros((h, w), dtype=np.float32)

        for start in range(0, len(windows), batch_size):
            group = windows[start:start + batch_size]
            patches = []
            for y0, x0 in group:
                y1, x1 = min(y0 + patch_size, h), min(x0 + patch_size, w)
                ph, pw = y1 - y0, x1 - x0
                patch = img_arr[y0:y1, x0:x1]
                if ph < patch_size or pw < patch_size:
                    patch = np.pad(
                        patch,
                        ((0, patch_size - ph), (0, patch_size - pw), (0, 0)),
                        mode="edge",
                    )
                patches.append(patch)

            inputs = processor(images=patches, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}
            outputs = model(**inputs)
            logits = build_mask2former_semantic_logits(outputs, target_size=(patch_size, patch_size))
            logits = logits.permute(0, 2, 3, 1).detach().cpu().numpy()
            if logits.shape[-1] != num_classes:
                raise RuntimeError(
                    f"Mask2Former class mismatch: expected {num_classes}, got {logits.shape[-1]}"
                )

            for index, (y0, x0) in enumerate(group):
                y1, x1 = min(y0 + patch_size, h), min(x0 + patch_size, w)
                ph, pw = y1 - y0, x1 - x0
                weight = full_weight[:ph, :pw]
                weight_sum[y0:y1, x0:x1] += weight
                logit_sum[y0:y1, x0:x1] += logits[index, :ph, :pw] * weight[..., None]

        uncovered = count_uncovered_pixels(weight_sum)
        if uncovered > 0:
            raise RuntimeError(f"Sliding window bug: {uncovered} pixels never covered")

        pred = finalize_semantic_prediction(logit_sum, weight_sum)
        del logit_sum
        del weight_sum

    return pred


def build_cost_map(route_mask: np.ndarray, route_costs: Dict[int, float]) -> np.ndarray:
    cost = np.zeros(route_mask.shape, dtype=np.float32)
    for cls_id, cls_cost in route_costs.items():
        cost[route_mask == cls_id] = float(cls_cost)
    return cost


def run_segmentation(
    image: str,
    output_dir: Optional[str] = None,
    model: str = "mfaytin/mask2former-satellite",
    hf_endpoint: Optional[str] = None,
    patch_size: int = 512,
    stride: int = 256,
    max_size: int = 0,
    smooth_kernel: int = 3,
    overlay_alpha: float = 0.40,
    save_costmap: bool = False,
    vis_only: bool = False,
    infer_batch_size: int = 4,
) -> Dict[str, str]:
    """
    Segment a satellite GeoTIFF/PNG into fine + coarse routing masks and PNGs.

    Returns dict with paths: fine_npy, coarse_npy, fine_vis, coarse_vis.
    """
    _ensure_dirs()

    if not vis_only:
        configure_hf_hub(hf_endpoint)

    if stride > patch_size:
        print(f"[WARN] stride ({stride}) > patch_size ({patch_size}); overlap is zero or negative.")
    if max_size < 0:
        raise ValueError("max_size must be >= 0")

    Image.MAX_IMAGE_PIXELS = None
    out_dir = os.path.abspath(output_dir) if output_dir else OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    img, geo = open_image_with_optional_geo(image)
    img_arr = np.array(img)
    h0, w0 = img_arr.shape[:2]
    base = os.path.splitext(os.path.basename(image))[0]
    fine_npy_path = os.path.join(out_dir, f"{base}_openearthmap_fine_mask.npy")
    coarse_npy_path = os.path.join(out_dir, f"{base}_routing_coarse_mask.npy")
    fine_vis_path = os.path.join(out_dir, f"{base}_openearthmap_fine.png")
    coarse_vis_path = os.path.join(out_dir, f"{base}_routing_coarse.png")

    result_paths = {
        "fine_npy": fine_npy_path,
        "coarse_npy": coarse_npy_path,
        "fine_vis": fine_vis_path,
        "coarse_vis": coarse_vis_path,
    }

    if vis_only:
        if not os.path.isfile(fine_npy_path) or not os.path.isfile(coarse_npy_path):
            raise FileNotFoundError(
                f"vis-only requires existing masks: {fine_npy_path} and {coarse_npy_path}"
            )
        fine_mask = np.load(fine_npy_path)
        coarse_mask = np.load(coarse_npy_path)
        mh, mw = fine_mask.shape[:2]
        if img_arr.shape[0] != mh or img_arr.shape[1] != mw:
            img_arr = np.array(
                Image.fromarray(img_arr).resize((mw, mh), Image.BILINEAR)
            )
        save_visualization(
            img_arr, fine_mask, OEM_CLASSES, "OpenEarthMap fine classes",
            fine_vis_path, overlay_alpha=overlay_alpha,
        )
        save_visualization(
            img_arr, coarse_mask, ROUTE_CLASSES, "Routing coarse classes",
            coarse_vis_path, overlay_alpha=overlay_alpha,
        )
        print(f"Saved fine visualization: {fine_vis_path}")
        print(f"Saved coarse visualization: {coarse_vis_path}")
        return result_paths

    device = resolve_inference_device()
    original_geo = geo

    log_lines = [
        f"[{datetime.now().isoformat()}] segment.py",
        f"image: {image}",
        f"model: {model}",
        f"patch_size: {patch_size}",
        f"stride: {stride}",
        f"infer_batch_size: {infer_batch_size}",
        f"max_size: {max_size}",
        f"smooth_kernel: {smooth_kernel}",
        f"device: {device}",
        f"original_shape: {h0}x{w0}",
        f"has_geo: {geo is not None}",
    ]

    if max_size > 0 and max(h0, w0) > max_size:
        scale = max_size / max(h0, w0)
        new_h = max(1, int(round(h0 * scale)))
        new_w = max(1, int(round(w0 * scale)))
        img = img.resize((new_w, new_h), Image.BILINEAR)
        if geo is not None:
            geo = GeoMeta(crs=geo.crs, transform=geo.transform, width=w0, height=h0)
        log_lines.append(f"resized_to: {new_h}x{new_w}")
    else:
        log_lines.append("resized_to: disabled")

    img_arr = np.array(img)

    print("[INFO] Loading remote-sensing model...")
    processor, model_obj = load_mask2former_remote(device, model)
    num_classes = infer_mask2former_num_classes(model_obj)
    log_lines.append(f"model_num_classes: {num_classes}")
    log_lines.append(f"processor_do_resize: {getattr(processor, 'do_resize', None)}")
    if num_classes != len(OEM_CLASSES):
        raise RuntimeError(
            f"Configured class map expects {len(OEM_CLASSES)} OpenEarthMap classes, but model reports {num_classes}"
        )

    print("[INFO] Running sliding-window inference...")
    fine_mask = segment_image_mask2former(
        processor,
        model_obj,
        img,
        patch_size,
        stride,
        device,
        num_classes=num_classes,
        batch_size=infer_batch_size,
    )

    coarse_mask = remap_mask(fine_mask, OEM_TO_ROUTE, default=0)
    if smooth_kernel and smooth_kernel > 1:
        coarse_mask = majority_smooth(
            coarse_mask,
            num_classes=max(ROUTE_CLASSES) + 1,
            kernel=smooth_kernel,
            device=device,
        )

    log_path = os.path.join(LOG_DIR, "segment_landcover_routing.log")
    save_visualization(
        img_arr,
        fine_mask,
        OEM_CLASSES,
        "OpenEarthMap fine classes",
        fine_vis_path,
        overlay_alpha=overlay_alpha,
    )
    save_visualization(
        img_arr,
        coarse_mask,
        ROUTE_CLASSES,
        "Routing coarse classes",
        coarse_vis_path,
        overlay_alpha=overlay_alpha,
    )
    np.save(fine_npy_path, fine_mask)
    np.save(coarse_npy_path, coarse_mask)

    log_lines.append(f"saved_fine_vis: {fine_vis_path}")
    log_lines.append(f"saved_coarse_vis: {coarse_vis_path}")
    log_lines.append(f"saved_fine_mask: {fine_npy_path}")
    log_lines.append(f"saved_coarse_mask: {coarse_npy_path}")

    fine_unique, fine_counts = np.unique(fine_mask, return_counts=True)
    for u, c in zip(fine_unique.tolist(), fine_counts.tolist()):
        name = OEM_CLASSES.get(int(u), ("unknown", "#888888"))[0]
        log_lines.append(f"fine class {u} ({name}): {c} px ({100.0 * c / fine_mask.size:.2f}%)")

    coarse_unique, coarse_counts = np.unique(coarse_mask, return_counts=True)
    for u, c in zip(coarse_unique.tolist(), coarse_counts.tolist()):
        name = ROUTE_CLASSES.get(int(u), ("unknown", "#888888"))[0]
        log_lines.append(f"coarse class {u} ({name}): {c} px ({100.0 * c / coarse_mask.size:.2f}%)")

    if save_costmap:
        cost_map = build_cost_map(coarse_mask, DEFAULT_ROUTE_COSTS)
        cost_npy_path = os.path.join(out_dir, f"{base}_routing_cost.npy")
        cost_png_path = os.path.join(out_dir, f"{base}_routing_cost.png")
        np.save(cost_npy_path, cost_map)
        save_cost_visualization(cost_map, cost_png_path)
        log_lines.append(f"saved_cost_npy: {cost_npy_path}")
        log_lines.append(f"saved_cost_png: {cost_png_path}")
        result_paths["cost_npy"] = cost_npy_path
        result_paths["cost_png"] = cost_png_path

        if original_geo is not None:
            cost_tif_path = os.path.join(out_dir, f"{base}_routing_cost.tif")
            save_mask_geotiff(cost_map.astype(np.float32), cost_tif_path, original_geo)
            log_lines.append(f"saved_cost_tif: {cost_tif_path}")

    if original_geo is not None:
        fine_tif_path = os.path.join(out_dir, f"{base}_openearthmap_fine_mask.tif")
        coarse_tif_path = os.path.join(out_dir, f"{base}_routing_coarse_mask.tif")
        save_mask_geotiff(fine_mask.astype(np.uint8), fine_tif_path, original_geo)
        save_mask_geotiff(coarse_mask.astype(np.uint8), coarse_tif_path, original_geo)
        log_lines.append(f"saved_fine_tif: {fine_tif_path}")
        log_lines.append(f"saved_coarse_tif: {coarse_tif_path}")

    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))

    print(f"Saved fine visualization: {fine_vis_path}")
    print(f"Saved coarse visualization: {coarse_vis_path}")
    print(f"Saved fine mask: {fine_npy_path}")
    print(f"Saved coarse mask: {coarse_npy_path}")
    print("Fine classes:", {OEM_CLASSES.get(int(u), ("?", "#000000"))[0]: int(c) for u, c in zip(fine_unique, fine_counts)})
    print(
        "Coarse classes:",
        {ROUTE_CLASSES.get(int(u), ("?", "#000000"))[0]: int(c) for u, c in zip(coarse_unique, coarse_counts)},
    )
    return result_paths


def main():
    parser = argparse.ArgumentParser(description="Remote-sensing land-cover segmentation for routing")
    parser.add_argument("--image", type=str, required=True, help="Input RGB image or GeoTIFF")
    parser.add_argument(
        "--vis-only",
        action="store_true",
        help="Only regenerate visualization from existing .npy masks (skip inference)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory for .npy masks and output images; default: masking_pipeline/outputs",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="mfaytin/mask2former-satellite",
        help="HF model id or local directory with config/weights",
    )
    parser.add_argument(
        "--hf-endpoint",
        type=str,
        default=None,
        help="HF Hub mirror base URL (e.g. https://hf-mirror.com). Default: HF_ENDPOINT env",
    )
    parser.add_argument("--patch-size", type=int, default=512)
    parser.add_argument("--stride", type=int, default=256)
    parser.add_argument("--infer-batch-size", type=int, default=4, help="Sliding windows per inference batch")
    parser.add_argument(
        "--max-size",
        type=int,
        default=0,
        help="Resize longest side before inference; 0 disables resizing",
    )
    parser.add_argument(
        "--smooth-kernel",
        type=int,
        default=3,
        help="Majority smoothing on coarse routing mask. 0 or 1 disables",
    )
    parser.add_argument("--overlay-alpha", type=float, default=0.40)
    parser.add_argument(
        "--save-costmap",
        action="store_true",
        help="Also save a simple routing cost raster derived from coarse classes",
    )
    args = parser.parse_args()
    run_segmentation(
        image=args.image,
        output_dir=args.output_dir,
        model=args.model,
        hf_endpoint=args.hf_endpoint,
        patch_size=args.patch_size,
        stride=args.stride,
        max_size=args.max_size,
        smooth_kernel=args.smooth_kernel,
        overlay_alpha=args.overlay_alpha,
        save_costmap=args.save_costmap,
        vis_only=args.vis_only,
        infer_batch_size=args.infer_batch_size,
    )


if __name__ == "__main__":
    main()
