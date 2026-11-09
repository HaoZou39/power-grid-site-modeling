"""Personal planning workspace metadata. These routes do not write a public scene."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.access import can_read_owned
from backend.app.infrastructure.workspace_repository import (
    PlanningWorkspace,
    WorkspaceRepository,
    clean_display_name,
)

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_scene_id: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=80)


class WorkspaceRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=80)


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    owner_id: str
    base_scene_id: str
    base_frame_id: str
    base_revision: str
    workspace_revision: str
    display_name: str
    created_at: str
    updated_at: str
    base_status: Literal["current", "changed", "missing"]

    @classmethod
    def from_record(cls, record: PlanningWorkspace, base_status: str) -> "WorkspaceResponse":
        body = {name: getattr(record, name) for name in (
            "workspace_id", "owner_id", "base_scene_id", "base_frame_id", "base_revision",
            "workspace_revision", "display_name", "created_at", "updated_at",
        )}
        return cls(**body, base_status=base_status)


class WorkspaceDeleted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    deleted: bool


def _repository(request: Request) -> WorkspaceRepository:
    return request.app.state.workspace_repository


def _actor(request: Request):
    actor = getattr(request.state, "actor", None)
    if actor is None:
        raise HTTPException(status_code=401, detail={"code": "unauthenticated", "message": "请先登录"})
    return actor


def _name_or_422(name: str) -> str:
    try:
        return clean_display_name(name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "workspace_name_invalid", "message": str(exc)}) from exc


def _bound_scene(scene_id: str):
    """Resolve a built scene. The caller keeps the write lock until the workspace row is inserted."""
    from experiments.scene_store import scene_directory, scenes_root

    try:
        path = scene_directory(scenes_root(), scene_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "scene_invalid", "message": str(exc)}) from exc
    return path


def _version_of(path) -> tuple[str, str]:
    from experiments.scene_store import missing_scene_files
    from experiments.scene_version import scene_data_version

    if not path.is_dir() or missing_scene_files(path):
        raise HTTPException(
            status_code=404,
            detail={"code": "scene_not_ready", "message": "公共场景不存在或尚未完成数据构建"},
        )
    version = scene_data_version(path)
    frame_id = version.get("frame_id")
    revision = version.get("scene_revision")
    if not frame_id or not revision:
        raise HTTPException(
            status_code=422,
            detail={"code": "scene_version_unavailable", "message": "公共场景没有可读的网格或修订"},
        )
    return str(frame_id), str(revision)


def base_status(record: PlanningWorkspace) -> Literal["current", "changed", "missing"]:
    from experiments.scene_lock import scene_write_lock
    from experiments.scene_store import missing_scene_files, scene_directory, scenes_root
    from experiments.scene_version import scene_data_version

    try:
        path = scene_directory(scenes_root(), record.base_scene_id)
    except ValueError:
        return "missing"
    if not path.is_dir():
        return "missing"
    with scene_write_lock(record.base_scene_id, path.parent, blocking=True):
        if not path.is_dir() or missing_scene_files(path):
            return "missing"
        version = scene_data_version(path)
        frame_id = version.get("frame_id")
        revision = version.get("scene_revision")
        if not frame_id or not revision:
            return "missing"
        if frame_id != record.base_frame_id or revision != record.base_revision:
            return "changed"
        return "current"


def _visible(request: Request, workspace_id: str) -> PlanningWorkspace:
    record = _repository(request).get(workspace_id)
    actor = _actor(request)
    if record is None or record.deleted_at is not None or not can_read_owned(
        record.owner_id, actor, kind="workspace", resource_id=workspace_id
    ):
        raise HTTPException(status_code=404, detail={"code": "workspace_not_found", "message": "工作区不存在"})
    return record


@router.get("", response_model=list[WorkspaceResponse])
def list_workspaces(
    request: Request,
    base_scene_id: str | None = None,
    owner_id: str | None = Query(default=None),
) -> list[WorkspaceResponse]:
    actor = _actor(request)
    if owner_id is not None and not actor.is_admin:
        raise HTTPException(status_code=403, detail={"code": "admin_required", "message": "不能查看其他用户的工作区"})
    if owner_id is not None and not owner_id.strip():
        raise HTTPException(status_code=422, detail={"code": "owner_filter_invalid", "message": "要查看的用户不能为空"})
    target = actor.id if owner_id is None else owner_id
    return [
        WorkspaceResponse.from_record(record, base_status(record))
        for record in _repository(request).list_active(target, base_scene_id)
    ]


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(payload: WorkspaceCreate, request: Request) -> WorkspaceResponse:
    from experiments.scene_lock import scene_write_lock

    owner_id = _actor(request).id
    name = _name_or_422(payload.display_name)
    path = _bound_scene(payload.base_scene_id)
    with scene_write_lock(path.name, path.parent, blocking=True):
        frame_id, revision = _version_of(path)
        record = _repository(request).insert(
            owner_id=owner_id,
            base_scene_id=path.name,
            base_frame_id=frame_id,
            base_revision=revision,
            display_name=name,
        )
    return WorkspaceResponse.from_record(record, base_status(record))


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(workspace_id: str, request: Request) -> WorkspaceResponse:
    record = _visible(request, workspace_id)
    return WorkspaceResponse.from_record(record, base_status(record))


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
def rename_workspace(workspace_id: str, payload: WorkspaceRename, request: Request) -> WorkspaceResponse:
    actor = _actor(request)
    name = _name_or_422(payload.display_name)
    updated = _repository(request).rename(workspace_id, actor.id, name)
    if updated is None:
        raise HTTPException(status_code=404, detail={"code": "workspace_not_found", "message": "工作区不存在"})
    return WorkspaceResponse.from_record(updated, base_status(updated))


@router.delete("/{workspace_id}", response_model=WorkspaceDeleted)
def delete_workspace(workspace_id: str, request: Request) -> WorkspaceDeleted:
    deleted = _repository(request).soft_delete(workspace_id, _actor(request).id)
    if deleted is None:
        raise HTTPException(status_code=404, detail={"code": "workspace_not_found", "message": "工作区不存在"})
    return WorkspaceDeleted(workspace_id=deleted.workspace_id, deleted=True)
