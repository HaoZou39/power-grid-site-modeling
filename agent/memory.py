"""Decision-maker memory kept in one readable markdown file.

The model only proposes MemoryOps; the file changes after the user confirms them.
Format and rules: markdown/AGENT_MODULE.md, section 记忆.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

MEMORY_PROMPT_LIMIT = 80
TITLE = "# 选址助手记忆"
GLOBAL = "全局"
SECTIONS = {"preference": "偏好", "command": "常用指令", "scene_note": "场景备注"}
SOURCES = {"stated": "明说", "inferred": "推断"}

Section = Literal["preference", "command", "scene_note"]
Source = Literal["stated", "inferred"]

_LINE = re.compile(r"^- \[(m\d+) \| ([^|\]]+?) \| (\d{4}-\d{2}-\d{2}) \| ([^|\]]+?)\] (.+)$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryEntry(_Model):
    id: str = Field(pattern=r"^m\d+$")
    section: Section
    scene: str | None
    date: str
    source: Source
    text: str = Field(min_length=1)


class Remember(_Model):
    kind: Literal["remember"]
    section: Section
    scene: str | None = None
    source: Source
    text: str = Field(min_length=1)


class Revise(_Model):
    kind: Literal["revise"]
    memory_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class Forget(_Model):
    kind: Literal["forget"]
    memory_id: str = Field(min_length=1)


MemoryOp = Annotated[Union[Remember, Revise, Forget], Field(discriminator="kind")]


def memory_path() -> Path:
    raw = os.getenv("AGENT_MEMORY_PATH", "").strip()
    return Path(raw) if raw else Path(__file__).resolve().parents[1] / "memory" / "MEMORY.md"


def load_memory(path: Path) -> list[MemoryEntry]:
    """Read the file, creating an empty one on first use."""
    if not path.is_file():
        save_memory(path, [])
        return []
    return parse_memory(path.read_text(encoding="utf-8"))


def parse_memory(text: str) -> list[MemoryEntry]:
    by_title = {title: key for key, title in SECTIONS.items()}
    by_source = {label: key for key, label in SOURCES.items()}
    entries: list[MemoryEntry] = []
    section: str | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line == TITLE:
            continue
        if line.startswith("## "):
            section = by_title.get(line[3:].strip())
            if section is None:
                raise ValueError(f"记忆文件第 {number} 行：不认识的标题 {line}")
            continue
        found = _LINE.match(line)
        if found is None or section is None:
            raise ValueError(f"记忆文件第 {number} 行格式不对：{line}")
        memory_id, scope, day, source, body = found.groups()
        if source not in by_source:
            raise ValueError(f"记忆文件第 {number} 行：来源只能是明说或推断")
        if any(entry.id == memory_id for entry in entries):
            raise ValueError(f"记忆文件第 {number} 行：编号 {memory_id} 重复")
        entries.append(MemoryEntry(
            id=memory_id,
            section=section,
            scene=None if scope == GLOBAL else scope,
            date=day,
            source=by_source[source],
            text=body.strip(),
        ))
    return entries


def render_memory(entries: list[MemoryEntry]) -> str:
    lines = [TITLE]
    for key, title in SECTIONS.items():
        lines += ["", f"## {title}"]
        lines += [
            f"- [{entry.id} | {entry.scene or GLOBAL} | {entry.date} | {SOURCES[entry.source]}] {entry.text}"
            for entry in entries
            if entry.section == key
        ]
    return "\n".join(lines) + "\n"


def save_memory(path: Path, entries: list[MemoryEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(render_memory(entries), encoding="utf-8")
    temp.replace(path)


def apply_memory_ops(
    entries: list[MemoryEntry],
    ops: list[MemoryOp],
    scene_name: str,
    today: date | None = None,
) -> list[MemoryEntry]:
    """Return the new entry list. Checks run in order; the input list is not changed."""
    day = (today or date.today()).isoformat()
    result = list(entries)
    for index, op in enumerate(ops, start=1):
        try:
            result = _apply(result, op, scene_name, day)
        except ValueError as exc:
            raise ValueError(f"第 {index} 个记忆改动无效：{exc}") from exc
    return result


def _apply(entries: list[MemoryEntry], op: MemoryOp, scene_name: str, day: str) -> list[MemoryEntry]:
    text = getattr(op, "text", "").strip()
    if isinstance(op, Remember):
        if op.scene is not None and op.scene != scene_name:
            raise ValueError(f"范围只能是全局或当前场景 {scene_name}")
        _one_line(text)
        number = max((int(entry.id[1:]) for entry in entries), default=0) + 1
        added = MemoryEntry(id=f"m{number}", section=op.section, scene=op.scene, date=day, source=op.source, text=text)
        return [*entries, added]
    position = next((i for i, entry in enumerate(entries) if entry.id == op.memory_id), None)
    if position is None:
        raise ValueError(f"没有这条记忆：{op.memory_id}")
    if isinstance(op, Forget):
        return entries[:position] + entries[position + 1:]
    _one_line(text)
    revised = entries[position].model_copy(update={"text": text, "date": day})
    return [*entries[:position], revised, *entries[position + 1:]]


def _one_line(text: str) -> None:
    if not text or "\n" in text:
        raise ValueError("记忆正文必须是非空的一行")


def select_for_prompt(entries: list[MemoryEntry], scene_name: str) -> list[MemoryEntry]:
    """Global entries plus the current scene's, in file order. Swap this when retrieval is needed."""
    return [entry for entry in entries if entry.scene is None or entry.scene == scene_name]
