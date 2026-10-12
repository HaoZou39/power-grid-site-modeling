"""Keep what the assistant knows in step with the software. Checklist: markdown/AGENT_MODULE.md, 让助手跟上新功能."""

from __future__ import annotations

import json
import re
from pathlib import Path

from agent.analysis import RANKED_OBJECTIVES
from agent.tools import build_tools
from tests.test_agent import _context

# Written to the solution table but not compared (markdown/GUIDED_SEARCH.md).
REPORTED_ONLY = {"road_distance"}


def _tool_names() -> set[str]:
    return {tool.name for tool in build_tools(_context())}


def test_tool_table_matches_the_registry() -> None:
    text = Path("markdown/AGENT_MODULE.md").read_text(encoding="utf-8")
    section = text.split("\n## 工具\n", 1)[1].split("\n## ", 1)[0]
    assert set(re.findall(r"^\| `(\w+)` \|", section, re.M)) == _tool_names()


def test_frontend_objective_keys_match_the_ranked_objectives() -> None:
    text = Path("frontend/src/agent/workspace_snapshot.ts").read_text(encoding="utf-8")
    block = re.search(r"const OBJECTIVE_FIELDS[^=]*= \[(.*?)\];", text, re.S)
    assert block is not None
    keys = set(re.findall(r'\["(\w+)", "', block.group(1)))
    assert keys == set(RANKED_OBJECTIVES) | REPORTED_ONLY


def test_eval_cases_only_expect_registered_tools() -> None:
    cases = json.loads(Path("experiments/agent_eval_cases.json").read_text(encoding="utf-8"))["cases"]
    expected = {name for case in cases for name in case.get("expect_tools", [])}
    assert expected <= _tool_names()
