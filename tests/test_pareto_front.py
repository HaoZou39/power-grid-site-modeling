import itertools
import numpy as np
import pytest

from algorithms.common.pareto import extract_feasible_pareto_front


def _oracle(values):
    return [i for i, row in enumerate(values)
            if not np.any(np.all(values <= row, axis=1) & np.any(values < row, axis=1))]


@pytest.mark.parametrize("kind", ["ties", "random", "duplicate", "chain", "antichain"])
def test_exact_three_objective_front_matches_exhaustive_oracle(kind):
    rng = np.random.default_rng(17)
    if kind == "ties":
        values = np.array(list(itertools.product(range(4), repeat=3)), dtype=float)
    elif kind == "random":
        values = rng.normal(size=(500,3))
    elif kind == "duplicate":
        values = np.repeat(rng.integers(-5,5,size=(80,3)), 3, axis=0)
    elif kind == "chain":
        values = np.repeat(np.arange(100)[:,None], 3, axis=1)
    else:
        x = np.arange(100)
        values = np.stack([x,-x,x*0], axis=1)
    rng.shuffle(values)
    records = [dict(id=i, a=row[0], b=row[1], c=row[2], is_feasible=True) for i,row in enumerate(values)]
    actual = extract_feasible_pareto_front(records, ("a","b","c"))
    assert [row["id"] for row in actual] == _oracle(values)


def test_duplicate_front_points_and_infeasible_nan_are_preserved_correctly():
    records = [dict(id=i, a=1, b=2, c=3, is_feasible=True) for i in range(5)]
    records.append(dict(id=5,a=np.nan,b=0,c=0,is_feasible=False))
    assert [row["id"] for row in extract_feasible_pareto_front(records,("a","b","c"))] == list(range(5))
    records[-1]["is_feasible"] = True
    with pytest.raises(ValueError, match="NaN"):
        extract_feasible_pareto_front(records,("a","b","c"))
