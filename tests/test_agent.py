"""Assistant contract: edit operations, the tool loop, and the chat route."""

from __future__ import annotations

import re
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from agent.llm import ModelTurn, OpenAICompatModel, ToolCall
from agent.loop import ChatTurn, run_turn
from agent.tools import ToolContext, build_tools
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
            {"kind": "run_search", "plugin_id": "site.nsga2"},
        ],
    })
    validate_ops(snapshot(), list(proposal.ops))


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


def test_gateway_lists_registered_plugins() -> None:
    context = live_tool_context(snapshot(), ExperimentCatalog(ROOT / "outputs"), build_registry())
    names = [item["id"] for item in context.list_plugins()]
    assert "site.nsga2" in names


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


def test_agent_chat_requires_configuration(monkeypatch) -> None:
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


def test_agent_chat_returns_a_proposal(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BASE_URL", "http://models.example/v1")
    monkeypatch.setenv("AGENT_MODEL", "demo")
    monkeypatch.setenv("AGENT_API_KEY", "secret-key")

    def fake_run_turn(model, tools, messages, current, max_rounds):
        from agent.loop import AgentReply
        from agent.workspace import Proposal

        assert current.scene_name == "cangnan"
        assert max_rounds == 6
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
    body = response.json()
    assert body["proposal"]["ops"][0]["kind"] == "set_building"
    assert body["message"] == "建议加宽。"


class _ScriptModel:
    def __init__(self, script: list[ModelTurn]) -> None:
        self.script = list(script)
        self.seen: list[list[dict]] = []

    def complete(self, messages, tools):
        self.seen.append([dict(message) for message in messages])
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
    )
