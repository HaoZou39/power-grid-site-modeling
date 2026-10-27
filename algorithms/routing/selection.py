"""Small native selection bundles; no conversion between NumPy and tensor state."""

from dataclasses import dataclass
from typing import Callable
import torch
from algorithms.common.nsga2 import nondominated_sort, select_population, tournament
from algorithms.common.tensor_nsga2 import crowding_distance, nondominated_rank, tournament as tensor_tournament


@dataclass(frozen=True)
class NumpySelection:
    rank: Callable
    parents: Callable
    survivors: Callable


def numpy_selection():
    return NumpySelection(nondominated_sort, tournament, select_population)


def tensor_order(rank, distance, size):
    order = torch.argsort(distance, descending=True, stable=True)
    return order[torch.argsort(rank[order], stable=True)][:size]


@dataclass(frozen=True)
class TensorSelection:
    rank: Callable
    crowding: Callable
    parents: Callable
    order: Callable


def tensor_selection():
    return TensorSelection(nondominated_rank, crowding_distance, tensor_tournament, tensor_order)
