"""Assistant contract: edit operations, the tool loop, and the chat route."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from agent.llm import ModelTurn, OpenAICompatModel, ToolCall
from agent.loop import ChatTurn, run_turn
from agent.tools import AgentTool, ToolContext, build_tools
from agent.workspace import WorkspaceSnapshot, edit_op_kinds, validate_ops
from backend.app.application.agent_gateway import live_tool_context
from backend.app.application.registry import build_registry
from backend.app.infrastructure.experiment_catalog import ExperimentCatalog
from backend.app.main import create_app


ROOT = Path(__file__).resolve().parents[1]


def snapshot() -> WorkspaceSnapshot:
    return WorkspaceSnapshot.model_validate({
        "scene_name": "cangnan",
        "site": {"width_m": 1800, "height_m": 1800},
        "building": {"width_m": 77, "height_m": 51.5},
        "policies": {"mountain_policy": "allowed", "field_policy": "allowed", "field_cost": 0.5},
        "origin": None,
        "regions": [{"id": "zone-1", "kind": "exclusion", "ring": [{"x": 1, "y": 1}, {"x": 4, "y": 1}, {"x": 2, "y": 4}]}],
        "poses": [{"id": "pose-1", "x": 10, "y": 20, "theta": 0, "objectives": {"dem_soft": 1.5}}],
        "selected_pose_id": "pose-1",
        "experiment_id": None,
        "layers": {
            "panel_open": False,
            "scene_ready": True,
            "dem": {"visible": False, "opacity": 0.6, "available": True},
            "landuse": {
                "field": {"visible": True, "available": True},
                "building": {"visible": True, "available": True},
                "road": {"visible": True, "available": True},
                "water": {"visible": True, "available": True},
            },
            "osm_roads": {"visible": False, "available": True},
            "regions": {"exclusion": True, "feasible": True},
        },
    })


def test_edit_op_kinds_match_the_frontend() -> None:
    text = (ROOT / "frontend/src/agent/edit_ops.ts").read_text(encoding="utf-8")
    block = re.search(r"export const EDIT_OP_KINDS = \[(.*?)] as const", text, re.S)
    assert block is not None
    found = re.findall(r'"([a-z_]+)"', block.group(1))
    assert found == edit_op_kinds()


def test_validate_ops_accepts_an_ordered_proposal() -> None:
    from agent.workspace import Proposal

    proposal = Proposal.model_validate({
        "rationale": "把建筑加大，并去掉这块禁区。",
        "ops": [
            {"kind": "set_building", "width_m": 80, "height_m": 50},
            {"kind": "remove_region", "region_id": "zone-1"},
            {"kind": "clear_origin"},
            {"kind": "run_search", "plugin_id": "site.guided_search"},
        ],
    })
    validate_ops(snapshot(), list(proposal.ops))


def test_validate_ops_accepts_layer_visibility_opacity_and_mixed_changes() -> None:
    from agent.workspace import Proposal

    proposal = Proposal.model_validate({
        "rationale": "改长度并显示高程。",
        "ops": [
            {"kind": "set_building", "width_m": 80, "height_m": 51.5},
            {"kind": "set_layer_visibility", "layer": "dem", "visible": True},
            {"kind": "set_dem_opacity", "opacity": 0.4},
            {"kind": "set_layer_visibility", "layer": "exclusion", "visible": False},
        ],
    })
    validate_ops(snapshot(), list(proposal.ops))


def test_validate_ops_accepts_layer_panel_open_and_close() -> None:
    from agent.workspace import Proposal

    for open_panel in (True, False):
        proposal = Proposal.model_validate({
            "rationale": "调整图层面板。",
            "ops": [{"kind": "set_layer_panel_open", "open": open_panel}],
        })
        validate_ops(snapshot(), list(proposal.ops))

    mixed = Proposal.model_validate({
        "rationale": "打开面板并显示高程。",
        "ops": [
            {"kind": "set_layer_panel_open", "open": True},
            {"kind": "set_layer_visibility", "layer": "dem", "visible": True},
        ],
    })
    validate_ops(snapshot(), list(mixed.ops))


def test_validate_ops_rejects_enabling_an_unavailable_layer() -> None:
    import pytest

    from agent.workspace import Proposal

    current = snapshot().model_copy(deep=True)
    current.layers.dem.available = False
    proposal = Proposal.model_validate({
        "rationale": "显示高程。",
        "ops": [{"kind": "set_layer_visibility", "layer": "dem", "visible": True}],
    })
    with pytest.raises(ValueError, match="没有可用"):
        validate_ops(current, list(proposal.ops))

    hidden = Proposal.model_validate({
        "rationale": "隐藏高程。",
        "ops": [{"kind": "set_layer_visibility", "layer": "dem", "visible": False}],
    })
    validate_ops(current, list(hidden.ops))


def test_snapshot_layer_defaults_keep_old_callers_compatible() -> None:
    data = snapshot().model_dump(exclude={"layers"})
    layers = WorkspaceSnapshot.model_validate(data).layers
    assert layers.scene_ready is False
    assert layers.dem.opacity == 0.6
    assert layers.regions.exclusion is True


def test_validate_ops_rejects_a_point_outside_the_site() -> None:
    from agent.workspace import Proposal

    proposal = Proposal.model_validate({
        "rationale": "把原点放到场地外。",
        "ops": [{"kind": "set_origin", "x": -1, "y": 2}],
    })
    try:
        validate_ops(snapshot(), list(proposal.ops))
    except ValueError as exc:
        assert "选址范围" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_refine_pose_needs_a_known_pose_alone_and_a_bounded_square() -> None:
    import pytest
    from pydantic import ValidationError

    from agent.workspace import Proposal

    def check(ops: list[dict]) -> None:
        validate_ops(snapshot(), list(Proposal.model_validate({"rationale": "局部优化", "ops": ops}).ops))

    check([{"kind": "refine_pose", "pose_id": "pose-1"}])
    for ops, message in (
        ([{"kind": "refine_pose", "pose_id": "pose-9"}], "没有这个方案"),
        ([{"kind": "refine_pose", "pose_id": "pose-1"}] * 2, "一个方案"),
        ([{"kind": "refine_pose", "pose_id": "pose-1"}, {"kind": "run_search", "plugin_id": "site.guided_search"}], "同一个提案"),
    ):
        with pytest.raises(ValueError, match=message):
            check(ops)
    with pytest.raises(ValidationError):
        check([{"kind": "refine_pose", "pose_id": "pose-1", "half_width_m": 10}])


def test_refine_bounds_match_the_frontend() -> None:
    from agent.workspace import RefinePose

    text = (ROOT / "frontend/src/agent/edit_ops.ts").read_text(encoding="utf-8")
    found = re.search(r"REFINE_HALF_WIDTH_M = \{ min: (\d+), max: (\d+), default: (\d+) \}", text)
    assert found is not None
    field = RefinePose.model_fields["half_width_m"]
    bounds = {type(item).__name__: item for item in field.metadata}
    assert [float(value) for value in found.groups()] == [bounds["Ge"].ge, bounds["Le"].le, field.default]


def test_clear_poses_is_standalone_and_needs_current_solutions() -> None:
    import pytest
    from pydantic import ValidationError

    from agent.workspace import Proposal

    proposal = Proposal.model_validate({"rationale": "清空当前方案。", "ops": [{"kind": "clear_poses"}]})
    validate_ops(snapshot(), list(proposal.ops))

    mixed = Proposal.model_validate({
        "rationale": "清空后搜索。",
        "ops": [{"kind": "clear_poses"}, {"kind": "run_search", "plugin_id": "site.guided_search"}],
    })
    with pytest.raises(ValueError, match="唯一"):
        validate_ops(snapshot(), list(mixed.ops))

    empty = snapshot().model_copy(update={"poses": [], "selected_pose_id": None})
    with pytest.raises(ValueError, match="没有方案"):
        validate_ops(empty, list(proposal.ops))

    with pytest.raises(ValidationError, match="记忆"):
        Proposal.model_validate({
            "rationale": "清空并记住。",
            "ops": [{"kind": "clear_poses"}],
            "memory": [{"kind": "remember", "section": "preference", "scene": None, "source": "stated", "text": "清空方案"}],
        })


def test_snapshot_keeps_feasibility_and_provenance() -> None:
    data = snapshot().model_dump()
    data["poses"].append({"id": "r/0", "x": 12, "y": 22, "theta": 0, "feasible": False, "derived_from": "pose-1"})
    pose = WorkspaceSnapshot.model_validate(data).poses[1]
    assert (pose.feasible, pose.derived_from) == (False, "pose-1")


def test_run_turn_reads_the_workspace() -> None:
    model = _ScriptModel([
        ModelTurn("", [ToolCall("1", "get_workspace", {})]),
        ModelTurn("当前建筑宽 77 m。", []),
    ])
    reply = run_turn(model, build_tools(_context()), [ChatTurn("user", "建筑多大")], snapshot(), 4)
    assert reply.proposal is None
    assert reply.message == "当前建筑宽 77 m。"
    assert reply.tool_trace[0].name == "get_workspace"
    assert reply.tool_trace[0].ok is True
    assert "77" in model.seen[1][-1]["content"]


def test_run_turn_returns_recommended_ids_in_rank_order() -> None:
    ranked = {"recommendations": [{"rank": 1, "pose_id": "pose-2"}, {"rank": 2, "pose_id": "pose-1"}]}
    tool = AgentTool("recommend_poses", "", {"type": "object"}, lambda args: ranked)
    model = _ScriptModel([
        ModelTurn("", [ToolCall("1", "recommend_poses", {})]),
        ModelTurn("推荐方案 2。", []),
    ])
    reply = run_turn(model, [tool], [ChatTurn("user", "推荐几个")], snapshot(), 4)
    assert reply.recommended == ["pose-2", "pose-1"]


def test_run_turn_retries_an_invalid_proposal_once() -> None:
    bad = {"rationale": "改大", "ops": [{"kind": "set_building", "width_m": -1, "height_m": 10}]}
    good = {"rationale": "改成 80×50", "ops": [{"kind": "set_building", "width_m": 80, "height_m": 50}]}
    model = _ScriptModel([
        ModelTurn("", [ToolCall("1", "propose_changes", bad)]),
        ModelTurn("", [ToolCall("2", "propose_changes", good)]),
    ])
    reply = run_turn(model, build_tools(_context()), [ChatTurn("user", "加大建筑")], snapshot(), 4)
    assert reply.proposal is not None
    assert reply.proposal.rationale == "改成 80×50"
    assert [item.ok for item in reply.tool_trace] == [False, True]
    assert "大于 0" in model.seen[1][-1]["content"]


def test_run_turn_stops_after_a_second_invalid_proposal() -> None:
    bad = {"rationale": "改大", "ops": [{"kind": "set_building", "width_m": -1, "height_m": 10}]}
    model = _ScriptModel([
        ModelTurn("", [ToolCall("1", "propose_changes", bad)]),
        ModelTurn("还是不行", [ToolCall("2", "propose_changes", bad)]),
    ])
    reply = run_turn(model, build_tools(_context()), [ChatTurn("user", "加大建筑")], snapshot(), 4)
    assert reply.proposal is None
    assert "大于 0" in reply.message


def test_every_edit_op_has_an_instruction_card() -> None:
    from agent.prompts import OP_GUIDES, system_prompt

    assert list(OP_GUIDES) == edit_op_kinds()
    prompt = system_prompt()
    for kind in edit_op_kinds():
        assert f"- {kind}：" in prompt


def test_clear_poses_eval_phrases_and_single_delete_boundary() -> None:
    cases = json.loads((ROOT / "experiments/agent_eval_cases.json").read_text(encoding="utf-8"))["cases"]
    by_ask = {case["ask"]: case for case in cases}
    for ask in (
        "清空当前所有方案",
        "把地图上的站址全部清掉",
        "清除刚才优化得到的方案",
        "我想重新选址，先把当前方案清空",
        "删除当前加载的全部候选方案，但保留历史记录",
    ):
        assert by_ask[ask]["expect"] == [{"kind": "clear_poses"}]
    assert by_ask["只删除方案 2，其他方案保留"]["unsupported"] is True


def test_run_turn_withdraws_a_tool_that_keeps_failing() -> None:
    from dataclasses import replace

    def not_buildable(x, y, theta):
        raise ValueError("site cell is not buildable")

    good = {"rationale": "往东挪", "ops": [{"kind": "update_pose", "pose_id": "pose-1", "x": 60}]}
    model = _ScriptModel([
        ModelTurn("", [ToolCall("1", "evaluate_pose", {"x": 60, "y": 20, "theta": 0})]),
        ModelTurn("", [ToolCall("2", "evaluate_pose", {"x": 61, "y": 20, "theta": 0})]),
        ModelTurn("", [ToolCall("3", "propose_changes", good)]),
    ])
    tools = build_tools(replace(_context(), evaluate_pose=not_buildable))
    reply = run_turn(model, tools, [ChatTurn("user", "往东挪 50 米")], snapshot(), 6)
    assert reply.proposal is not None
    assert "evaluate_pose" in [tool["function"]["name"] for tool in model.tools_seen[1]]
    assert "evaluate_pose" not in [tool["function"]["name"] for tool in model.tools_seen[2]]
    assert model.seen[2][-1]["role"] == "system"
    assert "evaluate_pose" in model.seen[2][-1]["content"]


def test_eval_scoring_rules() -> None:
    from experiments.agent_eval import score_ops

    def proposal(*ops):
        return {"rationale": "", "ops": list(ops)}

    move = {"kind": "update_pose", "pose_id": "pose-1", "x": 950.004, "y": None, "theta": None}
    assert score_ops([{"kind": "update_pose", "pose_id": "pose-1", "x": 950}], proposal(move)) == (True, "ok")
    assert score_ops([{"kind": "update_pose", "pose_id": "pose-1", "x": 950}], proposal({**move, "y": 900}))[0] is False
    assert score_ops([{"kind": "run_search", "plugin_id": "site.guided_search"}], None) == (False, "没有提案")
    assert score_ops(None, None) == (True, "ok")
    assert score_ops(None, proposal(move))[0] is False
    square = [{"x": 0, "y": 0}, {"x": 400, "y": 0}, {"x": 400, "y": 400}, {"x": 0, "y": 400}]
    turned = {"kind": "add_region", "region_kind": "feasible", "ring": square[2:] + square[:2]}
    assert score_ops([{"kind": "add_region", "region_kind": "feasible", "ring": square}], proposal(turned))[0] is True
    assert score_ops([{"kind": "set_origin", "x": 1, "y": 2}], proposal({"kind": "clear_origin"}))[0] is False


def test_eval_requires_saying_unsupported() -> None:
    from experiments.agent_eval import score_case

    refuse = {"expect": None, "unsupported": True}
    assert score_case(refuse, None, "目前不支持改种群，只能用默认值。") == (True, "ok")
    assert score_case(refuse, None, "这个做不到。")[0] is False
    mixed = {"expect": [{"kind": "clear_origin"}], "unsupported": True}
    with_note = {"rationale": "去掉原点；种群目前不支持修改。", "ops": [{"kind": "clear_origin"}]}
    assert score_case(mixed, with_note, "")[0] is True
    assert score_case(mixed, {**with_note, "rationale": "去掉原点"}, "")[0] is False
    analyze = {"expect": None, "expect_tools": ["analyze_pose"]}
    assert score_case(analyze, None, "", frozenset({"analyze_pose"})) == (True, "ok")
    assert score_case(analyze, None, "")[0] is False


def test_system_prompt_lists_known_gaps() -> None:
    from agent.prompts import UNSUPPORTED, system_prompt

    prompt = system_prompt()
    assert all(item in prompt for item in UNSUPPORTED)


def test_system_prompt_keeps_scheme_data_grounded_and_precise() -> None:
    from agent.prompts import system_prompt

    prompt = system_prompt()
    assert "当前工作区快照或本轮工具结果" in prompt
    assert "详细报告口径" in prompt and "优化目标口径" in prompt
    assert "小数点后三位" in prompt and "28.357 仍写 28.357" in prompt
    assert "`rank` 是综合推荐名次" in prompt and "`index` 是地图上的方案编号" in prompt
    assert "综合第 1 名只表示综合排序最靠前" in prompt


def test_gateway_lists_registered_plugins() -> None:
    context = live_tool_context(snapshot(), ExperimentCatalog(ROOT / "outputs"), build_registry())
    names = [item["id"] for item in context.list_plugins()]
    assert "site.guided_search" in names


def test_openai_adapter_sends_the_key_only_as_a_header() -> None:
    from agent.config import AgentConfig

    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "好"}}]})

    config = AgentConfig(base_url="http://models.example/v1", model="demo", api_key="secret-key", timeout_s=5)
    turn = OpenAICompatModel(config, transport=httpx.MockTransport(handler)).complete(
        [{"role": "user", "content": "你好"}],
        [],
    )
    assert turn.content == "好"
    assert seen["auth"] == "Bearer secret-key"
    assert "secret-key" not in seen["url"]
    assert seen["url"].endswith("/v1/chat/completions")


def test_agent_chat_requires_configuration(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_SETTINGS_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_ENV_FILE", str(tmp_path / ".env"))
    for name in ("AGENT_BASE_URL", "AGENT_MODEL", "AGENT_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    client = TestClient(create_app("sqlite://:memory:", ""))
    response = client.post("/api/v1/agent/chat", json={
        "messages": [{"role": "user", "content": "你好"}],
        "snapshot": snapshot().model_dump(mode="json"),
    })
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "agent_not_configured"


def test_agent_ops_schema_lists_every_kind() -> None:
    client = TestClient(create_app("sqlite://:memory:", ""))
    response = client.get("/api/v1/agent/ops")
    assert response.status_code == 200
    text = response.text
    for kind in edit_op_kinds():
        assert kind in text


def test_sse_content_streams_without_the_reasoning() -> None:
    from agent.llm import ModelTurn, iter_sse

    lines = [
        'data: {"choices":[{"delta":{"reasoning":"先想"}}]}',
        'data: {"choices":[{"delta":{"content":"往"}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"propose_changes","arguments":""}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"rationale\\":\\"挪\\",\\"ops\\":[]}"}}]}}]}',
        "data: [DONE]",
    ]
    items = list(iter_sse(lines))
    assert items[0] == "往"
    assert isinstance(items[-1], ModelTurn)
    assert items[-1].content == "往"
    assert items[-1].tool_calls[0].name == "propose_changes"
    assert items[-1].tool_calls[0].arguments["rationale"] == "挪"


def test_run_turn_forwards_streamed_text() -> None:
    from agent.llm import ModelTurn

    class _StreamModel:
        def iter_turn(self, messages, tools):
            yield "往"
            yield "东"
            yield ModelTurn("往东", [])

    seen: list[str] = []
    reply = run_turn(_StreamModel(), build_tools(_context()), [ChatTurn("user", "挪")], snapshot(), 2, on_delta=seen.append)
    assert seen == ["往", "东"]
    assert reply.message == "往东"


def test_agent_chat_returns_a_proposal(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_SETTINGS_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_BASE_URL", "http://models.example/v1")
    monkeypatch.setenv("AGENT_MODEL", "demo")
    monkeypatch.setenv("AGENT_API_KEY", "secret-key")
    monkeypatch.setenv("AGENT_MEMORY_PATH", str(tmp_path / "MEMORY.md"))

    def fake_run_turn(
        model, tools, messages, current, max_rounds, on_delta=None, memory=None, memory_enabled=True,
    ):
        assert memory == []
        assert memory_enabled is True
        from agent.loop import AgentReply
        from agent.workspace import Proposal

        assert current.scene_name == "cangnan"
        assert max_rounds == 6
        if on_delta:
            on_delta("建议")
            on_delta("加宽。")
        return AgentReply(
            message="建议加宽。",
            proposal=Proposal.model_validate({
                "rationale": "建议加宽。",
                "ops": [{"kind": "set_building", "width_m": 80, "height_m": 50}],
            }),
            tool_trace=[],
        )

    monkeypatch.setattr("backend.app.api.agent_routes.run_turn", fake_run_turn)
    client = TestClient(create_app("sqlite://:memory:", ""))
    response = client.post("/api/v1/agent/chat", json={
        "messages": [{"role": "user", "content": "加大建筑"}],
        "snapshot": snapshot().model_dump(mode="json"),
    })
    assert response.status_code == 200
    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert [line["text"] for line in lines if line["type"] == "delta"] == ["建议", "加宽。"]
    body = lines[-1]["reply"]
    assert lines[-1]["type"] == "done"
    assert body["proposal"]["ops"][0]["kind"] == "set_building"
    assert body["message"] == "建议加宽。"


class _ScriptModel:
    def __init__(self, script: list[ModelTurn]) -> None:
        self.script = list(script)
        self.seen: list[list[dict]] = []
        self.tools_seen: list[list[dict]] = []

    def complete(self, messages, tools):
        self.seen.append([dict(message) for message in messages])
        self.tools_seen.append(list(tools))
        if not self.script:
            raise AssertionError("script exhausted")
        return self.script.pop(0)


def _context() -> ToolContext:
    current = snapshot()
    return ToolContext(
        snapshot=current,
        list_scenes=lambda: [],
        list_experiments=lambda: [],
        get_experiment=lambda experiment_id: {"id": experiment_id},
        list_plugins=lambda: [],
        evaluate_pose=lambda x, y, theta: {"x": x, "y": y, "theta": theta},
        footprint_terrain=lambda x, y, theta: {"cells": 1},
        preference_choices=lambda: [],
        preference_defaults=lambda: None,
    )
