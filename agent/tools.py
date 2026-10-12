"""Read-only tools. Handlers call ToolContext; they do not import the map or the search."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import TypeAdapter

from agent.analysis import rank_pose
from agent.memory import MemoryEntry, apply_memory_ops
from agent.preference.recommend import PreferenceConfig, recommend_poses
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
    footprint_terrain: Reader
    preference_choices: Reader
    memory: tuple[MemoryEntry, ...] = ()
    preference: PreferenceConfig = PreferenceConfig()


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    params_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]


_EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}


def build_tools(context: ToolContext) -> list[AgentTool]:
    tools = [
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
            "analyze_pose",
            "分析一个已有方案：各目标在全部方案里的名次和最好值、占地内用地与地形统计、进场报告。不改地图。",
            {
                "type": "object",
                "properties": {"pose_id": {"type": "string"}},
                "required": ["pose_id"],
                "additionalProperties": False,
            },
            lambda args: _analyze(context, args),
        ),
        AgentTool(
            "recommend_poses",
            "按用户以往在方案小窗里点「记为我的选择」的记录，给当前地图上的方案排序，返回几个彼此有差别的推荐。没有记录时按各目标等权排序。不改地图。",
            {
                "type": "object",
                "properties": {"top_k": {"type": "integer", "minimum": 1, "maximum": 10}},
                "additionalProperties": False,
            },
            lambda args: recommend_poses(
                context.snapshot, context.preference_choices(), context.preference, args.get("top_k")
            ),
        ),
        AgentTool(
            "propose_changes",
            "提出一组地图编辑（ops）和记忆改动（memory）。调用后本轮结束，用户确认后才生效。",
            TypeAdapter(Proposal).json_schema(),
            lambda args: _propose(context, args),
        ),
    ]
    return tools


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


def _analyze(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    pose_id = args.get("pose_id")
    if not isinstance(pose_id, str) or not pose_id:
        raise ValueError("analyze_pose 需要 pose_id")
    result = rank_pose(context.snapshot, pose_id)
    pose = result["pose"]
    result["footprint"] = context.footprint_terrain(pose["x"], pose["y"], pose["theta"])
    try:
        result["site_report"] = context.evaluate_pose(pose["x"], pose["y"], pose["theta"])
    except ValueError as exc:
        # The ranks and footprint still hold; the model says the access report is missing.
        result["site_report"] = {"error": str(exc)}
    return result


def _propose(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ValueError("propose_changes 的参数必须是对象")
    proposal = Proposal.model_validate(args)
    if proposal.ops:
        validate_ops(context.snapshot, list(proposal.ops))
    apply_memory_ops(list(context.memory), list(proposal.memory), context.snapshot.scene_name)
    return proposal.model_dump(mode="json")
