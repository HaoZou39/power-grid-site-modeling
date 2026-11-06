"""Per-user assistant files. The user id is an argument, never an environment variable."""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

_USER_ID = re.compile(r"^[0-9a-fA-F-]{8,64}$")
_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def user_dir(user_id: str) -> Path:
    if not isinstance(user_id, str) or not _USER_ID.fullmatch(user_id):
        raise ValueError("invalid user id")
    raw = os.getenv("AGENT_MEMORY_ROOT", "").strip()
    root = Path(raw) if raw else Path(__file__).resolve().parents[1] / "memory"
    return root / "users" / user_id


def _lock(user_id: str) -> threading.RLock:
    with _locks_guard:
        lock = _locks.get(user_id)
        if lock is None:
            lock = threading.RLock()
            _locks[user_id] = lock
        return lock


def memory_file(user_id: str) -> Path:
    return user_dir(user_id) / "MEMORY.md"


def preference_files(user_id: str) -> tuple[Path, Path]:
    directory = user_dir(user_id)
    return directory / "PREFERENCE_CHOICES.jsonl", directory / "PREFERENCE_DEFAULTS.json"


def user_memory_enabled(user_id: str) -> bool:
    path = user_dir(user_id) / "memory.json"
    if not path.is_file():
        return True
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("个人记忆开关不是有效 JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("enabled"), bool):
        raise ValueError("个人记忆开关无效")
    return value["enabled"]


def set_user_memory_enabled(user_id: str, enabled: bool) -> None:
    path = user_dir(user_id) / "memory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"enabled": enabled}, ensure_ascii=False) + "\n", encoding="utf-8")


def disable_user_memory(user_id: str, clear) -> None:
    with _lock(user_id):
        set_user_memory_enabled(user_id, False)
        clear()
