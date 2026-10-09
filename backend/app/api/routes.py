from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.app.application.service import JobService
from backend.app.domain.plugins import PluginError


class JobCreateRequest(BaseModel):
    plugin_id: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


def router() -> APIRouter:
    api = APIRouter(prefix="/api/v1")

    def service(request: Request) -> JobService:
        return request.app.state.job_service

    @api.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "site-modeling-api", "version": "0.1.0"}

    @api.get("/plugins")
    def plugins(request: Request) -> dict[str, Any]:
        return {"items": service(request).list_plugins()}

    @api.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
    def create_job(payload: JobCreateRequest, request: Request) -> dict[str, Any]:
        try:
            record = service(request).create_job(payload.plugin_id, payload.config)
        except PluginError as exc:
            raise HTTPException(status_code=400, detail={"code": "invalid_plugin_or_config", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "invalid_config", "message": str(exc)}) from exc
        return record.to_dict()

    @api.get("/jobs/{job_id}")
    def get_job(job_id: str, request: Request) -> dict[str, Any]:
        record = service(request).get_job(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": job_id})
        return record.to_dict()

    @api.get("/jobs/{job_id}/result")
    def get_result(job_id: str, request: Request) -> dict[str, Any]:
        record = service(request).get_job(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": job_id})
        if record.result is None:
            raise HTTPException(status_code=409, detail={"code": "result_not_ready", "message": record.status.value})
        return record.result

    return api
