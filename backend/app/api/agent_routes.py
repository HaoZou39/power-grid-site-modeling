"""HTTP entry for one assistant turn. The route does not apply edits."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, TypeAdapter

from agent.config import AgentConfig, AgentNotConfigured
from agent.llm import OpenAICompatModel
from agent.loop import AgentReply, ChatTurn, run_turn
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

    @api.post("/agent/chat", response_model=AgentReply)
    async def agent_chat(payload: AgentChatRequest, request: Request) -> AgentReply:
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
        try:
            return await asyncio.to_thread(
                run_turn,
                model,
                build_tools(context),
                [ChatTurn(message.role, message.content) for message in payload.messages],
                payload.snapshot,
                config.max_tool_rounds,
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "agent_upstream_failed", "message": str(exc)},
            ) from exc

    return api
