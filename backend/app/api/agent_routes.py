"""HTTP entry for one assistant turn, the confirmed memory file and the user's scheme choices. The chat route does not apply edits."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Annotated, Literal, Union

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from agent.config import AgentConfig, AgentNotConfigured
from agent.llm import OpenAICompatModel
from agent.loop import AgentReply, ChatTurn, run_turn
from agent.memory import MEMORY_PROMPT_LIMIT, MemoryEntry, MemoryOp, apply_memory_ops, clear_memory, load_memory, memory_path, save_memory
from backend.app.software_update import UpdateRejected
from agent.settings import (
    MemoryDisabledError,
    SettingsFieldError,
    disable_memory_and_clear,
    enable_memory,
    memory_enabled,
    memory_snapshot,
    mutate_memory,
    read_public_settings,
    update_model_config,
)
from agent.preference.store import (
    ChoiceInput,
    PreferenceChoice,
    PreferenceDefaults,
    append_choice,
    defaults_path,
    load_choices,
    load_defaults,
    preference_path,
    save_defaults,
)
from agent.tools import build_tools
from agent.workspace import EditOp, Proposal, WorkspaceSnapshot
_log = logging.getLogger("uvicorn.error")
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


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UpdateModelRequest(_StrictRequest):
    action: Literal["update_model"]
    password: str = Field(default="", repr=False)
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_key: str | None = None
    clear_api_key: bool = False


class EnableMemoryRequest(_StrictRequest):
    action: Literal["enable_memory"]


class DisableMemoryRequest(_StrictRequest):
    action: Literal["disable_memory_and_clear"]


AgentSettingsRequest = Annotated[
    Union[UpdateModelRequest, EnableMemoryRequest, DisableMemoryRequest],
    Field(discriminator="action"),
]


def router() -> APIRouter:
    api = APIRouter(prefix="/api/v1")

    @api.get("/agent/ops")
    async def agent_ops() -> dict:
        return TypeAdapter(EditOp).json_schema()

    @api.get("/agent/settings")
    async def agent_settings() -> dict:
        try:
            return read_public_settings()
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "agent_settings_invalid", "message": str(exc)},
            ) from exc

    @api.put("/agent/settings")
    async def agent_settings_write(payload: AgentSettingsRequest) -> dict:
        try:
            if isinstance(payload, UpdateModelRequest):
                from backend.app.software_update import verify_admin_password
                verify_admin_password(payload.password, purpose="settings")
                update_model_config(
                    base_url=payload.base_url,
                    model=payload.model,
                    api_key=payload.api_key,
                    clear_api_key=payload.clear_api_key,
                )
            elif isinstance(payload, EnableMemoryRequest):
                enable_memory()
            else:
                disable_memory_and_clear(lambda: clear_memory(memory_path()))
            return read_public_settings()
        except UpdateRejected as exc:
            raise HTTPException(status_code=exc.status, detail={"code":exc.code, "message":str(exc)}) from exc
        except SettingsFieldError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "agent_settings_invalid", "field": exc.field, "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "agent_settings_invalid", "message": str(exc)},
            ) from exc
        except OSError as exc:
            if isinstance(payload, UpdateModelRequest):
                raise HTTPException(
                    status_code=500,
                    detail={"code": "model_config_write_failed", "message": "模型配置没有写入，请重试。"},
                ) from exc
            raise HTTPException(
                status_code=500,
                detail={"code": "memory_clear_failed", "message": "长期记忆已关闭，但文字记忆清理失败，请重试。"},
            ) from exc

    @api.get("/agent/memory")
    async def agent_memory() -> dict:
        enabled, entries = _memory_snapshot()
        return _memory_payload(entries if enabled and entries is not None else [])

    @api.post("/agent/memory")
    async def agent_memory_write(payload: MemoryWriteRequest) -> dict:
        try:
            entries = mutate_memory(lambda: _write_memory(payload))
        except MemoryDisabledError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "memory_disabled", "message": "长期记忆未开启，无法写入。"},
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "memory_op_invalid", "message": str(exc)}) from exc
        return _memory_payload(entries)

    @api.get("/agent/preferences")
    async def preference_state() -> dict:
        return _preference_payload()

    @api.put("/agent/preferences/defaults")
    async def preference_defaults(payload: PreferenceDefaults) -> dict:
        save_defaults(defaults_path(), payload)
        return _preference_payload()

    @api.post("/agent/preferences/choices")
    async def preference_choice(payload: ChoiceInput) -> dict:
        path = preference_path()
        count = len(_read_preference(load_choices, path))
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
        memory_is_enabled, memory_items = _memory_snapshot()
        memory = memory_items or []
        context = live_tool_context(
            payload.snapshot,
            request.app.state.experiment_catalog,
            request.app.state.job_service.registry,
            memory,
            memory_enabled=memory_is_enabled,
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
                    memory_enabled=memory_is_enabled,
                )
                reply = _remove_disabled_memory(reply)
                tools = " ".join(f"{item.name}:{'ok' if item.ok else 'error'}" for item in reply.tool_trace)
                _log.info("agent turn tools=[%s] recommended=%s proposal=%s", tools, reply.recommended, reply.proposal is not None)
                loop.call_soon_threadsafe(queue.put_nowait, _ndjson({"type": "done", "reply": reply.model_dump(mode="json")}))
            except (RuntimeError, ValueError) as exc:
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


def _memory_snapshot() -> tuple[bool, list[MemoryEntry] | None]:
    try:
        return memory_snapshot(lambda: load_memory(memory_path()))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "memory_file_invalid", "message": str(exc)}) from exc


def _write_memory(payload: MemoryWriteRequest) -> list[MemoryEntry]:
    path = memory_path()
    entries = apply_memory_ops(load_memory(path), list(payload.ops), payload.scene_name)
    save_memory(path, entries)
    return entries


def _remove_disabled_memory(reply: AgentReply) -> AgentReply:
    proposal = reply.proposal
    if proposal is None or not proposal.memory or memory_enabled():
        return reply
    if proposal.ops:
        safe = Proposal.model_validate({
            "rationale": proposal.rationale + "；长期记忆已关闭，未包含记忆改动。",
            "ops": [op.model_dump(mode="json") for op in proposal.ops],
            "memory": [],
        })
        return reply.model_copy(update={"proposal": safe})
    return reply.model_copy(update={
        "message": "长期记忆未开启，无法保存这条信息。你可以在「设置 → AI 助手设置」中开启。",
        "proposal": None,
    })


def _read_preference(load, path):
    try:
        return load(path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "preference_file_invalid", "message": str(exc)}) from exc


def _preference_payload() -> dict:
    defaults = _read_preference(load_defaults, defaults_path())
    return {
        "defaults": defaults.model_dump() if defaults else None,
        "choice_count": len(_read_preference(load_choices, preference_path())),
    }


def _memory_payload(entries: list[MemoryEntry]) -> dict:
    return {"entries": [entry.model_dump(mode="json") for entry in entries], "prompt_limit": MEMORY_PROMPT_LIMIT}


def _ndjson(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode()
