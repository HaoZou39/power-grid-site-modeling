"""距离场的可微采样。

场值放在格子中心。查询点相对格子中心做双线性插值。
落在某个格子中心时权重为 1，结果等于该格的精确值。
这一层不寻路。走不通的格子在插值张量里用有限哨兵，精确查表仍由 `query_exact` 判为不可行。
"""

from __future__ import annotations

import numpy as np
import torch

UNREACHABLE_M = 1.0e6


def torch_field(values: np.ndarray, reachable: np.ndarray) -> torch.Tensor:
    """把进站网格复制成有限张量。走不通的格子写成一个很大的距离。"""

    filled = np.array(values, dtype=np.float32, copy=True)
    filled[~reachable] = np.float32(UNREACHABLE_M)
    return torch.tensor(filled, dtype=torch.float32)


def sample_center_field(field: torch.Tensor, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
    """在连续的局部米坐标上读取一张 `[H, W]` 场。返回 shape `[B]`。"""

    if field.ndim != 2:
        raise ValueError("field must have shape [H, W]")
    if x.shape != y.shape or x.ndim != 1:
        raise ValueError("x and y must be 1D tensors of the same shape")
    height, width = field.shape
    # 场值记在格子中心 (col+0.5, row+0.5)。减去 0.5 后，查询点正好落在中心时权重为 1。
    # 这和道路 Voronoi 距离用四个角混合的采样不是同一种做法。
    u = x - 0.5
    v = y - 0.5
    col = torch.floor(u)
    row = torch.floor(v)
    fu = u - col
    fv = v - row
    col0 = col.long().clamp(0, width - 1)
    row0 = row.long().clamp(0, height - 1)
    col1 = (col0 + 1).clamp(max=width - 1)
    row1 = (row0 + 1).clamp(max=height - 1)
    value00 = field[row0, col0]
    value10 = field[row0, col1]
    value01 = field[row1, col0]
    value11 = field[row1, col1]
    return (
        (1.0 - fu) * (1.0 - fv) * value00
        + fu * (1.0 - fv) * value10
        + (1.0 - fu) * fv * value01
        + fu * fv * value11
    )
