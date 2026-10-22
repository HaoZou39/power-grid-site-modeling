"""Select the evolution implementation while sharing initialization and reporting."""

from __future__ import annotations

import numpy as np
import torch


def resolve_evolution_backend(requested: str, device: torch.device) -> str:
    if requested not in {"tensor", "numpy"}:
        raise ValueError("evolution_backend must be 'tensor' or 'numpy'")
    if device.type not in {"cpu", "cuda"}:
        raise ValueError("guided search supports CPU and CUDA devices")
    return "numpy" if device.type == "cpu" else requested


def generation_sigma(generation: int, generations: int, sigma: float, anneal_last: int, anneal_sigma_end: float | None) -> float:
    if anneal_last <= 0 or anneal_sigma_end is None or generation < generations - anneal_last:
        return float(sigma)
    slot = generation - (generations - anneal_last)
    return float(sigma + (float(anneal_sigma_end) - sigma) * (slot / max(anneal_last - 1, 1)))


def run_evolution(evaluate, *, backend: str, device: torch.device, initial: np.ndarray, **kwargs) -> np.ndarray:
    """Return final float32 raw poses; population stays in its backend during evolution."""
    if backend == "tensor":
        from .tensor_nsga2 import run_evolution as evolve

        result = evolve(evaluate, initial=torch.as_tensor(initial, dtype=torch.float64, device=device), **kwargs)
        return result.genes.to(torch.float32).cpu().numpy()
    if backend == "numpy":
        from .numpy_nsga2 import run_evolution as evolve

        result = evolve(evaluate, initial=initial, **kwargs)
        return np.stack([person.genes for person in result]).astype(np.float32)
    raise ValueError("evolution_backend must be 'tensor' or 'numpy'")
