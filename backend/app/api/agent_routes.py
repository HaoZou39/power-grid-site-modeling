"""HTTP entry for one assistant turn. The route does not apply edits."""

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
from agent.tools import build_tools
from agent.workspace import EditOp, WorkspaceSnapshot
from backend.app.application.agent_gateway import live_tool_context


class ChatMessageRequest(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class AgentChatRequest(BaseModel):
    messages: list[ChatMessageRequest] = Field(min_length=1)
    snapshot: WorkspaceSnapshot


def router() -> APIRouter:
    api = APIRouter(prefix="/api/v1")

    @api.get("/agent/ops")
    async def agent_ops() -> dict:
        return TypeAdapter(EditOp).json_schema()

    @api.post("/agent/chat")
    async def agent_chat(payload: AgentChatRequest, request: Request) -> StreamingResponse:
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
        context = live_tool_context(
            payload.snapshot,
            request.app.state.experiment_catalog,
            request.app.state.job_service.registry,
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
                    [ChatTurn(message.role, message.content) for message in payload.messages],
                    payload.snapshot,
                    config.max_tool_rounds,
                    on_delta=emit,
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


def _ndjson(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode()
