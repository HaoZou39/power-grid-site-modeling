"""Exact lexicographic sweep; only previously nondominated values need testing."""

import numpy as np
from numba import njit


@njit(cache=True)
def _sweep(values):
    keep = np.ones(len(values), dtype=np.bool_)
    front = np.empty(len(values), dtype=np.int64)
    size = 0
    for i in range(len(values)):
        duplicate = False
        for place in range(size):
            j = front[place]
            if (values[j, 0] <= values[i, 0] and values[j, 1] <= values[i, 1]
                    and values[j, 2] <= values[i, 2] and values[j, 3] <= values[i, 3]):
                duplicate = (values[j, 0] == values[i, 0] and values[j, 1] == values[i, 1]
                             and values[j, 2] == values[i, 2] and values[j, 3] == values[i, 3])
                keep[i] = duplicate
                break
        if keep[i] and not duplicate:
            front[size] = i
            size += 1
    return keep


def four_objective_front(values):
    order = np.lexsort(tuple(values[:, column] for column in (3, 2, 1, 0)))
    keep = np.empty(len(values), dtype=bool)
    keep[order] = _sweep(values[order])
    return keep
