"""Model settings. The key stays out of logs and API responses."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agent.settings import effective_model_config


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
        effective = effective_model_config()
        values = {
            "AGENT_BASE_URL": effective["base_url"],
            "AGENT_MODEL": effective["model"],
            "AGENT_API_KEY": effective["api_key"],
        }
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


def _load_dotenv() -> None:
    """Fill unset variables from the repo-root `.env`. Existing environment wins."""
    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name and name not in os.environ:
            os.environ[name] = value.strip().strip('"').strip("'")


_load_dotenv()


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
