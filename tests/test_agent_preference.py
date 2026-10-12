"""Preference ranking: shared normalization, objective matching, diversity, the choice route and the tool."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from agent.preference.store import PreferenceChoice, PreferenceDefaults, load_choices
from agent.preference.recommend import PreferenceConfig, recommend_poses
from agent.tools import build_tools
from agent.workspace import WorkspaceSnapshot
from backend.app.main import create_app
from tests.test_agent import _context

KEYS = ("dem_soft", "offroad_haul_m", "haul_rise_m")
SCALES = np.array([5.0, 2000.0, 50.0])  # very different units, as in a real run


def _snapshot(rows: np.ndarray, origin=None, keys=KEYS) -> WorkspaceSnapshot:
    return WorkspaceSnapshot.model_validate({
        "scene_name": "cangnan",
        "site": {"width_m": 1800, "height_m": 1800},
        "building": {"width_m": 77, "height_m": 51.5},
        "policies": {"mountain_policy": "allowed", "field_policy": "allowed", "field_cost": 0.5},
        "origin": origin,
        "regions": [],
        "poses": [
            {"id": f"pose-{i}", "x": 10.0 * i, "y": 0, "theta": 0, "objectives": dict(zip(keys, map(float, row)))}
            for i, row in enumerate(rows)
        ],
        "selected_pose_id": None,
        "experiment_id": None,
    })


def _choice(rows: np.ndarray, chosen: int, keys=KEYS) -> PreferenceChoice:
    return PreferenceChoice.model_validate({
        "scene_name": "cangnan",
        "experiment_id": None,
        "recorded_at": "2026-10-12T00:00:00+00:00",
        "chosen_id": f"c{chosen}",
        "candidates": [{"id": f"c{i}", "objectives": dict(zip(keys, map(float, row)))} for i, row in enumerate(rows)],
    })


def _front(t: np.ndarray) -> np.ndarray:
    """Trade-off rows: flatter (small t) costs more haul, so equal weights favour t = 1."""
    return np.column_stack([t, 1.0 - t, 1.0 - t]) * SCALES


def test_a_flatness_first_user_gets_the_flattest_scheme() -> None:
    rng = np.random.default_rng(0)
    history = []
    for _ in range(6):
        menu = _front(rng.uniform(size=8))
        history.append(_choice(menu, int(np.argmin(menu[:, 0]))))
    current = _front(rng.uniform(size=20))
    result = recommend_poses(_snapshot(current), history, None, PreferenceConfig(min_distance=0.0))
    assert result["basis"] == "past_choices" and result["choices_used"] == 6
    assert result["recommendations"][0]["index"] == int(np.argmin(current[:, 0])) + 1
    weights = {item["key"]: item["weight"] for item in result["weights"]}
    assert max(weights, key=weights.get) == "dem_soft"


def test_defaults_steer_the_first_recommendation() -> None:
    current = _front(np.linspace(0.0, 1.0, 9))
    flat_first = PreferenceDefaults(weights={"dem_soft": 5, "offroad_haul_m": 1, "haul_rise_m": 0})
    result = recommend_poses(_snapshot(current), [], flat_first, PreferenceConfig())
    assert result["basis"] == "defaults"
    assert result["recommendations"][0]["index"] == 1
    assert result["recommendations"][0]["strengths"][0] == "地形平整度"
    assert [item["prior"] for item in result["weights"]] == [0.833, 0.167, 0.0]
    equal = recommend_poses(_snapshot(current), [], None, PreferenceConfig())
    assert equal["basis"] == "equal_weights" and equal["recommendations"][0]["index"] == 9


def test_all_zero_defaults_is_an_error() -> None:
    zero = PreferenceDefaults(weights=dict.fromkeys(KEYS, 0))
    with pytest.raises(ValueError, match="全是 0"):
        recommend_poses(_snapshot(_front(np.linspace(0, 1, 3))), [], zero, PreferenceConfig())


def test_history_with_other_objectives_is_skipped_not_fatal() -> None:
    rng = np.random.default_rng(1)
    current = rng.uniform(size=(5, 4)) * np.append(SCALES, 900.0)
    keys = (*KEYS, "road_haul_m")
    old = _choice(rng.uniform(size=(4, 3)) * SCALES, 0)
    result = recommend_poses(_snapshot(current, origin={"x": 0, "y": 0}, keys=keys), [old], None, PreferenceConfig())
    assert result["basis"] == "equal_weights"
    assert (result["choices_used"], result["choices_skipped"]) == (0, 1)
    assert [item["key"] for item in result["weights"]] == ["dem_soft", "road_haul_m", "offroad_haul_m", "haul_rise_m"]


def test_road_haul_is_not_compared_without_an_origin() -> None:
    rows = np.array([[1.0, 10.0, 1.0, 5.0], [2.0, 20.0, 2.0, 1.0]])
    result = recommend_poses(_snapshot(rows, keys=(*KEYS, "road_haul_m")), [], None, PreferenceConfig())
    assert [item["key"] for item in result["weights"]] == list(KEYS)


def test_near_duplicates_are_skipped_before_filling() -> None:
    rows = np.array([[0.0, 0.0, 0.0], [0.001, 0.0, 0.0], [5.0, 2000.0, 50.0], [2.5, 1000.0, 25.0]])
    result = recommend_poses(_snapshot(rows), [], None, PreferenceConfig(top_k=3))
    assert [item["index"] for item in result["recommendations"]] == [1, 4, 3]


def test_fewer_than_two_measured_schemes_is_an_error() -> None:
    with pytest.raises(ValueError, match="两个"):
        recommend_poses(_snapshot(np.ones((1, 3))), [], None, PreferenceConfig())


def test_tool_is_read_only_and_reads_the_history() -> None:
    rows = np.array([[1.0, 10.0, 1.0], [2.0, 20.0, 2.0]])
    context = replace(_context(), snapshot=_snapshot(rows), preference_choices=lambda: [_choice(rows, 1)])
    tools = {tool.name: tool for tool in build_tools(context)}
    assert not {"record_preference_choice", "fit_preference_model"} & tools.keys()
    result = tools["recommend_poses"].handler({"top_k": 1})
    assert result["choices_used"] == 1 and len(result["recommendations"]) == 1


def test_choice_route_appends_and_rejects_bad_choices(monkeypatch, tmp_path) -> None:
    path = tmp_path / "PREFERENCE_CHOICES.jsonl"
    monkeypatch.setenv("AGENT_PREFERENCE_HISTORY_PATH", str(path))
    client = TestClient(create_app("sqlite://:memory:", ""))
    body = {
        "scene_name": "cangnan",
        "experiment_id": "run-1",
        "chosen_id": "pose-2",
        "candidates": [{"id": "pose-1", "objectives": {"dem_soft": 1.0}}, {"id": "pose-2", "objectives": {"dem_soft": 2.0}}],
    }
    assert client.post("/api/v1/agent/preferences/choices", json=body).json() == {"count": 1}
    [saved] = load_choices(path)
    assert saved.chosen_id == "pose-2" and saved.recorded_at

    before = path.read_text(encoding="utf-8")
    assert client.post("/api/v1/agent/preferences/choices", json={**body, "chosen_id": "pose-9"}).status_code == 422
    assert client.post("/api/v1/agent/preferences/choices", json={**body, "recorded_at": "x"}).status_code == 422
    assert path.read_text(encoding="utf-8") == before

    path.write_text(before + "not json\n", encoding="utf-8")
    broken = client.post("/api/v1/agent/preferences/choices", json=body)
    assert broken.status_code == 422 and "第 2 行" in broken.json()["detail"]["message"]


def test_defaults_routes_read_and_write(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_PREFERENCE_DEFAULTS_PATH", str(tmp_path / "PREFERENCE_DEFAULTS.json"))
    monkeypatch.setenv("AGENT_PREFERENCE_HISTORY_PATH", str(tmp_path / "PREFERENCE_CHOICES.jsonl"))
    client = TestClient(create_app("sqlite://:memory:", ""))
    assert client.get("/api/v1/agent/preferences").json() == {"defaults": None, "choice_count": 0}
    saved = client.put("/api/v1/agent/preferences/defaults", json={"weights": {"dem_soft": 4, "haul_rise_m": 0}})
    assert saved.json()["defaults"] == {"weights": {"dem_soft": 4.0, "haul_rise_m": 0.0}}
    assert client.put("/api/v1/agent/preferences/defaults", json={"weights": {"cost": 1}}).status_code == 422
    assert client.put("/api/v1/agent/preferences/defaults", json={"weights": {"dem_soft": 9}}).status_code == 422
    assert client.get("/api/v1/agent/preferences").json()["defaults"]["weights"]["dem_soft"] == 4.0


def test_prompt_says_the_assistant_cannot_record_choices() -> None:
    from agent.prompts import system_prompt

    assert "recommend_poses" in system_prompt() and "记为我的选择" in system_prompt()
