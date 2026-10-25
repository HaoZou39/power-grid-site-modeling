"""Extract a feasible nondominated front from already evaluated records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np


def extract_feasible_pareto_front(
    records: Sequence[Mapping[str, object]],
    objective_names: Sequence[str],
    feasible_key: str = "is_feasible",
) -> list[dict[str, object]]:
    if not objective_names:
        raise ValueError("objective_names must not be empty")
    feasible: list[dict[str, object]] = []
    values: list[list[float]] = []
    for record in records:
        if bool(record.get(feasible_key, False)):
            row = []
            for name in objective_names:
                if name not in record:
                    raise ValueError(f"record is missing objective {name!r}")
                value = float(record[name])
                if not np.isfinite(value):
                    raise ValueError(f"objective {name!r} contains NaN or Inf")
                row.append(value)
            feasible.append(dict(record))
            values.append(row)
    if not feasible:
        return []
    arr = np.asarray(values, dtype=np.float64)
    if arr.shape[1] == 3:
        keep = _three_objective_front(arr)
        return [record for record, selected in zip(feasible, keep) if selected]
    keep = np.ones(arr.shape[0], dtype=bool)
    for i in range(arr.shape[0]):
        if not keep[i]:
            continue
        dominated = np.all(arr <= arr[i], axis=1) & np.any(arr < arr[i], axis=1)
        dominated[i] = False
        if np.any(dominated):
            keep[i] = False
    return [feasible[i] for i in range(len(feasible)) if keep[i]]


def _three_objective_front(values: np.ndarray) -> np.ndarray:
    """Exact O(N log N) minimization sweep; identical points never dominate each other."""
    order = np.lexsort((values[:, 2], values[:, 1], values[:, 0]))
    sorted_values = values[order]
    _, ranks = np.unique(sorted_values[:, 1], return_inverse=True)
    tree = np.full(int(ranks.max()) + 2, np.inf)
    keep = np.ones(len(values), dtype=bool)
    starts = np.r_[0, np.flatnonzero(np.any(sorted_values[1:] != sorted_values[:-1], axis=1)) + 1]
    ends = np.r_[starts[1:], len(values)]
    for start, end in zip(starts, ends):
        rank = int(ranks[start]) + 1
        z = sorted_values[start, 2]
        best = np.inf
        index = rank
        while index:
            best = min(best, tree[index])
            index -= index & -index
        if best <= z:
            keep[order[start:end]] = False
        # Publish the group only after querying: exact duplicates remain equivalent.
        index = rank
        while index < len(tree):
            tree[index] = min(tree[index], z)
            index += index & -index
    return keep
