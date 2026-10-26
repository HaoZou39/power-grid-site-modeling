import numpy as np

from algorithms.common.four_objective_front import four_objective_front


def test_exact_four_objective_sweep_preserves_duplicates_and_input_order():
    rng = np.random.default_rng(31)
    for values in [rng.integers(0, 20, (200, 4)).astype(float), np.ones((100, 4)),
                   np.column_stack((np.arange(100), -np.arange(100), np.zeros((100, 2))))]:
        expected = [not np.any(np.all(values <= row, 1) & np.any(values < row, 1)) for row in values]
        np.testing.assert_array_equal(four_objective_front(values), expected)
