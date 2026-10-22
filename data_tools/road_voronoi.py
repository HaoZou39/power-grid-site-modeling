"""Exact cell-centre nearest-road labels with CPU and CUDA backends."""

from importlib.util import find_spec

import numpy as np
import torch

try:
    from numba import njit, prange
except ImportError:  # pragma: no cover - the documented environment includes numba
    njit = None
    prange = range

if njit is not None:

    @njit(cache=True, parallel=True)
    def _segment_voronoi_numba(seg, height, width, resolution):
        """Nearest segment id at each cell center. Ties keep the smaller id."""

        n = seg.shape[0]
        ax = seg[:, 0]
        ay = seg[:, 1]
        bx = seg[:, 2]
        by = seg[:, 3]
        abx = bx - ax
        aby = by - ay
        denom = abx * abx + aby * aby
        labels = np.empty((height, width), np.int64)
        for y in prange(height):
            py = np.float32((y + 0.5) * resolution)
            for x in range(width):
                px = np.float32((x + 0.5) * resolution)
                best_i = np.int64(0)
                best_d = np.float32(1e38)
                for i in range(n):
                    t = ((px - ax[i]) * abx[i] + (py - ay[i]) * aby[i]) / denom[i]
                    if t < 0.0:
                        t = np.float32(0.0)
                    elif t > 1.0:
                        t = np.float32(1.0)
                    dx = px - (ax[i] + t * abx[i])
                    dy = py - (ay[i] + t * aby[i])
                    dist2 = dx * dx + dy * dy
                    if dist2 < best_d:
                        best_d = dist2
                        best_i = i
                labels[y, x] = best_i
        return labels

else:  # pragma: no cover
    _segment_voronoi_numba = None


def resolve_voronoi_backend(backend: str = "auto", device: str = "cuda") -> str:
    if backend not in {"auto", "cpu", "cuda"}:
        raise ValueError("road Voronoi backend must be auto, cpu or cuda")
    if backend == "cpu":
        return "cpu"
    target = torch.device(device)
    if target.type != "cuda":
        raise ValueError("road Voronoi CUDA device must be cuda or cuda:<index>")
    available = torch.cuda.is_available()
    has_triton = find_spec("triton") is not None
    if backend == "auto" and not (available and has_triton):
        return "cpu"
    if not available:
        raise RuntimeError("CUDA road Voronoi requested but CUDA is unavailable")
    if not has_triton:
        raise ImportError("CUDA road Voronoi requires Triton; select cpu or install Triton")
    if target.index is not None and target.index >= torch.cuda.device_count():
        raise ValueError(f"CUDA road Voronoi device does not exist: {device}")
    return "cuda"


def compute_segment_voronoi(
    segments: np.ndarray, height: int, width: int, resolution_m: float = 1.0,
    chunk_points: int = 8192, *, backend: str = "auto", device: str = "cuda",
    gpu_chunk_points: int = 1048576, segment_tile: int = 128,
) -> np.ndarray:
    if segments.ndim != 2 or segments.shape[1] != 4 or len(segments) == 0:
        raise ValueError("segments must have non-empty shape [N_seg, 4]")
    if height <= 0 or width <= 0 or int(height) != height or int(width) != width:
        raise ValueError("Voronoi height and width must be positive integers")
    if not np.isfinite(resolution_m) or resolution_m <= 0:
        raise ValueError("Voronoi resolution must be finite and positive")
    if any(int(n) != n or n <= 0 for n in (chunk_points, gpu_chunk_points)):
        raise ValueError("Voronoi chunk sizes must be positive integers")
    if segment_tile not in {32, 64, 128, 256}:
        raise ValueError("Voronoi segment_tile must be 32, 64, 128 or 256")
    seg = np.ascontiguousarray(segments, dtype=np.float32)
    if not np.isfinite(seg).all():
        raise ValueError("road segments must be finite float32 values")
    denom = np.sum((seg[:, 2:4] - seg[:, :2]) ** 2, axis=1)
    if np.any(denom <= 0):
        raise ValueError("road segments contain zero-length segment")
    if not np.isfinite(denom).all():
        raise ValueError("road segment squared lengths overflow float32")
    actual = resolve_voronoi_backend(backend, device)
    if actual == "cuda":
        from .road_voronoi_cuda import compute_cuda_voronoi

        return compute_cuda_voronoi(seg, int(height), int(width), resolution_m, device,
                                    int(gpu_chunk_points), int(segment_tile))
    if _segment_voronoi_numba is not None:
        return _segment_voronoi_numba(seg, int(height), int(width), np.float32(resolution_m))
    return _compute_segment_voronoi_numpy(seg, height, width, resolution_m, chunk_points)


def _compute_segment_voronoi_numpy(seg, height, width, resolution_m, chunk_points):
    a = seg[:, :2]
    ab = seg[:, 2:4] - a
    denom = np.sum(ab * ab, axis=1)
    labels = np.empty(height * width, dtype=np.int64)
    for start in range(0, len(labels), chunk_points):
        pixel = np.arange(start, min(start + chunk_points, len(labels)))
        p = (np.column_stack([pixel % width, pixel // width]).astype(np.float64) + 0.5)
        p = (p * np.float32(resolution_m)).astype(np.float32)
        best_d = np.full(len(p), np.float32(1e38))
        best_i = np.zeros(len(p), dtype=np.int64)
        for first in range(0, len(seg), 128):
            last = first + 128
            ap = p[:, None, :] - a[None, first:last, :]
            t = np.sum(ap * ab[None, first:last, :], axis=2) / denom[None, first:last]
            t = np.clip(t, 0.0, 1.0)
            diff = p[:, None, :] - (a[None, first:last, :] + t[:, :, None] * ab[None, first:last, :])
            dist2 = np.sum(diff * diff, axis=2)
            index = np.argmin(dist2, axis=1)
            distance = dist2[np.arange(len(p)), index]
            improve = distance < best_d
            best_i[improve] = index[improve] + first
            best_d = np.minimum(best_d, distance)
        labels[start:start + len(p)] = best_i
    return labels.reshape(height, width)
