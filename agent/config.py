"""Model settings. The key stays in the environment and is never logged."""

from __future__ import annotations

import os
from dataclasses import dataclass


class AgentNotConfigured(RuntimeError):
    """Raised when the chat route has no complete model settings."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__("缺少模型配置：" + ", ".join(missing))


@dataclass(frozen=True)
class AgentConfig:
    base_url: str
    model: str
    api_key: str
    max_tool_rounds: int = 6
    timeout_s: float = 60

    @classmethod
    def from_env(cls) -> AgentConfig:
        values = {name: os.getenv(name, "").strip() for name in ("AGENT_BASE_URL", "AGENT_MODEL", "AGENT_API_KEY")}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise AgentNotConfigured(missing)
        return cls(
            base_url=values["AGENT_BASE_URL"],
            model=values["AGENT_MODEL"],
            api_key=values["AGENT_API_KEY"],
            max_tool_rounds=_positive_int("AGENT_MAX_TOOL_ROUNDS", 6),
            timeout_s=_positive_float("AGENT_TIMEOUT_S", 60),
        )


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是正整数") from exc
    if value <= 0:
        raise ValueError(f"{name} 必须是正整数")
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是正数") from exc
    if value <= 0:
        raise ValueError(f"{name} 必须是正数")
    return value
