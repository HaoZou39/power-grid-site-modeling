"""The project JSON is the only place that holds modeling and algorithm parameter values."""

import json

import pytest

from config.project_config import DEFAULT_CONFIG_PATH, load_default_config, load_project_config


def _write(tmp_path, mutate):
    raw = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8-sig"))
    mutate(raw)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_json_values_reach_the_config_unchanged(tmp_path) -> None:
    def mutate(raw):
        raw["guided_search"]["popsize"] = 4321

    assert load_project_config(_write(tmp_path, mutate)).guided_search.popsize == 4321


@pytest.mark.parametrize("name", ["road_dp_tolerance_m", "demand_seed", "n_demand_points", "target_resolution_m"])
def test_data_parameters_cannot_fall_back_when_json_fields_are_missing(tmp_path, name):
    with pytest.raises(TypeError):
        load_project_config(_write(tmp_path, lambda raw: raw["data"].pop(name)))


@pytest.mark.parametrize("extra", [False, True])
def test_top_level_config_fields_are_strict(tmp_path, extra):
    def mutate(raw):
        if extra:
            raw["unexpected_section"] = {}
        else:
            raw.pop("modeling")
    with pytest.raises(ValueError, match="project config fields mismatch"):
        load_project_config(_write(tmp_path, mutate))


@pytest.mark.parametrize("section", ["modeling", "common", "cma_es", "guided_search", "multistart_adam", "vae_like_multihead"])
def test_missing_or_unknown_parameters_are_rejected(tmp_path, section) -> None:
    def drop(raw):
        raw[section].pop(next(iter(raw[section])))

    def add(raw):
        raw[section]["not_a_parameter"] = 1

    for mutate in (drop, add):
        with pytest.raises(TypeError):
            load_project_config(_write(tmp_path, mutate))


@pytest.mark.parametrize("device", ["auto", "cpu", "cuda:x"])
def test_project_device_must_be_usable_by_every_plugin(tmp_path, device) -> None:
    def mutate(raw):
        raw["modeling"]["device"] = device

    with pytest.raises(ValueError, match="modeling.device"):
        load_project_config(_write(tmp_path, mutate))


def test_every_project_device_is_accepted_by_every_plugin(tmp_path) -> None:
    from plugins.site_plugin import CmaEsSiteConfig, GuidedSiteConfig, MultiStartAdamSiteConfig, PartitionedGuidedSiteConfig

    device = load_project_config(_write(tmp_path, lambda raw: raw["modeling"].update(device="cuda:1"))).modeling.device
    for model in (CmaEsSiteConfig, GuidedSiteConfig, PartitionedGuidedSiteConfig, MultiStartAdamSiteConfig):
        assert model(experiment_name="x", device=device).device == "cuda:1"
    assert GuidedSiteConfig(experiment_name="x", device="auto").device == "auto"
    with pytest.raises(ValueError, match="device"):
        CmaEsSiteConfig(experiment_name="x", device="cpu")


def test_api_imports_without_torch() -> None:
    import subprocess
    import sys

    code = "import sys; sys.modules['torch'] = None; import backend.app.main"
    subprocess.run([sys.executable, "-c", code], check=True, cwd=DEFAULT_CONFIG_PATH.parents[1])


def test_assistant_states_the_json_population() -> None:
    from agent.prompts import UNSUPPORTED

    assert any(f"默认种群 {load_default_config().guided_search.popsize}、" in entry for entry in UNSUPPORTED)
