"""Attached-pose analysis: footprint terrain, ranking, the analyze_pose tool and the attachment note."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from agent.analysis import rank_pose
from agent.llm import ModelTurn
from agent.loop import ChatTurn, run_turn
from agent.tools import build_tools
from agent.workspace import WorkspaceSnapshot
from backend.app.main import create_app
from modeling.footprint_terrain import footprint_terrain
from tests.test_agent import _context, _ScriptModel


def three_poses(origin=None) -> WorkspaceSnapshot:
    return WorkspaceSnapshot.model_validate({
        "scene_name": "cangnan",
        "site": {"width_m": 1800, "height_m": 1800},
        "building": {"width_m": 77, "height_m": 51.5},
        "policies": {"mountain_policy": "allowed", "field_policy": "allowed", "field_cost": 0.5},
        "origin": origin,
        "regions": [],
        "poses": [
            {"id": "pose-1", "x": 100, "y": 100, "theta": 0, "objectives": {"dem_soft": 1.0, "demand_distance": 300, "road_haul_m": 50}},
            {"id": "pose-2", "x": 200, "y": 100, "theta": 0, "objectives": {"dem_soft": 3.0, "demand_distance": 100, "road_haul_m": 10}},
            {"id": "pose-3", "x": 300, "y": 100, "theta": 0, "objectives": {"dem_soft": 1.0, "demand_distance": 200}},
        ],
        "selected_pose_id": "pose-1",
        "experiment_id": None,
    })


def test_footprint_terrain_counts_landuse_and_relief() -> None:
    dem = np.tile(np.arange(20, dtype=np.float64), (20, 1))
    landuse = np.zeros((20, 20), dtype=np.int64)
    landuse[:, :10] = 1
    report = footprint_terrain(dem, landuse, (10.0, 10.0, 0.0), 6.0, 4.0)
    shares = report["landuse_share"]
    assert report["cells"] > 0
    assert sum(shares.values()) == pytest.approx(1.0)
    assert 0 < shares["field"] < 1 and shares["field"] + shares["other"] == pytest.approx(1.0)
    assert report["elevation_range_m"] == report["elevation_max_m"] - report["elevation_min_m"] > 0
    assert report["max_slope_deg"] == pytest.approx(45.0, abs=1.0)


def test_footprint_terrain_rejects_mismatched_grids() -> None:
    with pytest.raises(ValueError, match="share a shape"):
        footprint_terrain(np.zeros((5, 5)), np.zeros((4, 5), dtype=np.int64), (2.0, 2.0, 0.0), 2.0, 2.0)


def test_rank_pose_shares_ties_and_skips_road_haul_without_origin() -> None:
    result = rank_pose(three_poses(), "pose-3")
    ranks = {item["key"]: item for item in result["ranks"]}
    assert result["pose"]["index"] == 3
    assert "road_haul_m" not in ranks
    assert ranks["dem_soft"]["rank"] == 1 and ranks["dem_soft"]["of"] == 3
    assert ranks["demand_distance"] == {
        "key": "demand_distance",
        "label": "需求点距离（m）",
        "value": 200,
        "rank": 2,
        "of": 3,
        "best_value": 100,
        "best_pose_id": "pose-2",
        "best_index": 2,
    }
    assert result["strengths"] == ["dem_soft"]
    assert result["weaknesses"] == []


def test_rank_pose_with_origin_ranks_road_haul() -> None:
    result = rank_pose(three_poses(origin={"x": 1, "y": 1}), "pose-1")
    ranks = {item["key"]: item for item in result["ranks"]}
    assert ranks["road_haul_m"]["rank"] == 2 and ranks["road_haul_m"]["of"] == 2
    assert "road_haul_m" in result["weaknesses"] and "demand_distance" in result["weaknesses"]


def test_rank_pose_rejects_an_unknown_pose() -> None:
    with pytest.raises(ValueError, match="pose-9"):
        rank_pose(three_poses(), "pose-9")


def test_analyze_pose_keeps_ranks_when_the_site_report_fails() -> None:
    def not_buildable(x, y, theta):
        raise ValueError("site cell is not buildable")

    context = replace(_context(), snapshot=three_poses(), evaluate_pose=not_buildable)
    tool = next(tool for tool in build_tools(context) if tool.name == "analyze_pose")
    result = tool.handler({"pose_id": "pose-2"})
    assert result["pose"]["id"] == "pose-2"
    assert result["footprint"] == {"cells": 1}
    assert result["site_report"] == {"error": "site cell is not buildable"}


def test_run_turn_notes_the_attached_pose() -> None:
    model = _ScriptModel([ModelTurn("看过了。", [])])
    run_turn(model, build_tools(replace(_context(), snapshot=three_poses())), [ChatTurn("user", "分析一下", "pose-2")], three_poses(), 2)
    assert model.seen[0][-1]["content"] == "分析一下\n（本句附上方案 pose-2，即 poses 第 2 个）"


def test_agent_chat_rejects_an_unknown_attached_pose() -> None:
    client = TestClient(create_app("sqlite://:memory:", ""))
    response = client.post("/api/v1/agent/chat", json={
        "messages": [{"role": "user", "content": "分析一下", "pose_id": "pose-9"}],
        "snapshot": three_poses().model_dump(mode="json"),
    })
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "attached_pose_unknown"


def test_analysis_rule_is_in_the_prompt() -> None:
    from agent.prompts import system_prompt

    assert "先调用 analyze_pose" in system_prompt()
