from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

from backend.app.domain.plugins import PluginResult, PluginSpec


class DemoConfig(BaseModel):
    values: list[float] = Field(default_factory=lambda: [1.0, 2.0, 3.0])
    multiplier: float = 1.0


def _parse_config(config: dict[str, Any]) -> DemoConfig:
    parsed = (
        DemoConfig.model_validate(config)
        if hasattr(DemoConfig, "model_validate")
        else DemoConfig.parse_obj(config)
    )
    if not parsed.values:
        raise ValueError("values must contain at least one number")
    if not all(math.isfinite(value) for value in parsed.values):
        raise ValueError("values must contain only finite numbers")
    if not math.isfinite(parsed.multiplier):
        raise ValueError("multiplier must be finite")
    return parsed


def _schema(model: type[BaseModel]) -> dict[str, Any]:
    if hasattr(model, "model_json_schema"):
        return model.model_json_schema()  # type: ignore[attr-defined]
    return model.schema()


class DemoAlgorithmPlugin:
    id = "demo.algorithm"
    version = "0.1.0"

    def describe(self) -> PluginSpec:
        return PluginSpec(
            id=self.id,
            version=self.version,
            kind="algorithm",
            name="Demo algorithm",
            description="A deterministic plugin for checking the v0 task and result flow.",
            config_schema=_schema(DemoConfig),
        )

    def validate_config(self, config: dict[str, Any]) -> None:
        _parse_config(config)

    def run(self, config: dict[str, Any], reporter) -> PluginResult:
        parsed = _parse_config(config)
        reporter(0.2, "validated", "Configuration validated")
        total = sum(parsed.values)
        reporter(0.6, "computed", "Computed aggregate values")
        average = total / len(parsed.values)
        weighted = total * parsed.multiplier
        reporter(0.9, "assembling_result", "Preparing result")
        return PluginResult(
            status="succeeded",
            metrics={"sum": total, "average": average, "weighted_sum": weighted},
            data={"count": len(parsed.values), "multiplier": parsed.multiplier},
        )
