"""One assistant turn. A valid propose_changes ends the turn; a bad one is retried once.

A read-only tool that fails in two rounds in a row is withdrawn for the rest of the turn.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from agent.llm import ChatModel, ModelTurn, ToolCall
from agent.memory import MemoryEntry, select_for_prompt
from agent.prompts import system_prompt
from agent.tools import AgentTool, tool_specs
from agent.workspace import Proposal, WorkspaceSnapshot


class ToolTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    ok: bool


class AgentReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    proposal: Proposal | None
    tool_trace: list[ToolTrace]
    # Pose ids from the turn's last recommend_poses, best first. The map colors them by rank.
    recommended: list[str] = []


@dataclass(frozen=True)
class ChatTurn:
    role: str
    content: str
    pose_id: str | None = None


def _turn_text(message: ChatTurn, snapshot: WorkspaceSnapshot) -> str:
    if message.pose_id is None:
        return message.content
    index = next(i for i, pose in enumerate(snapshot.poses) if pose.id == message.pose_id)
    return f"{message.content}\n（本句附上方案 {index + 1}，pose_id 为 {message.pose_id}）"


def run_turn(
    model: ChatModel,
    tools: list[AgentTool],
    messages: list[ChatTurn],
    snapshot: WorkspaceSnapshot,
    max_rounds: int,
    on_delta: Callable[[str], None] | None = None,
    memory: list[MemoryEntry] | None = None,
    memory_enabled: bool = True,
) -> AgentReply:
    if not memory_enabled and _pure_memory_request(messages):
        return AgentReply(
            message="长期记忆未开启，无法保存这条信息。你可以在「设置 → AI 助手设置」中开启。",
            proposal=None,
            tool_trace=[],
        )
    by_name = {tool.name: tool for tool in tools}
    selected_memory = select_for_prompt(memory or [], snapshot.scene_name) if memory_enabled else []
    prompt = system_prompt(selected_memory, memory_enabled=memory_enabled)
    transcript: list[dict[str, Any]] = [
        {"role": "system", "content": prompt + "\n\n当前工作区：\n" + snapshot.model_dump_json()},
        *[{"role": message.role, "content": _turn_text(message, snapshot)} for message in messages],
    ]
    trace: list[ToolTrace] = []
    proposal_failures = 0
    failed_last_round: set[str] = set()
    withdrawn: set[str] = set()
    recommended: list[str] = []
    for _ in range(max_rounds):
        turn = _next_turn(model, transcript, tool_specs([tool for tool in tools if tool.name not in withdrawn]), on_delta)
        transcript.append(_assistant_message(turn))
        if not turn.tool_calls:
            return AgentReply(message=turn.content or "没有新的建议。", proposal=None, tool_trace=trace, recommended=recommended)
        start = len(trace)
        available = {name: tool for name, tool in by_name.items() if name not in withdrawn}
        proposal, failure = _run_tools(turn.tool_calls, available, transcript, trace, recommended)
        if proposal is not None:
            return AgentReply(message=turn.content.strip() or proposal.rationale, proposal=proposal, tool_trace=trace, recommended=recommended)
        if failure is not None:
            proposal_failures += 1
            if proposal_failures > 1:
                detail = str(failure)
                text = turn.content.strip()
                return AgentReply(message=f"{text}\n{detail}".strip(), proposal=None, tool_trace=trace, recommended=recommended)
        failed = {item.name for item in trace[start:] if not item.ok and item.name in by_name}
        repeated = (failed & failed_last_round) - {"propose_changes"} - withdrawn
        if repeated:
            withdrawn |= repeated
            names = "、".join(sorted(repeated))
            transcript.append({
                "role": "system",
                "content": f"{names} 已连续出错，本轮不再提供。请直接用 propose_changes 提案，或说明做不到。",
            })
        failed_last_round = failed
    return AgentReply(message="工具调用次数已用完，请把要求再说具体一点。", proposal=None, tool_trace=trace, recommended=recommended)


def _pure_memory_request(messages: list[ChatTurn]) -> bool:
    latest = next((message.content for message in reversed(messages) if message.role == "user"), "")
    memory_intent = any(word in latest for word in ("记住", "以后都", "忘掉", "整理记忆", "长期记忆"))
    edit_intent = any(word in latest for word in (
        "移动", "挪", "旋转", "调整方案", "优化", "重跑", "建筑", "变电站", "进货原点",
        "禁区", "可行域", "图层", "透明度", "选择方案", "打开", "关闭面板",
    ))
    return memory_intent and not edit_intent


def _next_turn(model: ChatModel, transcript: list[dict[str, Any]], specs: list[dict[str, Any]], on_delta: Callable[[str], None] | None) -> ModelTurn:
    iterate = getattr(model, "iter_turn", None)
    if iterate is None:
        return model.complete(transcript, specs)
    found = None
    for item in iterate(transcript, specs):
        if isinstance(item, str):
            if on_delta and item:
                on_delta(item)
        else:
            found = item
    if found is None:
        raise RuntimeError("模型接口没有返回结果")
    return found


def _run_tools(
    calls: list[ToolCall],
    by_name: dict[str, AgentTool],
    transcript: list[dict[str, Any]],
    trace: list[ToolTrace],
    recommended: list[str],
) -> tuple[Proposal | None, Exception | None]:
    proposal = None
    failure = None
    for call in calls:
        tool = by_name.get(call.name)
        if tool is None:
            trace.append(ToolTrace(name=call.name, ok=False))
            _tool_result(transcript, call.id, {"error": f"没有这个工具：{call.name}"})
            continue
        try:
            result = tool.handler(call.arguments)
        except Exception as exc:
            trace.append(ToolTrace(name=call.name, ok=False))
            _tool_result(transcript, call.id, {"error": str(exc)})
            if call.name == "propose_changes":
                failure = exc
            continue
        trace.append(ToolTrace(name=call.name, ok=True))
        _tool_result(transcript, call.id, result)
        if call.name == "propose_changes":
            proposal = Proposal.model_validate(result)
        if call.name == "recommend_poses":
            recommended[:] = [item["pose_id"] for item in result["recommendations"]]
    return proposal, failure


def _tool_result(transcript: list[dict[str, Any]], call_id: str, payload: Any) -> None:
    transcript.append({
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(_jsonable(payload), ensure_ascii=False),
    })


def _jsonable(value: Any) -> Any:
    """Tool results cross the model API as JSON. Numpy scalars become Python numbers."""

    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    raise TypeError(f"工具结果无法写成 JSON：{type(value).__name__}")


def _assistant_message(turn: ModelTurn) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": turn.content or None}
    if turn.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in turn.tool_calls
        ]
    return message
