"""HTTP entry for one assistant turn and for the confirmed memory file. The chat route does not apply edits."""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, TypeAdapter

from agent.config import AgentConfig, AgentNotConfigured
from agent.llm import OpenAICompatModel
from agent.loop import ChatTurn, run_turn
from agent.memory import MEMORY_PROMPT_LIMIT, MemoryEntry, MemoryOp, apply_memory_ops, load_memory, memory_path, save_memory
from agent.preference.candidates import load_pareto_csv
from agent.preference.models import Candidate, ObjectiveSpec, PreferenceChoice
from agent.preference.service import PreferenceService
from agent.tools import build_tools
from agent.workspace import EditOp, WorkspaceSnapshot
from backend.app.application.agent_gateway import live_tool_context


class ChatMessageRequest(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)
    pose_id: str | None = None


class AgentChatRequest(BaseModel):
    messages: list[ChatMessageRequest] = Field(min_length=1)
    snapshot: WorkspaceSnapshot


class MemoryWriteRequest(BaseModel):
    scene_name: str = Field(min_length=1)
    ops: list[MemoryOp] = Field(min_length=1)


class PreferenceCandidateRequest(BaseModel):
    candidate_id: str = Field(min_length=1)
    objectives: dict[str, float]
    variables: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)


class PreferenceChoiceRequest(BaseModel):
    scene_id: str = Field(min_length=1)
    experiment_id: str | None = None
    chosen_id: str = Field(min_length=1)
    reason: str = ""
    candidates: list[PreferenceCandidateRequest] = Field(min_length=1)


class PreferenceModelRequest(BaseModel):
    experiment_id: str = Field(min_length=1)
    objective_names: list[str] = Field(min_length=1)
    objective_directions: dict[str, Literal["min", "max"]] = Field(default_factory=dict)


class PreferenceRecommendationRequest(PreferenceModelRequest):
    top_k: int = Field(default=5, ge=1, le=20)


def router() -> APIRouter:
    api = APIRouter(prefix="/api/v1")

    @api.get("/agent/ops")
    async def agent_ops() -> dict:
        return TypeAdapter(EditOp).json_schema()

    @api.get("/agent/memory")
    async def agent_memory() -> dict:
        return _memory_payload(_read_memory())

    @api.post("/agent/memory")
    async def agent_memory_write(payload: MemoryWriteRequest) -> dict:
        path = memory_path()
        try:
            entries = apply_memory_ops(_read_memory(), list(payload.ops), payload.scene_name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "memory_op_invalid", "message": str(exc)}) from exc
        save_memory(path, entries)
        return _memory_payload(entries)

    @api.get("/agent/preferences/history")
    async def preference_history() -> dict:
        service = PreferenceService()
        return {
            "items": [choice.to_dict() for choice in service.choices()],
            "count": len(service.choices()),
        }

    @api.get("/agent/preferences/model")
    async def preference_model() -> dict:
        return PreferenceService().model_summary()

    @api.post("/agent/preferences/choices")
    async def preference_choice(payload: PreferenceChoiceRequest) -> dict:
        candidates = tuple(
            Candidate(
                candidate_id=item.candidate_id,
                objectives=item.objectives,
                variables=item.variables,
                metadata=item.metadata,
            )
            for item in payload.candidates
        )
        choice = PreferenceChoice(
            scene_id=payload.scene_id,
            experiment_id=payload.experiment_id,
            chosen_id=payload.chosen_id,
            reason=payload.reason,
            candidates=candidates,
        )
        return PreferenceService().record_choice(choice)

    @api.post("/agent/preferences/model")
    async def fit_preference_model(payload: PreferenceModelRequest, request: Request) -> dict:
        specs = _preference_specs(payload)
        try:
            path, _ = request.app.state.experiment_catalog.resolve_artifact(
                payload.experiment_id, "pareto_solutions.csv"
            )
            candidates = await asyncio.to_thread(
                load_pareto_csv, path, [spec.name for spec in specs]
            )
            return await asyncio.to_thread(
                PreferenceService().fit_model, candidates, specs
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=422, detail={"code": "preference_model_invalid", "message": str(exc)}) from exc

    @api.post("/agent/preferences/recommendations")
    async def preference_recommendations(
        payload: PreferenceRecommendationRequest, request: Request
    ) -> dict:
        specs = _preference_specs(payload)
        try:
            path, _ = request.app.state.experiment_catalog.resolve_artifact(
                payload.experiment_id, "pareto_solutions.csv"
            )
            return await asyncio.to_thread(
                PreferenceService().recommend_from_csv,
                path,
                specs,
                top_k=payload.top_k,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=422, detail={"code": "preference_recommendation_invalid", "message": str(exc)}) from exc

    @api.post("/agent/chat")
    async def agent_chat(payload: AgentChatRequest, request: Request) -> StreamingResponse:
        pose_ids = {pose.id for pose in payload.snapshot.poses}
        for message in payload.messages:
            if message.pose_id is not None and message.pose_id not in pose_ids:
                raise HTTPException(
                    status_code=422,
                    detail={"code": "attached_pose_unknown", "message": f"附上的方案不在当前工作区：{message.pose_id}"},
                )
        try:
            config = AgentConfig.from_env()
        except AgentNotConfigured as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "agent_not_configured", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "agent_config_invalid", "message": str(exc)},
            ) from exc
        memory = _read_memory()
        context = live_tool_context(
            payload.snapshot,
            request.app.state.experiment_catalog,
            request.app.state.job_service.registry,
            memory,
        )
        model = OpenAICompatModel(config)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        def emit(text: str) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, _ndjson({"type": "delta", "text": text}))

        def work() -> None:
            try:
                reply = run_turn(
                    model,
                    build_tools(context),
                    [ChatTurn(message.role, message.content, message.pose_id) for message in payload.messages],
                    payload.snapshot,
                    config.max_tool_rounds,
                    on_delta=emit,
                    memory=memory,
                )
                loop.call_soon_threadsafe(queue.put_nowait, _ndjson({"type": "done", "reply": reply.model_dump(mode="json")}))
            except RuntimeError as exc:
                loop.call_soon_threadsafe(queue.put_nowait, _ndjson({"type": "error", "message": str(exc)}))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        task = asyncio.create_task(asyncio.to_thread(work))

        async def generate():
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
            await task

        return StreamingResponse(
            generate(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return api


def _read_memory() -> list[MemoryEntry]:
    try:
        return load_memory(memory_path())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "memory_file_invalid", "message": str(exc)}) from exc


def _preference_specs(payload: PreferenceModelRequest) -> list[ObjectiveSpec]:
    if len(set(payload.objective_names)) != len(payload.objective_names):
        raise HTTPException(status_code=422, detail={"code": "duplicate_objective", "message": "目标名称不能重复"})
    try:
        return [
            ObjectiveSpec(name, payload.objective_directions.get(name, "min"))
            for name in payload.objective_names
        ]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "objective_invalid", "message": str(exc)}) from exc


def _memory_payload(entries: list[MemoryEntry]) -> dict:
    return {"entries": [entry.model_dump(mode="json") for entry in entries], "prompt_limit": MEMORY_PROMPT_LIMIT}


def _ndjson(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode()
