"""HTTP entry for one assistant turn, the confirmed memory file and the user's scheme choices. The chat route does not apply edits."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, TypeAdapter

from agent.config import AgentConfig, AgentNotConfigured
from agent.llm import OpenAICompatModel
from agent.loop import ChatTurn, run_turn
from agent.memory import MEMORY_PROMPT_LIMIT, MemoryEntry, MemoryOp, apply_memory_ops, load_memory, memory_path, save_memory
from agent.preference.history import ChoiceInput, PreferenceChoice, append_choice, load_choices, preference_path
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

    @api.post("/agent/preferences/choices")
    async def preference_choice(payload: ChoiceInput) -> dict:
        path = preference_path()
        try:
            count = len(load_choices(path))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "preference_file_invalid", "message": str(exc)}) from exc
        recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        append_choice(path, PreferenceChoice(**payload.model_dump(), recorded_at=recorded_at))
        return {"count": count + 1}

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


def _memory_payload(entries: list[MemoryEntry]) -> dict:
    return {"entries": [entry.model_dump(mode="json") for entry in entries], "prompt_limit": MEMORY_PROMPT_LIMIT}


def _ndjson(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode()
