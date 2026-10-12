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
            with httpx.Client(transport=self.transport, timeout=self.config.timeout_s) as client:
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
