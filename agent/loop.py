"""One assistant turn. A valid propose_changes ends the turn; a bad one is retried once."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from agent.llm import ChatModel, ModelTurn, ToolCall
from agent.prompts import SYSTEM_PROMPT
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


@dataclass(frozen=True)
class ChatTurn:
    role: str
    content: str


def run_turn(
    model: ChatModel,
    tools: list[AgentTool],
    messages: list[ChatTurn],
    snapshot: WorkspaceSnapshot,
    max_rounds: int,
) -> AgentReply:
    by_name = {tool.name: tool for tool in tools}
    transcript: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\n当前工作区：\n" + snapshot.model_dump_json()},
        *[{"role": message.role, "content": message.content} for message in messages],
    ]
    specs = tool_specs(tools)
    trace: list[ToolTrace] = []
    proposal_failures = 0
    for _ in range(max_rounds):
        turn = model.complete(transcript, specs)
        transcript.append(_assistant_message(turn))
        if not turn.tool_calls:
            return AgentReply(message=turn.content or "没有新的建议。", proposal=None, tool_trace=trace)
        proposal, failure = _run_tools(turn.tool_calls, by_name, transcript, trace)
        if proposal is not None:
            return AgentReply(message=turn.content.strip() or proposal.rationale, proposal=proposal, tool_trace=trace)
        if failure is not None:
            proposal_failures += 1
            if proposal_failures > 1:
                detail = str(failure)
                text = turn.content.strip()
                return AgentReply(message=f"{text}\n{detail}".strip(), proposal=None, tool_trace=trace)
    return AgentReply(message="工具调用次数已用完，请把要求再说具体一点。", proposal=None, tool_trace=trace)


def _run_tools(
    calls: list[ToolCall],
    by_name: dict[str, AgentTool],
    transcript: list[dict[str, Any]],
    trace: list[ToolTrace],
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
