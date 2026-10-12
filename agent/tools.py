"""Read-only tools. Handlers call ToolContext; they do not import the map or the search."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import TypeAdapter

from agent.workspace import Proposal, WorkspaceSnapshot, validate_ops


Reader = Callable[..., Any]


@dataclass(frozen=True)
class ToolContext:
    snapshot: WorkspaceSnapshot
    list_scenes: Reader
    list_experiments: Reader
    get_experiment: Reader
    list_plugins: Reader
    evaluate_pose: Reader


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    params_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]


_EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}


def build_tools(context: ToolContext) -> list[AgentTool]:
    return [
        AgentTool("get_workspace", "返回本轮工作区快照。", _EMPTY, lambda _args: _workspace(context)),
        AgentTool("list_scenes", "列出已经准备好的场景。", _EMPTY, lambda _args: {"scenes": context.list_scenes()}),
        AgentTool(
            "list_experiments",
            "列出已完成的优化结果。",
            _EMPTY,
            lambda _args: {"experiments": context.list_experiments()},
        ),
        AgentTool(
            "get_experiment",
            "读取一个已完成实验的摘要和产物清单。",
            {
                "type": "object",
                "properties": {"experiment_id": {"type": "string"}},
                "required": ["experiment_id"],
                "additionalProperties": False,
            },
            lambda args: _experiment(context, args),
        ),
        AgentTool("list_plugins", "列出可提交的插件及其配置。", _EMPTY, lambda _args: {"plugins": context.list_plugins()}),
        AgentTool(
            "evaluate_pose",
            "用当前场景和建筑尺寸评估一个位姿的进场报告，不改地图。",
            {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "theta": {"type": "number"},
                },
                "required": ["x", "y", "theta"],
                "additionalProperties": False,
            },
            lambda args: _evaluate(context, args),
        ),
        AgentTool(
            "propose_changes",
            "提出一组编辑操作。调用后本轮结束，操作不会自动生效。",
            TypeAdapter(Proposal).json_schema(),
            lambda args: _propose(context, args),
        ),
    ]


def tool_specs(tools: list[AgentTool]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.params_schema,
            },
        }
        for tool in tools
    ]


def _workspace(context: ToolContext) -> dict[str, Any]:
    return context.snapshot.model_dump(mode="json")


def _experiment(context: ToolContext, args: dict[str, Any]) -> Any:
    experiment_id = args.get("experiment_id")
    if not isinstance(experiment_id, str) or not experiment_id:
        raise ValueError("get_experiment 需要 experiment_id")
    return context.get_experiment(experiment_id)


def _evaluate(context: ToolContext, args: dict[str, Any]) -> Any:
    try:
        x = float(args["x"])
        y = float(args["y"])
        theta = float(args["theta"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("evaluate_pose 需要数字 x、y、theta") from exc
    return context.evaluate_pose(x, y, theta)


def _propose(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ValueError("propose_changes 的参数必须是对象")
    proposal = Proposal.model_validate(args)
    validate_ops(context.snapshot, list(proposal.ops))
    return proposal.model_dump(mode="json")
