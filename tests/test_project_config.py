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


@pytest.mark.parametrize("section", ["modeling", "common", "cma_es", "guided_search", "multistart_adam", "vae_like_multihead"])
def test_missing_or_unknown_parameters_are_rejected(tmp_path, section) -> None:
    def drop(raw):
        raw[section].pop(next(iter(raw[section])))

    def add(raw):
        raw[section]["not_a_parameter"] = 1

    for mutate in (drop, add):
        with pytest.raises(TypeError):
            load_project_config(_write(tmp_path, mutate))


def test_assistant_states_the_json_population() -> None:
    from agent.prompts import UNSUPPORTED

    assert any(f"默认种群 {load_default_config().guided_search.popsize}、" in entry for entry in UNSUPPORTED)
