"""Personal planning workspace metadata and its current plan. These routes do not write a public scene."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.access import can_read_owned
from backend.app.domain.planning_content import (
    PLAN_BYTE_LIMIT,
    PlanInvalid,
    PlanNotWritable,
    PlanRevisionConflict,
    PlanTooLarge,
    PlanningDocument,
    RoutingPlan,
    SitePlan,
    parse_stored_plan,
)
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


class PlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    workspace_revision: str
    base_status: Literal["current", "changed", "missing"]
    schema_version: Literal[1]
    site: SitePlan | None
    routing: RoutingPlan | None


class SitePlanWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_workspace_revision: str = Field(min_length=1, max_length=80)
    site: SitePlan | None


class RoutingPlanWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_workspace_revision: str = Field(min_length=1, max_length=80)
    routing: RoutingPlan | None


class PlanSaved(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_revision: str
    changed: bool


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


def _limit_plan_body(request: Request) -> None:
    raw = request.headers.get("content-length")
    if raw is not None and raw.isdigit() and int(raw) > PLAN_BYTE_LIMIT:
        raise HTTPException(status_code=413, detail={"code": "plan_too_large", "message": "规划配置超过大小限制"})


def _owned(request: Request, workspace_id: str) -> PlanningWorkspace:
    record = _repository(request).get(workspace_id)
    actor = _actor(request)
    if record is None or record.deleted_at is not None or record.owner_id != actor.id:
        raise HTTPException(status_code=404, detail={"code": "workspace_not_found", "message": "工作区不存在"})
    return record


@contextmanager
def _current_base(record: PlanningWorkspace) -> Iterator[None]:
    """Hold the scene lock across the version check and the plan update."""
    from experiments.scene_lock import scene_write_lock
    from experiments.scene_store import scene_directory, scenes_root

    try:
        path = scene_directory(scenes_root(), record.base_scene_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "workspace_base_missing", "message": "公共场景已不可用，不能保存规划配置"},
        ) from exc
    if not path.is_dir():
        raise HTTPException(
            status_code=409,
            detail={"code": "workspace_base_missing", "message": "公共场景已不存在，不能保存规划配置"},
        )
    with scene_write_lock(path.name, path.parent, blocking=True):
        state = base_status(record)
        if state == "missing":
            raise HTTPException(
                status_code=409,
                detail={"code": "workspace_base_missing", "message": "公共场景已不存在，不能保存规划配置"},
            )
        if state == "changed":
            raise HTTPException(
                status_code=409,
                detail={"code": "workspace_base_changed", "message": "公共场景版本已变化，不能把旧配置写到新版本上"},
            )
        yield


def _save_plan(request: Request, workspace_id: str, side: str, expected: str, value: dict | None) -> PlanSaved:
    record = _owned(request, workspace_id)
    try:
        with _current_base(record):
            updated, changed = _repository(request).save_plan_side(
                workspace_id, record.owner_id, expected, side, value,
            )
    except PlanRevisionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "workspace_revision_conflict", "message": "工作区规划配置已被其他保存更新"},
        ) from exc
    except PlanNotWritable as exc:
        raise HTTPException(status_code=404, detail={"code": "workspace_not_found", "message": "工作区不存在"}) from exc
    except PlanTooLarge as exc:
        raise HTTPException(status_code=413, detail={"code": "plan_too_large", "message": "规划配置超过大小限制"}) from exc
    except PlanInvalid as exc:
        raise HTTPException(status_code=422, detail={"code": "plan_invalid", "message": str(exc)}) from exc
    return PlanSaved(workspace_revision=updated.workspace_revision, changed=changed)


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


@router.get("/{workspace_id}/plan", response_model=PlanResponse)
def get_plan(workspace_id: str, request: Request) -> PlanResponse:
    record = _visible(request, workspace_id)
    document = _stored_plan(record)
    return PlanResponse(
        workspace_id=record.workspace_id,
        workspace_revision=record.workspace_revision,
        base_status=base_status(record),
        schema_version=document.schema_version,
        site=document.site,
        routing=document.routing,
    )


@router.put("/{workspace_id}/plan/site", response_model=PlanSaved, dependencies=[Depends(_limit_plan_body)])
def save_site_plan(workspace_id: str, payload: SitePlanWrite, request: Request) -> PlanSaved:
    value = None if payload.site is None else payload.site.model_dump(mode="json")
    return _save_plan(request, workspace_id, "site", payload.expected_workspace_revision, value)


@router.put("/{workspace_id}/plan/routing", response_model=PlanSaved, dependencies=[Depends(_limit_plan_body)])
def save_routing_plan(workspace_id: str, payload: RoutingPlanWrite, request: Request) -> PlanSaved:
    value = None if payload.routing is None else payload.routing.model_dump(mode="json")
    return _save_plan(request, workspace_id, "routing", payload.expected_workspace_revision, value)


def _stored_plan(record: PlanningWorkspace) -> PlanningDocument:
    try:
        return parse_stored_plan(record.content_json)
    except PlanInvalid as exc:
        raise HTTPException(status_code=422, detail={"code": "plan_invalid", "message": str(exc)}) from exc


@router.delete("/{workspace_id}", response_model=WorkspaceDeleted)
def delete_workspace(workspace_id: str, request: Request) -> WorkspaceDeleted:
    deleted = _repository(request).soft_delete(workspace_id, _actor(request).id)
    if deleted is None:
        raise HTTPException(status_code=404, detail={"code": "workspace_not_found", "message": "工作区不存在"})
    return WorkspaceDeleted(workspace_id=deleted.workspace_id, deleted=True)
