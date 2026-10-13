"""What the user told us about their preference: scheme-card choices (JSONL) and default weights (JSON).

Only the API routes behind the user's clicks write here; the model only reads.
Format and rules: markdown/AGENT_MODULE.md, section 偏好推荐.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.analysis import RANKED_OBJECTIVES


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Candidate(_Model):
    id: str = Field(min_length=1)
    objectives: dict[str, float] = Field(min_length=1)


class ChoiceInput(_Model):
    """One click: the user picked `chosen_id` out of every scheme shown at that moment."""

    scene_name: str = Field(min_length=1)
    experiment_id: str | None
    chosen_id: str
    candidates: list[Candidate] = Field(min_length=2)

    @model_validator(mode="after")
    def _chosen_in_menu(self) -> ChoiceInput:
        ids = [candidate.id for candidate in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("候选方案编号重复")
        if self.chosen_id not in ids:
            raise ValueError(f"选中的方案 {self.chosen_id} 不在候选里")
        return self


class PreferenceChoice(ChoiceInput):
    recorded_at: str  # ISO 8601, set by the server


class PreferenceDefaults(_Model):
    """Importance the user set before any choice: 0 (ignore) to 5, one per objective; missing keys count as 1."""

    weights: dict[str, float]

    @model_validator(mode="after")
    def _known_and_in_range(self) -> PreferenceDefaults:
        for key, value in self.weights.items():
            if key not in RANKED_OBJECTIVES:
                raise ValueError(f"不认识的目标：{key}")
            if not 0 <= value <= 5:
                raise ValueError(f"{RANKED_OBJECTIVES[key]} 的重要程度要在 0 到 5 之间")
        return self


def _memory_file(env: str, name: str) -> Path:
    raw = os.getenv(env, "").strip()
    return Path(raw) if raw else Path(__file__).resolve().parents[2] / "memory" / name


def preference_path() -> Path:
    return _memory_file("AGENT_PREFERENCE_HISTORY_PATH", "PREFERENCE_CHOICES.jsonl")


def defaults_path() -> Path:
    return _memory_file("AGENT_PREFERENCE_DEFAULTS_PATH", "PREFERENCE_DEFAULTS.json")


def load_defaults(path: Path) -> PreferenceDefaults | None:
    if not path.is_file():
        return None
    try:
        return PreferenceDefaults.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"偏好默认值文件无效：{exc}") from exc


def save_defaults(path: Path, defaults: PreferenceDefaults) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(defaults.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_choices(path: Path) -> list[PreferenceChoice]:
    if not path.is_file():
        return []
    choices = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            choices.append(PreferenceChoice.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(f"偏好记录第 {number} 行无效：{exc}") from exc
    return choices


def append_choice(path: Path, choice: PreferenceChoice) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(choice.model_dump(), ensure_ascii=False) + "\n")
