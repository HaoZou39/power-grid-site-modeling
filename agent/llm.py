"""OpenAI-compatible chat. The key is sent only as an Authorization header."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from agent.config import AgentConfig


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelTurn:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)


class ChatModel(Protocol):
    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn: ...


def iter_sse(lines: Any) -> Any:
    """Yield content pieces from an OpenAI event stream, then one ModelTurn.

    Reasoning text is not shown. Only `delta.content` reaches the caller.
    """
    content: list[str] = []
    calls: dict[int, dict[str, str]] = {}
    for raw in lines:
        line = str(raw).strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError as exc:
            raise RuntimeError("模型接口没有返回结果") from exc
        choices = chunk.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        piece = delta.get("content")
        if isinstance(piece, str) and piece:
            content.append(piece)
            yield piece
        for call in delta.get("tool_calls") or []:
            slot = calls.setdefault(int(call.get("index") or 0), {"id": "", "name": "", "arguments": ""})
            if call.get("id"):
                slot["id"] = str(call["id"])
            function = call.get("function") or {}
            if function.get("name"):
                slot["name"] += str(function["name"])
            if function.get("arguments"):
                slot["arguments"] += str(function["arguments"])
    yield ModelTurn("".join(content), _parsed_calls(calls))


def _parsed_calls(calls: dict[int, dict[str, str]]) -> list[ToolCall]:
    parsed = []
    for index in sorted(calls):
        slot = calls[index]
        raw = slot["arguments"] or "{}"
        try:
            arguments = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("模型返回的工具参数不是 JSON") from exc
        if not isinstance(arguments, dict):
            raise RuntimeError("模型返回的工具参数不是 JSON 对象")
        parsed.append(ToolCall(id=slot["id"], name=slot["name"], arguments=arguments))
    return parsed


class OpenAICompatModel:
    def __init__(self, config: AgentConfig, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        self.transport = transport

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
        }
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        try:
            with httpx.Client(transport=self.transport, timeout=self.config.timeout_s, follow_redirects=False) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError("模型接口没有返回结果") from exc
        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("模型接口没有返回结果") from exc
        return ModelTurn(content=message.get("content") or "", tool_calls=_tool_calls(message))

    def iter_turn(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        try:
            with httpx.Client(transport=self.transport, timeout=self.config.timeout_s, follow_redirects=False) as client:
                with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    if "application/json" in response.headers.get("content-type", ""):
                        turn = _turn_from_json(response.json())
                        if turn.content:
                            yield turn.content
                        yield turn
                        return
                    yield from iter_sse(response.iter_lines())
        except httpx.HTTPError as exc:
            raise RuntimeError("模型接口没有返回结果") from exc


def _turn_from_json(body: dict[str, Any]) -> ModelTurn:
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("模型接口没有返回结果") from exc
    return ModelTurn(content=message.get("content") or "", tool_calls=_tool_calls(message))


def _tool_calls(message: dict[str, Any]) -> list[ToolCall]:
    calls = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        raw = function.get("arguments") or "{}"
        try:
            arguments = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as exc:
            raise RuntimeError("模型返回的工具参数不是 JSON") from exc
        if not isinstance(arguments, dict):
            raise RuntimeError("模型返回的工具参数不是 JSON 对象")
        calls.append(ToolCall(id=str(call.get("id") or ""), name=str(function.get("name") or ""), arguments=arguments))
    return calls
