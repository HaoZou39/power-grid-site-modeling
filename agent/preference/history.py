"""Past choices the user made in the scheme card, one JSON object per line.

Only the API route that handles the user's click appends here; the model only reads.
Format and rules: markdown/AGENT_MODULE.md, section 偏好推荐.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


def preference_path() -> Path:
    raw = os.getenv("AGENT_PREFERENCE_HISTORY_PATH", "").strip()
    return Path(raw) if raw else Path(__file__).resolve().parents[2] / "memory" / "PREFERENCE_CHOICES.jsonl"


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
