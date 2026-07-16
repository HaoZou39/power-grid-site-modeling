from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

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
    keep = np.ones(arr.shape[0], dtype=bool)
    for i in range(arr.shape[0]):
        if not keep[i]:
            continue
        dominated = np.all(arr <= arr[i], axis=1) & np.any(arr < arr[i], axis=1)
        dominated[i] = False
        if np.any(dominated):
            keep[i] = False
    return [feasible[i] for i in range(len(feasible)) if keep[i]]

