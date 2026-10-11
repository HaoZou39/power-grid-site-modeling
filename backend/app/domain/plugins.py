"""Plugin protocol and registry types used by both API and worker processes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


class PluginError(ValueError):
    """Raised when a plugin cannot accept a requested operation."""


@dataclass(frozen=True)
class PluginSpec:
    id: str
    version: str
    kind: str
    name: str
    description: str
    config_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PluginResult:
    status: str
    metrics: dict[str, float]
    data: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProgressReporter(Protocol):
    def __call__(self, progress: float, stage: str, message: str) -> None: ...


class Plugin(Protocol):
    id: str
    version: str

    def describe(self) -> PluginSpec: ...

    def validate_config(self, config: dict[str, Any]) -> None: ...

    def run(
        self,
        config: dict[str, Any],
        reporter: ProgressReporter,
    ) -> PluginResult: ...


class PluginRegistry:
    """Explicit registry that keeps plugin discovery deterministic."""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> None:
        if plugin.id in self._plugins:
            raise PluginError(f"plugin already registered: {plugin.id}")
        self._plugins[plugin.id] = plugin

    def get(self, plugin_id: str) -> Plugin:
        try:
            return self._plugins[plugin_id]
        except KeyError as exc:
            raise PluginError(f"unknown plugin: {plugin_id}") from exc

    def list_specs(self) -> list[PluginSpec]:
        return [self._plugins[key].describe() for key in sorted(self._plugins)]

    def __contains__(self, plugin_id: str) -> bool:
        return plugin_id in self._plugins
