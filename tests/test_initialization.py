"""Initial poses must cover the decoded domain and retain exact OA balance."""

from itertools import combinations

import numpy as np
import pytest
import torch

from algorithms.guided_search.initialization import sample_initial_population
from modeling.pose import compute_safe_margin, decode_raw_pose
from plugins.site_plugin import GuidedSiteConfig


@pytest.mark.parametrize("method", ["gaussian", "uniform", "taguchi"])
def test_initialization_is_finite_and_seeded(method):
    raw = sample_initial_population(100, 123, method)
    assert raw.shape == (100, 3) and raw.dtype == np.float32
    assert np.isfinite(raw).all()
    np.testing.assert_array_equal(raw, sample_initial_population(100, 123, method))
    assert not np.array_equal(raw, sample_initial_population(100, 456, method))


def test_gaussian_preserves_the_legacy_random_sequence():
    expected = np.random.default_rng(123).normal(0, 0.7, (40, 3)).astype(np.float32)
    np.testing.assert_array_equal(sample_initial_population(40, 123, "gaussian", 0.7), expected)


@pytest.mark.parametrize("popsize", [4, 9, 100, 10000])
def test_taguchi_every_factor_pair_covers_every_level_pair_once(popsize):
    levels = int(np.sqrt(popsize))
    raw = sample_initial_population(popsize, 123, "taguchi")
    unit = 1 / (1 + np.exp(-raw.astype(np.float64)))
    table = np.floor(unit * levels).astype(int)
    np.testing.assert_allclose(unit, (table + 0.5) / levels, atol=1e-7)
    for first, second in combinations(range(3), 2):
        counts = np.bincount(table[:, first] * levels + table[:, second], minlength=popsize)
        np.testing.assert_array_equal(counts, np.ones(popsize, dtype=int))


def test_uniform_covers_the_whole_decoded_domain_without_center_bias():
    raw = sample_initial_population(10000, 123, "uniform")
    unit = 1 / (1 + np.exp(-raw.astype(np.float64)))
    assert np.all(unit.min(axis=0) < 0.01) and np.all(unit.max(axis=0) > 0.99)
    np.testing.assert_allclose(unit.mean(axis=0), 0.5, atol=0.015)
    bins = (unit * 10).astype(int)
    for column in range(3):
        assert np.all(np.abs(np.bincount(bins[:, column], minlength=10) - 1000) < 150)
    np.testing.assert_array_equal(raw, sample_initial_population(10000, 123, "uniform", 5.0))


@pytest.mark.parametrize("method", ["uniform", "taguchi"])
def test_decoded_positions_and_angles_match_the_sampling_domain(cuda_device, method):
    raw = sample_initial_population(100, 123, method)
    unit = 1 / (1 + np.exp(-raw.astype(np.float64)))
    pose = decode_raw_pose(torch.tensor(raw, device=cuda_device), (1800, 1800), 77, 51.5).cpu().numpy()
    margin = compute_safe_margin(77, 51.5)
    expected = np.column_stack((margin + (1799 - 2 * margin) * unit[:, 0],
                                margin + (1799 - 2 * margin) * unit[:, 1],
                                -np.pi + 2 * np.pi * unit[:, 2]))
    np.testing.assert_allclose(pose, expected, rtol=1e-6, atol=2e-4)


@pytest.mark.parametrize("popsize,method,sigma", [(3, "uniform", 1), (100, "bad", 1),
                                                (40, "taguchi", 1), (100, "gaussian", 0),
                                                (100, "uniform", np.nan)])
def test_invalid_initialization_is_rejected(popsize, method, sigma):
    with pytest.raises(ValueError):
        sample_initial_population(popsize, 123, method, sigma)


def test_plugin_accepts_taguchi_default_and_rejects_nonorthogonal_population():
    config = GuidedSiteConfig(experiment_name="taguchi", initialization="taguchi")
    assert config.popsize == 10000
    with pytest.raises(ValueError, match="square popsize"):
        GuidedSiteConfig(experiment_name="taguchi", initialization="taguchi", popsize=40)
    with pytest.raises(ValueError):
        GuidedSiteConfig(experiment_name="bad", initialization="unregistered")
