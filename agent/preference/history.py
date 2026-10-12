"""Append-only JSONL persistence for preference choices."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from agent.preference.models import Candidate, PreferenceChoice

DEFAULT_HISTORY_ENV = "AGENT_PREFERENCE_HISTORY_PATH"


def history_path() -> Path:
    configured = os.getenv(DEFAULT_HISTORY_ENV, "").strip()
    return Path(configured).expanduser() if configured else Path("memory") / "PREFERENCE_CHOICES.jsonl"


def append_choice(path: Path, choice: PreferenceChoice) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = choice.to_dict()
    if not payload["timestamp"]:
        payload["timestamp"] = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def load_choices(path: Path) -> list[PreferenceChoice]:
    if not path.is_file():
        return []
    choices: list[PreferenceChoice] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            choices.append(choice_from_dict(payload))
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise ValueError(f"preference history line {line_number} is invalid") from exc
    return choices


def choice_from_dict(payload: dict[str, Any]) -> PreferenceChoice:
    if not isinstance(payload, dict):
        raise ValueError("choice record must be an object")
    candidates = tuple(
        Candidate(
            candidate_id=str(item["candidate_id"]),
            objectives=item["objectives"],
            variables=item.get("variables", {}),
            metadata=item.get("metadata", {}),
        )
        for item in payload["candidates"]
    )
    return PreferenceChoice(
        scene_id=str(payload["scene_id"]),
        experiment_id=payload.get("experiment_id"),
        timestamp=payload.get("timestamp"),
        candidates=candidates,
        chosen_id=str(payload["chosen_id"]),
        reason=str(payload.get("reason", "")),
        metadata=payload.get("metadata", {}),
    )


def history_summary(choices: Iterable[PreferenceChoice]) -> dict[str, Any]:
    items = list(choices)
    return {
        "choice_count": len(items),
        "scene_count": len({item.scene_id for item in items}),
        "latest_timestamp": items[-1].timestamp if items else None,
    }
