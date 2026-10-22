"""Config overlay and output-directory guards. These tests do not start a search."""

from pathlib import Path
import json

import pytest

from config.project_config import load_project_config
from experiments.launch_site_run import apply_site_form, form_weight, prepare_output_dir, search_weights
from tests.test_site_plugin_schema import _valid_cma_config


def test_cma_es_search_uses_the_project_weight_grid() -> None:
    assert search_weights(_valid_cma_config(), "cma_es") is None
    assert search_weights(_valid_cma_config(), "guided_search") is None
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


def test_guided_search_form_keeps_data_paths_and_does_not_read_weights() -> None:
    base = load_project_config("config/default_config.json")
    config = apply_site_form(
        base,
        {
            "experiment_name": "guided-ui",
            "seed": 7,
            "rect_w_m": 60,
            "rect_h_m": 40,
            "demand_on_buildable_only": False,
            "device": "cuda",
            "popsize": 12,
            "generations": 5,
            "sigma0": 0.5,
        },
        "guided_search",
    )
    assert config.guided_search.popsize == 12
    assert config.guided_search.generations == 5
    assert config.guided_search.sigma0 == 0.5
    assert config.guided_search.include_demand is False
    assert config.guided_search.diagonal_access is False
    assert config.guided_search.initialization == "uniform"
    opened = apply_site_form(
        base,
        {
            "experiment_name": "guided-ui",
            "seed": 7,
            "rect_w_m": 60,
            "rect_h_m": 40,
            "demand_on_buildable_only": False,
            "device": "cuda",
            "popsize": 12,
            "generations": 5,
            "sigma0": 0.5,
            "diagonal_access": True,
        },
        "guided_search",
    )
    assert opened.guided_search.diagonal_access is True
    from dataclasses import replace
    research_base = replace(base, guided_search=replace(base.guided_search, initialization="gaussian"))
    missing = {"experiment_name": "init", "seed": 7, "popsize": 100, "generations": 1,
               "sigma0": 1, "rect_w_m": 60, "rect_h_m": 40,
               "device": "cuda", "demand_on_buildable_only": False}
    assert apply_site_form(research_base, missing, "guided_search").guided_search.initialization == "gaussian"
    assert apply_site_form(research_base, {**missing, "initialization": "taguchi"}, "guided_search").guided_search.initialization == "taguchi"
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


def test_failed_overwrite_preserves_the_completed_experiment(tmp_path, monkeypatch) -> None:
    from experiments.launch_site_run import launch_site_run
    from plugins.site_plugin import GuidedSiteConfig

    directory = tmp_path / "kept"
    directory.mkdir()
    before = {"run_summary.json": "{}", "resolved_config.json": '{"old":true}', "solutions.csv": "old"}
    for name, content in before.items():
        (directory / name).write_text(content, encoding="utf-8")
    monkeypatch.setattr("config.project_config.validate_cuda_device", lambda _: "cpu")

    def fail(*args):
        raise ValueError("scene unavailable")

    monkeypatch.setattr("experiments.launch_site_run.constrained_problem", fail)
    form = GuidedSiteConfig(experiment_name="kept", overwrite_existing=True).model_dump()
    with pytest.raises(ValueError, match="scene unavailable"):
        launch_site_run(form, "guided_search", lambda *args: None, output_root=tmp_path)
    assert {path.name: path.read_text(encoding="utf-8") for path in directory.iterdir()} == before
    assert list(tmp_path.iterdir()) == [directory]


@pytest.mark.parametrize("publication_fails", [False, True])
def test_overwrite_publishes_whole_directory_or_restores_it(tmp_path, monkeypatch, publication_fails) -> None:
    from experiments.launch_site_run import launch_site_run
    from plugins.site_plugin import GuidedSiteConfig

    directory = tmp_path / "kept"
    directory.mkdir()
    (directory / "run_summary.json").write_text('{"old":true}', encoding="utf-8")
    (directory / "runs.csv").write_text("old", encoding="utf-8")

    def write_run(form, algorithm, reporter, config, staged):
        assert staged != directory
        assert config.data.output_dir == directory.resolve()
        assert json.loads((directory / "run_summary.json").read_text())["old"] is True
        (staged / "run_summary.json").write_text('{"new":true}', encoding="utf-8")
        (staged / "solutions.csv").write_text("new", encoding="utf-8")

    monkeypatch.setattr("experiments.launch_site_run._run_site_search", write_run)
    original_rename = Path.rename

    def rename(source, destination):
        if publication_fails and source.name == "run":
            raise OSError("publication rejected")
        return original_rename(source, destination)

    monkeypatch.setattr(Path, "rename", rename)
    form = GuidedSiteConfig(experiment_name="kept", overwrite_existing=True).model_dump()
    if publication_fails:
        with pytest.raises(OSError, match="publication rejected"):
            launch_site_run(form, "guided_search", lambda *args: None, output_root=tmp_path)
        assert json.loads((directory / "run_summary.json").read_text()) == {"old": True}
        assert (directory / "runs.csv").read_text() == "old"
    else:
        assert launch_site_run(form, "guided_search", lambda *args: None, output_root=tmp_path) == directory
        assert json.loads((directory / "run_summary.json").read_text()) == {"new": True}
        assert (directory / "solutions.csv").read_text() == "new"
        assert not (directory / "runs.csv").exists()
    assert list(tmp_path.iterdir()) == [directory]
