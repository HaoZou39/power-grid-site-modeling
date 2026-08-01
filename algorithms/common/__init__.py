"""Shared multi-objective algorithm utilities."""

from .pareto import extract_feasible_pareto_front
from .scalarization import (
    OBJECTIVE_NAMES,
    compute_normalization_from_samples,
    generate_weight_grid,
    normalize_weight_vector,
    scalarize_tchebycheff_numpy,
    scalarize_tchebycheff_torch,
    scalarize_tchebycheff_torch_batched,
)
from .weiszfeld import compute_demand_ideal_value, compute_weighted_geometric_median

__all__ = [
    "OBJECTIVE_NAMES",
    "compute_demand_ideal_value",
    "compute_normalization_from_samples",
    "compute_weighted_geometric_median",
    "extract_feasible_pareto_front",
    "generate_weight_grid",
    "normalize_weight_vector",
    "scalarize_tchebycheff_numpy",
    "scalarize_tchebycheff_torch",
    "scalarize_tchebycheff_torch_batched",
]
