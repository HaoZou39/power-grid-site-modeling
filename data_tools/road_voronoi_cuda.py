"""Bounded-memory nearest-segment reduction on CUDA (loaded only on demand)."""

import numpy as np
import torch
import triton
import triton.language as tl
from triton.language.extra.cuda import libdevice


@triton.jit
def _nearest_segment_kernel(
    segments, labels, start, count, width, resolution, n_segments,
    PIXELS: tl.constexpr, SEGMENTS: tl.constexpr,
):
    offset = tl.program_id(0) * PIXELS + tl.arange(0, PIXELS)
    pixel = start + offset
    # Numba forms cell centres in float64 and rounds the result to float32.
    px = (((pixel % width).to(tl.float64) + 0.5) * resolution.to(tl.float64)).to(tl.float32)
    py = (((pixel // width).to(tl.float64) + 0.5) * resolution.to(tl.float64)).to(tl.float32)
    best_d = tl.full((PIXELS,), 1.0e38, tl.float32)
    best_i = tl.full((PIXELS,), 0, tl.int32)
    for begin in range(tl.cdiv(n_segments, SEGMENTS)):
        index = begin * SEGMENTS + tl.arange(0, SEGMENTS)
        valid = index < n_segments
        ax = tl.load(segments + index * 4, valid, other=0)
        ay = tl.load(segments + index * 4 + 1, valid, other=0)
        bx = tl.load(segments + index * 4 + 2, valid, other=1)
        by = tl.load(segments + index * 4 + 3, valid, other=0)
        abx, aby = bx - ax, by - ay
        denom = abx * abx + aby * aby
        numerator = (px[:, None] - ax[None, :]) * abx[None, :] + (py[:, None] - ay[None, :]) * aby[None, :]
        t = tl.minimum(tl.maximum(libdevice.div_rn(numerator, denom[None, :]), 0.0), 1.0)
        dx = px[:, None] - (ax[None, :] + t * abx[None, :])
        dy = py[:, None] - (ay[None, :] + t * aby[None, :])
        dist = tl.where(valid[None, :], dx * dx + dy * dy, float("inf"))
        block_d = tl.min(dist, axis=1)
        block_i = tl.min(tl.where(dist == block_d[:, None], index[None, :], 2147483647), axis=1)
        improve = block_d < best_d
        best_i = tl.where(improve, block_i, best_i)
        best_d = tl.minimum(best_d, block_d)
    tl.store(labels + offset, best_i.to(tl.int64), offset < count)


def compute_cuda_voronoi(
    segments: np.ndarray, height: int, width: int, resolution: float,
    device: str, chunk_points: int, segment_tile: int,
) -> np.ndarray:
    result = np.empty((height, width), dtype=np.int64)
    flat = result.reshape(-1)
    with torch.inference_mode(), torch.cuda.device(device):
        roads = torch.as_tensor(segments, device=device)
        batch = torch.empty(min(chunk_points, flat.size), device=device, dtype=torch.int64)
        for start in range(0, flat.size, chunk_points):
            count = min(chunk_points, flat.size - start)
            _nearest_segment_kernel[(triton.cdiv(count, 16),)](
                roads, batch, start, count, width, float(np.float32(resolution)), len(segments),
                PIXELS=16, SEGMENTS=segment_tile, enable_fp_fusion=False,
            )
            flat[start:start + count] = batch[:count].cpu().numpy()
    return result
