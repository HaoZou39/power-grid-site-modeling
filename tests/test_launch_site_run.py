"""Config overlay and output-directory guards. These tests do not start a search."""

from pathlib import Path

import pytest

from config.project_config import load_project_config
from experiments.launch_site_run import apply_site_form, form_weight, prepare_output_dir, search_weights
from tests.test_site_plugin_schema import _valid_cma_config


def test_cma_es_search_uses_the_project_weight_grid() -> None:
    assert search_weights(_valid_cma_config(), "cma_es") is None
    assert search_weights(_valid_cma_config(), "nsga2") is None
    adam = search_weights(_valid_cma_config(), "multistart_adam")
    assert adam is not None
    assert adam[0].tolist() == [0.2, 0.3, 0.5]
    weight = form_weight(_valid_cma_config()["objective_weights"])
    assert weight.tolist() == [0.2, 0.3, 0.5]


def test_apply_site_form_overrides_rectangle_and_keeps_data_paths() -> None:
    base = load_project_config("config/default_config.json")
    config = apply_site_form(base, _valid_cma_config(), "cma_es")
    assert config.modeling.rect_w_m == 80
    assert config.modeling.rect_h_m == 50
    assert config.cma_es.popsize == 8
    assert config.cma_es.max_iters == 40
    assert config.experiment_name == "cmaes-ui"
    assert config.data.dem_path == base.data.dem_path
    assert config.common.weight_grid_step == base.common.weight_grid_step


def test_nsga2_form_keeps_data_paths_and_does_not_read_weights() -> None:
    base = load_project_config("config/default_config.json")
    config = apply_site_form(
        base,
        {
            "experiment_name": "nsga-ui",
            "seed": 7,
            "rect_w_m": 60,
            "rect_h_m": 40,
            "demand_on_buildable_only": False,
            "device": "cuda",
            "popsize": 12,
            "generations": 5,
            "sigma0": 0.5,
        },
        "nsga2",
    )
    assert config.nsga2.popsize == 12
    assert config.nsga2.generations == 5
    assert config.nsga2.sigma0 == 0.5
    assert config.modeling.rect_w_m == 60
    assert config.data.dem_path == base.data.dem_path


def test_prepare_output_dir_rejects_path_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        prepare_output_dir(tmp_path, "../outside", False)


def test_prepare_output_dir_refuses_to_replace_a_finished_experiment(tmp_path: Path) -> None:
    directory = tmp_path / "kept"
    directory.mkdir()
    (directory / "run_summary.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        prepare_output_dir(tmp_path, "kept", False)
    assert prepare_output_dir(tmp_path, "kept", True) == directory.resolve()
