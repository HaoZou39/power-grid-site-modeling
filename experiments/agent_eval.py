"""Score the assistant against fixed requests. Calls the configured model; not part of pytest."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.config import AgentConfig
from agent.llm import OpenAICompatModel
from agent.loop import ChatTurn, run_turn
from agent.memory import MemoryEntry
from agent.tools import build_tools
from agent.workspace import WorkspaceSnapshot
from backend.app.application.agent_gateway import live_tool_context
from backend.app.application.registry import build_registry
from backend.app.infrastructure.experiment_catalog import ExperimentCatalog

TOLERANCE = 0.01
UNSUPPORTED_PHRASE = "目前不支持"


@dataclass(frozen=True)
class AgentEvalConfig:
    name: str
    cases_path: Path = Path("experiments/agent_eval_cases.json")
    output_root: Path = Path("outputs/agent_eval")
    model: str | None = None
    repeats: int = 1


def score_ops(expected: list[dict[str, Any]] | None, proposal: dict[str, Any] | None) -> tuple[bool, str]:
    """Listed fields must match; unlisted fields must be empty. `expected=None` means no proposal."""
    if expected is None:
        return (proposal is None, "ok" if proposal is None else "不该出提案")
    if proposal is None:
        return False, "没有提案"
    ops = proposal["ops"]
    if [op["kind"] for op in ops] != [op["kind"] for op in expected]:
        return False, "操作种类或顺序不符"
    for index, (want, got) in enumerate(zip(expected, ops)):
        for key in set(want) | set(got):
            if key == "kind":
                continue
            if key not in want:
                if got.get(key) is not None:
                    return False, f"第 {index + 1} 步多改了 {key}"
            elif not _same(want[key], got.get(key)):
                return False, f"第 {index + 1} 步 {key} 应为 {want[key]}，得到 {got.get(key)}"
    return True, "ok"


def score_memory(expected: list[dict[str, Any]] | None, proposal: dict[str, Any] | None) -> tuple[bool, str]:
    """Kinds and order must match; listed fields must be equal; `text_has` pieces must appear in the text."""
    got = proposal.get("memory", []) if proposal else []
    want = expected or []
    if [op["kind"] for op in got] != [op["kind"] for op in want]:
        return False, "记忆改动种类或顺序不符"
    for index, (spec, op) in enumerate(zip(want, got), start=1):
        for key, value in spec.items():
            if key == "text_has":
                missing = [piece for piece in value if piece not in op.get("text", "")]
                if missing:
                    return False, f"第 {index} 个记忆改动缺少 {missing}"
            elif op.get(key) != value:
                return False, f"第 {index} 个记忆改动 {key} 应为 {value}，得到 {op.get(key)}"
    return True, "ok"


def score_case(
    case: dict[str, Any], proposal: dict[str, Any] | None, message: str, called: frozenset[str] = frozenset(),
) -> tuple[bool, str]:
    """`called` holds the tools that succeeded at least once this turn."""
    passed, reason = score_ops(case["expect"], proposal)
    if passed:
        passed, reason = score_memory(case.get("expect_memory"), proposal)
    missing = [name for name in case.get("expect_tools", []) if name not in called]
    if passed and missing:
        return False, f"没有调用 {missing}"
    if passed and case.get("unsupported"):
        text = message + (proposal["rationale"] if proposal else "")
        if UNSUPPORTED_PHRASE not in text:
            return False, f"没有写明「{UNSUPPORTED_PHRASE}」"
    return passed, reason


def _same(want: Any, got: Any) -> bool:
    if isinstance(want, list):
        # Rings are point sets: start corner and winding do not matter.
        if not isinstance(got, list) or len(got) != len(want):
            return False
        return _points(want) == _points(got)
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        return isinstance(got, (int, float)) and abs(float(got) - float(want)) <= TOLERANCE
    return want == got


def _points(ring: list[dict[str, float]]) -> list[tuple[float, float]]:
    return sorted((round(point["x"], 1), round(point["y"], 1)) for point in ring)


def run_eval(config: AgentEvalConfig) -> dict[str, Any]:
    if config.repeats <= 0:
        raise ValueError("repeats 必须是正整数")
    data = json.loads(config.cases_path.read_text(encoding="utf-8"))
    snapshot = WorkspaceSnapshot.model_validate(data["snapshot"])
    agent_config = AgentConfig.from_env()
    if config.model:
        agent_config = replace(agent_config, model=config.model)
    model = OpenAICompatModel(agent_config)
    catalog, registry = ExperimentCatalog("outputs"), build_registry()

    rows = []
    for case in data["cases"]:
        layers = snapshot.layers.model_copy(
            update={"panel_open": case.get("snapshot_panel_open", snapshot.layers.panel_open)}
        )
        current = snapshot.model_copy(update={
            "scene_name": case.get("snapshot_scene", snapshot.scene_name),
            "layers": layers,
        })
        memory = [MemoryEntry.model_validate(item) for item in case.get("memory", [])]
        tools = build_tools(live_tool_context(current, catalog, registry, memory))
        for repeat in range(config.repeats):
            started = time.perf_counter()
            proposal, tools_used, message = None, "", ""
            try:
                reply = run_turn(
                    model,
                    tools,
                    [ChatTurn("user", case["ask"], case.get("attach"))],
                    current,
                    agent_config.max_tool_rounds,
                    memory=memory,
                )
            except RuntimeError as exc:
                # An upstream timeout is a failed call, not a reason to drop the rows already scored.
                passed, reason = False, f"上游失败：{exc}"
            else:
                proposal = reply.proposal.model_dump(mode="json") if reply.proposal else None
                message = reply.message
                called = frozenset(t.name for t in reply.tool_trace if t.ok)
                passed, reason = score_case(case, proposal, message, called)
                tools_used = ",".join(t.name + ("" if t.ok else "!") for t in reply.tool_trace)
            rows.append({
                "case_id": case["id"],
                "repeat": repeat,
                "passed": passed,
                "reason": reason,
                "ops": json.dumps(proposal["ops"] if proposal else None, ensure_ascii=False),
                "memory": json.dumps(proposal["memory"] if proposal else None, ensure_ascii=False),
                "tools": tools_used,
                "message": message.replace("\t", " ").replace("\n", " "),
                "seconds": round(time.perf_counter() - started, 2),
            })
            print(f"{'PASS' if passed else 'FAIL'} {case['id']}#{repeat} {reason}", flush=True)

    out = config.output_root / config.name
    out.mkdir(parents=True, exist_ok=True)
    with (out / "results.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    by_case: dict[str, int] = {}
    for row in rows:
        by_case[row["case_id"]] = by_case.get(row["case_id"], 0) + int(row["passed"])
    summary = {
        "model": agent_config.model,
        "cases_path": str(config.cases_path),
        "repeats": config.repeats,
        "passed": sum(by_case.values()),
        "total": len(rows),
        "passed_by_case": by_case,
    }
    (out / "eval_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="output directory under outputs/agent_eval")
    parser.add_argument("--cases", type=Path, default=AgentEvalConfig.cases_path)
    parser.add_argument("--model", default=None, help="override AGENT_MODEL")
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    summary = run_eval(AgentEvalConfig(name=args.name, cases_path=args.cases, model=args.model, repeats=args.repeats))
    print(f"{summary['model']}: {summary['passed']}/{summary['total']}")


if __name__ == "__main__":
    main()
