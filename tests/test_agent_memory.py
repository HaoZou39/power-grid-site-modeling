"""Memory file format, MemoryOps, prompt selection and the memory routes."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from agent.memory import (
    MEMORY_PROMPT_LIMIT,
    MemoryEntry,
    apply_memory_ops,
    load_memory,
    parse_memory,
    render_memory,
    select_for_prompt,
)
from agent.tools import build_tools
from agent.workspace import Proposal
from backend.app.main import create_app
from tests.test_agent import _context, snapshot

SAMPLE = """# 选址助手记忆

## 偏好
- [m1 | 全局 | 2026-10-12 | 明说] 农田一般计入成本，系数 0.3
- [m2 | cangnan | 2026-10-12 | 推断] 进货原点常用 (1700, 100)

## 常用指令
- [m3 | 全局 | 2026-10-12 | 明说] “老规矩” = 农田计入成本 0.3，变电站 80×50，然后优化

## 场景备注
"""


@pytest.fixture(autouse=True)
def isolate_agent_settings(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_SETTINGS_DIR", str(tmp_path / "agent-settings"))


def entries() -> list[MemoryEntry]:
    return parse_memory(SAMPLE)


def test_memory_file_round_trips() -> None:
    parsed = entries()
    assert [entry.id for entry in parsed] == ["m1", "m2", "m3"]
    assert parsed[1].scene == "cangnan" and parsed[1].source == "inferred"
    assert parsed[2].section == "command"
    assert render_memory(parsed) == SAMPLE


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("## 杂项\n", 1),
        ("## 偏好\n- m1 农田 0.3\n", 2),
        ("## 偏好\n- [m1 | 全局 | 2026-10-12 | 听说] 农田\n", 2),
        ("## 偏好\n- [m1 | 全局 | 2026-10-12 | 明说] a\n- [m1 | 全局 | 2026-10-12 | 明说] b\n", 3),
        ("- [m1 | 全局 | 2026-10-12 | 明说] 没有标题\n", 1),
    ],
)
def test_bad_memory_lines_name_the_line(text: str, line: int) -> None:
    with pytest.raises(ValueError, match=f"第 {line} 行"):
        parse_memory(text)


def test_missing_memory_file_is_created_empty(tmp_path) -> None:
    path = tmp_path / "memory" / "MEMORY.md"
    assert load_memory(path) == []
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# 选址助手记忆")
    assert "## 偏好" in text and "## 常用指令" in text and "## 场景备注" in text


def test_memory_ops_apply_in_order() -> None:
    today = date(2026, 10, 13)
    result = apply_memory_ops(entries(), _ops([
        {"kind": "revise", "memory_id": "m1", "text": "农田一般计入成本，系数 0.25"},
        {"kind": "forget", "memory_id": "m2"},
        {"kind": "remember", "section": "scene_note", "scene": "cangnan", "source": "stated", "text": "北侧是规划用地"},
    ]), "cangnan", today)
    assert [entry.id for entry in result] == ["m1", "m3", "m4"]
    assert result[0].text.endswith("0.25") and result[0].date == "2026-10-13"
    assert result[2].section == "scene_note" and result[2].scene == "cangnan"
    assert [entry.id for entry in entries()] == ["m1", "m2", "m3"]


def test_memory_ops_reject_unknown_ids_and_other_scenes() -> None:
    with pytest.raises(ValueError, match="第 2 个记忆改动无效：没有这条记忆"):
        apply_memory_ops(entries(), _ops([{"kind": "forget", "memory_id": "m1"}, {"kind": "forget", "memory_id": "m1"}]), "cangnan")
    with pytest.raises(ValueError, match="当前场景"):
        apply_memory_ops(entries(), _ops([{"kind": "remember", "section": "preference", "scene": "other", "source": "stated", "text": "x"}]), "cangnan")


def test_prompt_takes_global_and_current_scene_only() -> None:
    from agent.prompts import system_prompt

    assert [entry.id for entry in select_for_prompt(entries(), "other")] == ["m1", "m3"]
    prompt = system_prompt(select_for_prompt(entries(), "cangnan"))
    assert "[m2 | 偏好 | cangnan | 推断] 进货原点常用 (1700, 100)" in prompt
    assert "超过" not in prompt
    many = [entries()[0].model_copy(update={"id": f"m{i}"}) for i in range(MEMORY_PROMPT_LIMIT + 1)]
    assert f"超过 {MEMORY_PROMPT_LIMIT} 条" in system_prompt(many)
    assert "记忆：暂无。" in system_prompt([])


def test_proposal_may_carry_only_memory() -> None:
    from dataclasses import replace

    propose = {tool.name: tool for tool in build_tools(replace(_context(), memory=tuple(entries())))}["propose_changes"]
    result = propose.handler({"rationale": "记下", "memory": [{"kind": "forget", "memory_id": "m2"}]})
    assert result["ops"] == [] and result["memory"][0]["memory_id"] == "m2"
    with pytest.raises(ValueError, match="没有这条记忆"):
        propose.handler({"rationale": "忘掉", "memory": [{"kind": "forget", "memory_id": "m9"}]})
    with pytest.raises(ValueError, match="提案没有任何操作"):
        Proposal.model_validate({"rationale": "空的"})


def test_eval_scores_memory_changes() -> None:
    import json
    from pathlib import Path

    from experiments.agent_eval import score_case

    remember = {"kind": "remember", "section": "preference", "scene": None, "source": "stated", "text": "农田系数 0.3"}
    case = {"expect": [], "expect_memory": [{"kind": "remember", "section": "preference", "text_has": ["0.3"]}]}
    assert score_case(case, {"rationale": "-", "ops": [], "memory": [remember]}, "") == (True, "ok")
    assert score_case(case, {"rationale": "-", "ops": [], "memory": [{**remember, "text": "农田系数"}]}, "")[0] is False
    assert score_case({"expect": []}, {"rationale": "-", "ops": [], "memory": [remember]}, "")[0] is False

    cases = json.loads(Path("experiments/agent_eval_cases.json").read_text(encoding="utf-8"))["cases"]
    for item in cases:
        for raw in item.get("memory", []):
            MemoryEntry.model_validate(raw)


def test_memory_routes_read_and_write(monkeypatch, tmp_path) -> None:
    path = tmp_path / "MEMORY.md"
    monkeypatch.setenv("AGENT_MEMORY_PATH", str(path))
    client = TestClient(create_app("sqlite://:memory:", ""))
    first = client.get("/api/v1/agent/memory").json()
    assert first == {"entries": [], "prompt_limit": MEMORY_PROMPT_LIMIT}
    assert path.is_file()

    written = client.post("/api/v1/agent/memory", json={
        "scene_name": "cangnan",
        "ops": [{"kind": "remember", "section": "preference", "source": "stated", "text": "农田系数 0.3"}],
    })
    assert written.status_code == 200
    assert written.json()["entries"][0]["id"] == "m1"
    assert "农田系数 0.3" in path.read_text(encoding="utf-8")

    before = path.read_text(encoding="utf-8")
    bad = client.post("/api/v1/agent/memory", json={"scene_name": "cangnan", "ops": [{"kind": "forget", "memory_id": "m7"}]})
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "memory_op_invalid"
    assert path.read_text(encoding="utf-8") == before


def test_broken_memory_file_is_reported(monkeypatch, tmp_path) -> None:
    path = tmp_path / "MEMORY.md"
    path.write_text("## 偏好\n- 随手写的一行\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_MEMORY_PATH", str(path))
    response = TestClient(create_app("sqlite://:memory:", "")).get("/api/v1/agent/memory")
    assert response.status_code == 422
    assert "第 2 行" in response.json()["detail"]["message"]


def _ops(raw: list[dict]) -> list:
    return list(Proposal.model_validate({"rationale": "-", "memory": raw}).memory)
