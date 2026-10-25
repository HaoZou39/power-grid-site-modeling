from __future__ import annotations

from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from backend.app.infrastructure.favorite_repository import (
    FavoritePoint,
    FavoritePointRepository,
)

router = APIRouter(prefix="/api/v1/scenes/{scene_id}/favorites", tags=["favorites"])


class FavoritePointCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    width_m: float = Field(gt=0, allow_inf_nan=False)
    height_m: float = Field(gt=0, allow_inf_nan=False)
    bearing_deg: float = Field(ge=0, lt=360, allow_inf_nan=False)


class FavoritePointUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    bearing_deg: float = Field(ge=0, lt=360, allow_inf_nan=False)


class FavoritePointResponse(BaseModel):
    id: str
    scene_id: str
    longitude: float
    latitude: float
    width_m: float
    height_m: float
    bearing_deg: float
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, favorite: FavoritePoint) -> "FavoritePointResponse":
        return cls(**favorite.__dict__)


def _validate_scene(scene_id: str) -> None:
    from experiments.scene_store import SCENE_SOURCES, missing_scene_files, scene_directory, scenes_root

    try:
        path = scene_directory(scenes_root(), scene_id)
        if scene_id not in SCENE_SOURCES and missing_scene_files(path):
            raise ValueError(f"场景 {scene_id} 不存在或尚未完成数据构建")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "scene_not_found", "message": str(exc)},
        ) from exc


@contextmanager
def _writable_scene(scene_id: str):
    from experiments.scene_store import scene_directory, scenes_root, ensure_scene_writable
    from experiments.scene_lock import scene_write_lock
    _validate_scene(scene_id)
    path = scene_directory(scenes_root(None), scene_id)
    with scene_write_lock(scene_id, path.parent):
        try:
            ensure_scene_writable(path)
        except ValueError as exc:
            raise HTTPException(409, detail={"code":"scene_read_only", "message":str(exc)}) from exc
        yield


def _repository(request: Request) -> FavoritePointRepository:
    return request.app.state.favorite_point_repository


@router.get("", response_model=list[FavoritePointResponse])
def list_favorites(scene_id: str, request: Request) -> list[FavoritePointResponse]:
    _validate_scene(scene_id)
    return [
        FavoritePointResponse.from_domain(favorite)
        for favorite in _repository(request).list_for_scene(scene_id)
    ]


@router.post("", response_model=FavoritePointResponse, status_code=status.HTTP_201_CREATED)
def create_favorite(
    scene_id: str,
    payload: FavoritePointCreate,
    request: Request,
) -> FavoritePointResponse:
    with _writable_scene(scene_id):
        favorite = _repository(request).create(scene_id, **payload.model_dump())
    return FavoritePointResponse.from_domain(favorite)


@router.put("/{favorite_id}", response_model=FavoritePointResponse)
def update_favorite(
    scene_id: str,
    favorite_id: str,
    payload: FavoritePointUpdate,
    request: Request,
) -> FavoritePointResponse:
    with _writable_scene(scene_id):
        favorite = _repository(request).update(
            scene_id, favorite_id, **payload.model_dump()
        )
    if favorite is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "favorite_not_found", "message": favorite_id},
        )
    return FavoritePointResponse.from_domain(favorite)


@router.delete("/{favorite_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_favorite(scene_id: str, favorite_id: str, request: Request) -> None:
    with _writable_scene(scene_id):
        deleted = _repository(request).delete(scene_id, favorite_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "favorite_not_found", "message": favorite_id},
        )
