"""Read-only tools. Handlers call ToolContext; they do not import the map or the search."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import TypeAdapter

from agent.analysis import rank_pose
from agent.memory import MemoryEntry, apply_memory_ops
from agent.preference.models import Candidate, PreferenceChoice
from agent.preference.service import PreferenceService
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
    memory: tuple[MemoryEntry, ...] = ()
    preference_service: PreferenceService | None = None
    recommend_pareto: Reader | None = None
    fit_preference: Reader | None = None


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    params_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]


_EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}
_CANDIDATE = {
    "type": "object",
    "properties": {
        "candidate_id": {"type": "string"},
        "objectives": {"type": "object", "additionalProperties": {"type": "number"}},
        "variables": {"type": "object", "additionalProperties": {"type": "number"}},
        "metadata": {"type": "object"},
    },
    "required": ["candidate_id", "objectives"],
    "additionalProperties": False,
}


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
            "propose_changes",
            "提出一组地图编辑（ops）和记忆改动（memory）。调用后本轮结束，用户确认后才生效。",
            TypeAdapter(Proposal).json_schema(),
            lambda args: _propose(context, args),
        ),
    ]
    if context.preference_service is not None:
        tools.extend(
            [
                AgentTool(
                    "record_preference_choice",
                    "记录用户从一组候选选址方案中做出的选择，供偏好模型学习。",
                    {
                        "type": "object",
                        "properties": {
                            "scene_id": {"type": "string"},
                            "experiment_id": {"type": "string"},
                            "chosen_id": {"type": "string"},
                            "reason": {"type": "string"},
                            "candidates": {"type": "array", "items": _CANDIDATE, "minItems": 1},
                        },
                        "required": ["scene_id", "chosen_id", "candidates"],
                        "additionalProperties": False,
                    },
                    lambda args: _record_preference_choice(context, args),
                ),
                AgentTool(
                    "get_preference_model",
                    "读取当前偏好模型摘要、历史选择数量和置信度。",
                    _EMPTY,
                    lambda _args: context.preference_service.model_summary(),
                ),
            ]
        )
    if context.recommend_pareto is not None:
        if context.fit_preference is not None:
            tools.append(
                AgentTool(
                    "fit_preference_model",
                    "使用历史选择和指定实验的 Pareto 方案训练偏好模型。",
                    {
                        "type": "object",
                        "properties": {
                            "experiment_id": {"type": "string"},
                            "objective_names": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                            "objective_directions": {"type": "object", "additionalProperties": {"enum": ["min", "max"]}},
                        },
                        "required": ["experiment_id", "objective_names"],
                        "additionalProperties": False,
                    },
                    lambda args: context.fit_preference(args),
                )
            )
        tools.append(
            AgentTool(
                "recommend_site_solutions",
                "根据历史选择偏好，从一个实验的 Pareto 方案中推荐少量有差异的选址方案。",
                {
                    "type": "object",
                    "properties": {
                        "experiment_id": {"type": "string"},
                        "objective_names": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        "objective_directions": {"type": "object", "additionalProperties": {"enum": ["min", "max"]}},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                    "required": ["experiment_id", "objective_names"],
                    "additionalProperties": False,
                },
                lambda args: context.recommend_pareto(args),
            )
        )
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


def _record_preference_choice(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    if context.preference_service is None:
        raise ValueError("偏好服务未配置")
    raw_candidates = args.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ValueError("candidates 必须是数组")
    if not all(isinstance(item, dict) for item in raw_candidates):
        raise ValueError("candidates 的每项必须是对象")
    candidates = tuple(
        Candidate(
            candidate_id=str(item["candidate_id"]),
            objectives=item["objectives"],
            variables=item.get("variables", {}),
            metadata=item.get("metadata", {}),
        )
        for item in raw_candidates
    )
    choice = PreferenceChoice(
        scene_id=str(args.get("scene_id", "")),
        experiment_id=args.get("experiment_id"),
        chosen_id=str(args.get("chosen_id", "")),
        reason=str(args.get("reason", "")),
        candidates=candidates,
    )
    return context.preference_service.record_choice(choice)
