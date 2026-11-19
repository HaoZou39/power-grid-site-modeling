"""Immutable, self-contained decision snapshots; no evaluator or optimizer dependency."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FilterCandidate(SnapshotModel):
    id: str = Field(min_length=1)
    original_number: int = Field(ge=1)
    metrics: dict[str, FiniteFloat | None]
    geometry: dict[str, Any]
    data: dict[str, Any]


class FilterSort(SnapshotModel):
    key: str = Field(min_length=1)
    direction: Literal["ascending", "descending", "original"]


class FilterStage(FilterSort):
    lower: FiniteFloat
    upper: FiniteFloat
    retained_count: int = Field(ge=0)


class FilterSnapshot(SnapshotModel):
    schema_version: Literal[1]
    problem_type: Literal["site", "routing"]
    scene_name: str = Field(min_length=1)
    source_experiment_id: str | None
    scene_version: dict[str, Any]
    captured_at: datetime
    scope: dict[str, Any]
    context: dict[str, Any]
    candidates: list[FilterCandidate] = Field(min_length=1)
    retained_ids: list[str]
    stages: list[FilterStage]
    display_sort: FilterSort | None

    @model_validator(mode="after")
    def verify_selection(self) -> "FilterSnapshot":
        ids = [item.id for item in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("候选编号重复")
        if len({stage.key for stage in self.stages}) != len(self.stages):
            raise ValueError("筛选指标重复")
        order = {value: index for index, value in enumerate(ids)}

        def sort(items: list[FilterCandidate], rule: FilterSort) -> list[FilterCandidate]:
            def key(item: FilterCandidate) -> tuple:
                value = item.metrics.get(rule.key)
                return (value is None, 0 if value is None or rule.direction == "original"
                        else value * (-1 if rule.direction == "descending" else 1), order[item.id])
            return sorted(items, key=key)

        active = self.candidates
        for stage in self.stages:
            if stage.lower > stage.upper:
                raise ValueError("筛选下界不能大于上界")
            active = [item for item in sort(active, stage)
                      if (value := item.metrics.get(stage.key)) is not None and stage.lower <= value <= stage.upper]
            if len(active) != stage.retained_count:
                raise ValueError("轮次保留数量与候选快照不一致")
        if self.display_sort:
            active = sort(active, self.display_sort)
        if [item.id for item in active] != self.retained_ids:
            raise ValueError("最终保留顺序与筛选记录不一致")
        return self


class SaveFilterCaseRequest(SnapshotModel):
    name: str = Field(min_length=1, max_length=200)
    snapshot: FilterSnapshot


def save_filter_case(root: Path, request: SaveFilterCaseRequest) -> str:
    snapshot = request.snapshot
    name = request.name.strip()
    if not name or not snapshot.retained_ids:
        raise ValueError("名称和最终保留方案不能为空")
    case_id = f"filter-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    summary = {
        "display_name": name, "algorithm": "filter_snapshot", "is_case": True,
        "case_kind": "filter_result", "problem_type": snapshot.problem_type,
        "scene_name": snapshot.scene_name, "n_solutions": len(snapshot.retained_ids),
        "candidate_count": len(snapshot.candidates), "source_experiment_id": snapshot.source_experiment_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    # Publish only after both files are complete. No source directory is needed to reopen.
    with TemporaryDirectory(prefix=".filter-case-", dir=root) as staging:
        folder = Path(staging) / "case"
        folder.mkdir()
        for filename, value in (("filter_snapshot.json", snapshot.model_dump(mode="json")), ("run_summary.json", summary)):
            (folder / filename).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        folder.rename(root / case_id)
    return case_id
