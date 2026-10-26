"""Exact float64 grid operations in bounded tensor work tiles."""

import math

import torch


def sample_dem(dem, points):
    height, width = dem.shape
    valid = torch.isfinite(points).all(-1) & (points >= 0).all(-1)
    valid &= (points[..., 0] <= width) & (points[..., 1] <= height)
    xy = (points - .5).clamp_min(0).minimum(points.new_tensor([width - 1, height - 1]))
    col, row = xy.long().unbind(-1)
    right, bottom = (col + 1).clamp_max(width - 1), (row + 1).clamp_max(height - 1)
    fx, fy = (xy - xy.long()).unbind(-1)
    samples = torch.stack((dem[row, col], dem[row, right], dem[bottom, col], dem[bottom, right]), -1).double()
    weights = torch.stack(((1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy), -1)
    values = (torch.where(weights > 0, samples, 0) * weights).sum(-1)
    return torch.where(valid, values, torch.nan)


def tower_flags(dem, blocked, points, radius, workspace_bytes):
    height, width = dem.shape
    outside = ((points < radius) | (points > points.new_tensor([width, height]) - radius)).any(-1)
    hit = torch.zeros(len(points), dtype=torch.bool, device=points.device)
    missing = ~torch.isfinite(sample_dem(dem, points))
    near = torch.zeros_like(hit)
    side = 2 * math.ceil(radius) + 5
    offset = math.ceil(radius) + 2
    limit = radius + 32 * torch.finfo(points.dtype).eps * points.abs().amax(-1).clamp_min(max(1., radius))
    centers = points.floor().long()
    cells_per_tile = max(1, workspace_bytes // max(1, len(points)) // 160)
    for start in range(0, side * side, cells_per_tile):
        ids = torch.arange(start, min(start + cells_per_tile, side * side), device=points.device)
        cols = centers[:, 0, None] + ids[None, :] % side - offset
        rows = centers[:, 1, None] + ids[None, :] // side - offset
        dx = points[:, 0, None] - points[:, 0, None].maximum(cols).minimum(cols + 1)
        dy = points[:, 1, None] - points[:, 1, None].maximum(rows).minimum(rows + 1)
        squared = dx.square() + dy.square()
        in_circle = squared <= limit[:, None].square()
        valid = (cols >= 0) & (cols < width) & (rows >= 0) & (rows < height)
        rr, cc = rows.clamp(0, height - 1), cols.clamp(0, width - 1)
        covered = in_circle & valid
        hit |= (covered & blocked[rr, cc]).any(-1)
        missing |= (covered & ~torch.isfinite(dem[rr, cc])).any(-1)
        sensitive = blocked[rr, cc] | ~torch.isfinite(dem[rr, cc])
        margin = 128 * torch.finfo(points.dtype).eps * points.abs().amax(-1).clamp_min(max(1., radius)) * max(1., radius)
        near |= (((squared - limit[:, None].square()).abs() <= margin[:, None]) & valid & sensitive).any(-1)
    near |= (points - radius).abs().amin(-1) < 1e-8
    near |= (points - points.new_tensor([width, height]) + radius).abs().amin(-1) < 1e-8
    return outside, hit, missing, near


def crossing_lengths(starts, ends, mask, workspace_bytes):
    result = starts.new_zeros(len(starts))
    if not len(starts):
        return result
    delta = ends - starts
    lo, hi = starts.minimum(ends), starts.maximum(ends)
    counts = (hi.ceil() - lo.floor() - 1).clamp_min(0).long()
    counts = torch.where(delta != 0, counts, 0)
    width_x, width_y = counts.amax(0).tolist()
    events = width_x + width_y + 2
    batch_size = max(1, workspace_bytes // max(1, events) // 160)
    height, width = mask.shape
    for begin in range(0, len(starts), batch_size):
        a, d, lower, n = starts[begin:begin + batch_size], delta[begin:begin + batch_size], lo[begin:begin + batch_size], counts[begin:begin + batch_size]
        pieces = [a.new_zeros((len(a), 1)), a.new_ones((len(a), 1))]
        for axis, size in enumerate((width_x, width_y)):
            k = torch.arange(size, device=a.device)[None, :]
            lines = lower[:, axis, None].floor() + 1 + k
            t = (lines - a[:, axis, None]) / torch.where(d[:, axis, None] != 0, d[:, axis, None], 1)
            pieces.append(torch.where(k < n[:, axis, None], t, torch.inf))
        boundaries = torch.cat(pieces, 1).sort(dim=1).values
        left, right = boundaries[:, :-1], boundaries[:, 1:]
        valid = (left >= 0) & (right <= 1) & (right > left)
        t = torch.where(valid, (left + right) / 2, 0)
        points = a[:, None] + t[..., None] * d[:, None]
        cols, rows = points.floor().long().unbind(-1)
        hit = torch.zeros_like(valid)
        for dc, dr in ((0, 0), (1, 0), (0, 1), (1, 1)):
            rr, cc = rows - dr, cols - dc
            on_edge = torch.ones(len(a), device=a.device, dtype=torch.bool)
            if dc:
                on_edge &= (d[:, 0] == 0) & (a[:, 0] == a[:, 0].floor())
            if dr:
                on_edge &= (d[:, 1] == 0) & (a[:, 1] == a[:, 1].floor())
            inside = (rr >= 0) & (rr < height) & (cc >= 0) & (cc < width)
            hit |= inside & on_edge[:, None] & mask[rr.clamp(0, height - 1), cc.clamp(0, width - 1)]
        amounts = torch.where(valid & hit, right - left, 0).sum(1)
        result[begin:begin + len(a)] = amounts * torch.linalg.vector_norm(d, dim=1)
    return result
