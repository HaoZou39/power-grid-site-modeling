"""Preflight working allocations without changing search parameters."""

import torch


def require_workspace(device, additional_bytes, budget_mib):
    device = torch.device(device)
    if device.type != "cuda":
        return
    free, _ = torch.cuda.mem_get_info(device)
    available = min(free, budget_mib * 1024**2 - torch.cuda.memory_allocated(device))
    if additional_bytes > available:
        raise MemoryError(f"routing working set on {device} exceeds memory budget; reduce evaluation batch or raise budget")
