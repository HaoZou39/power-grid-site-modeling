"""Batched variable-length operators; endpoints remain external."""

import torch

from modeling.routing.tensor_types import TowerBatch, connected_points

def _insert(xy, counts, where, points, active):
    columns = torch.arange(xy.shape[1], device=xy.device)[None, :]
    source = (columns - ((columns > where[:, None]) & active[:, None]).long()).clamp(0, xy.shape[1] - 1)
    xy = xy.gather(1, source[..., None].expand(-1, -1, 2))
    xy = torch.where(((columns == where[:, None]) & active[:, None])[..., None], points[:, None], xy)
    return xy, counts + active.long()


def _delete(xy, counts, where, active):
    columns = torch.arange(xy.shape[1], device=xy.device)[None, :]
    source = (columns + ((columns >= where[:, None]) & active[:, None])).clamp_max(xy.shape[1] - 1)
    return xy.gather(1, source[..., None].expand(-1, -1, 2)), counts - active.long()

@torch.no_grad()
def vary(first, second, *, start, end, lower, upper, sigma, radius, size, generator,
         target_count=None, actions=None, locations=None, cuts=None, noise=None):
    device, count = first.xy.device, len(first.xy)
    width = max(1, upper * 2 + 1)
    xy = torch.nn.functional.pad(first.xy, (0, 0, 0, width - first.xy.shape[1]))
    other = torch.nn.functional.pad(second.xy, (0, 0, 0, width - second.xy.shape[1]))
    n, m = first.counts.clone(), second.counts
    if actions is None:
        actions = torch.randint(4, (count,), device=device, generator=generator)
    if locations is None:
        locations = torch.rand(count, device=device, generator=generator, dtype=torch.float64)
    if cuts is None:
        cuts = torch.rand((count, 2), device=device, generator=generator, dtype=torch.float64)
    if noise is None:
        noise = torch.randn((count, 2), device=device, generator=generator, dtype=torch.float64)
    move = (actions == 0) & (n > 0)
    insert = (actions == 1) & (n < upper)
    delete = (actions == 2) & (n > lower)
    cross = ~(move | insert | delete) & (n > 0) & (m > 0)
    rows = torch.arange(count, device=device)
    index = (locations * n).long().clamp_max(width - 1)
    xy[rows, index] += (sigma * noise) * move[:, None]
    points = connected_points(xy, n, start, end)
    index = (locations * (n + 1)).long()
    center = (points[rows, index] + points[rows, index + 1]) / 2 + sigma * noise
    xy, n = _insert(xy, n, index, center, insert)
    xy, n = _delete(xy, n, (locations * n).long(), delete)
    left = (cuts[:, 0] * (first.counts + 1)).long()
    right = (cuts[:, 1] * (m + 1)).long()
    columns = torch.arange(width, device=device)[None, :]
    source = (columns - left[:, None] + right[:, None]).clamp(0, width - 1)
    crossed = torch.where((columns < left[:, None])[..., None], xy,
                          other.gather(1, source[..., None].expand(-1, -1, 2)))
    xy = torch.where(cross[:, None, None], crossed, xy)
    n = torch.where(cross, left + m - right, n)
    desired = n.clamp(lower, upper) if target_count is None else target_count.clamp(lower, upper)
    while bool((n < desired).any()):
        points = connected_points(xy, n, start, end)
        lengths = torch.linalg.vector_norm(points[:, 1:] - points[:, :-1], dim=2)
        lengths.masked_fill_(torch.arange(width + 1, device=device)[None, :] > n[:, None], -1)
        index = lengths.argmax(1)
        center = (points[rows, index] + points[rows, index + 1]) / 2
        center += sigma * torch.randn((count, 2), device=device, generator=generator, dtype=torch.float64)
        xy, n = _insert(xy, n, index, center, n < desired)
    while bool((n > desired).any()):
        index = (torch.rand(count, device=device, generator=generator, dtype=torch.float64) * n).long()
        xy, n = _delete(xy, n, index, n > desired)
    if min(size) >= 2 * radius:
        xy = xy.clamp_min(radius).minimum(xy.new_tensor(size) - radius)
    xy = xy[:, :upper].contiguous()
    valid = torch.arange(upper, device=device)[None, :] < n[:, None]
    return TowerBatch(torch.where(valid[..., None], xy, 0), n)
