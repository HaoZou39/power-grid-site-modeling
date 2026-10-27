from dataclasses import replace

import pytest

from agent.llm import ModelTurn
from agent.loop import ChatTurn, run_turn
from agent.tools import build_tools
from agent.workspace import RunSearch, validate_ops
from tests.test_agent import _ScriptModel, _context


def test_routing_mode_withdraws_site_tools_and_rejects_site_proposals():
    context = _context()
    snapshot = context.snapshot.model_copy(update={"problem_type": "routing"})
    tools = build_tools(replace(context, snapshot=snapshot))
    assert {tool.name for tool in tools} == {"get_workspace", "list_scenes", "list_experiments", "get_experiment", "list_plugins"}
    with pytest.raises(ValueError, match="选线模式"):
        validate_ops(snapshot, [RunSearch(kind="run_search", plugin_id="site.guided_search")])


def test_routing_agent_dry_evaluation_has_no_site_ranking_or_editing():
    context = _context()
    snapshot = context.snapshot.model_copy(update={"problem_type": "routing", "poses": [], "regions": [], "selected_pose_id": None})
    model = _ScriptModel([ModelTurn("请在选线面板指定两端；当前净空未校核。", [])])
    reply = run_turn(model, build_tools(replace(context, snapshot=snapshot)),
        [ChatTurn("user", "帮我启动选线")], snapshot, 2)
    assert reply.proposal is None and reply.recommended == []
    prompt = model.seen[0][0]["content"]
    assert "当前是选线模式" in prompt and "净空未校核" in prompt
    assert not any(item["function"]["name"] == "recommend_poses" for item in model.tools_seen[0])


def test_pilot_tensor_explanation_and_execution_limits_are_in_the_local_prompt():
    from agent.prompts import UNSUPPORTED
    text = str(UNSUPPORTED)
    assert "PILOT" in text and "tensor演化与tensor评价" in text
    assert "初始化与RRT/A*规划器仍在CPU" in text
    assert "助手目前不支持启动选线或设置接入点" in text
