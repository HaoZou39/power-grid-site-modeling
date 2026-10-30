"""Reporting metrics only: no normalization or reference enters evolution."""

import numpy as np

from algorithms.common.four_objective_front import four_objective_front


def reference_front(fronts):
    fronts = [front for front in fronts if len(front)]
    if not fronts:
        return np.empty((0, 4))
    values = np.concatenate(fronts, axis=0)
    return np.unique(values[four_objective_front(values)], axis=0)


def compare_front(approximation, reference, minimum, scale):
    if not len(reference):
        raise ValueError("reference front must not be empty")
    if not len(approximation):
        return {"igd_plus": None, "epsilon": None, "coverage": 0., "status": "no_feasible_solution"}
    a, r = (approximation - minimum) / scale, (reference - minimum) / scale
    distances, epsilons, covered = [], [], []
    for point in r:
        delta = a - point
        distances.append(np.sqrt(np.square(np.maximum(delta, 0)).sum(1)).min())
        epsilons.append(delta.max(1).min())
        covered.append(np.any((delta <= 0).all(1)))
    return {"igd_plus": float(np.mean(distances)), "epsilon": float(np.max(epsilons)),
            "coverage": float(np.mean(covered)), "status": "ok"}
