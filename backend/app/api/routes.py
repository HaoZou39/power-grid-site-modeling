"""HTTP contract for health, plugins, jobs, and experiment outputs."""

from __future__ import annotations

import asyncio
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.application.service import JobService
from backend.app.domain.plugins import PluginError
from backend.app.software_update import UpdateRejected, begin_update, read_status
from backend.app.infrastructure.experiment_catalog import (
    ExperimentCatalog,
    ExperimentNotFound,
    media_type_for,
)


class FarmlandConfirmRequest(BaseModel):
    token: str = Field(min_length=32, max_length=32)


class JobCreateRequest(BaseModel):
    plugin_id: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class PluginSpecResponse(BaseModel):
    id: str
    version: str
    kind: str
    name: str
    description: str
    config_schema: dict[str, Any]


class PluginCatalogResponse(BaseModel):
    items: list[PluginSpecResponse]


class JobResponse(BaseModel):
    job_id: str
    plugin_id: str
    plugin_version: str
    config: dict[str, Any]
    status: str
    progress: float
    stage: str
    message: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: str
    updated_at: str


class ArtifactResponse(BaseModel):
    id: str
    name: str
    kind: str
    media_type: str
    size_bytes: int
    url: str


class SceneResponse(BaseModel):
    id: str
    title: str
    ready: bool
    missing: list[str]
    frame: dict[str, Any] | None = None
    source_site_id: str | None = None


class LandusePatchRequest(BaseModel):
    x: float
    y: float
    max_cells: int = Field(default=8000, ge=1)


class LanduseEditRequest(BaseModel):
    class_id: Literal[1, 2, 3, 5]
    points: list[tuple[float, float]] = Field(min_length=3, max_length=2000)


class LanduseEditUpdateRequest(BaseModel):
    points: list[tuple[float, float]] = Field(min_length=3, max_length=2000)


class ZoneRequest(BaseModel):
    points: list[tuple[float, float]] = Field(min_length=3)


class SiteReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    theta: float = 0
    rect_w_m: float = Field(default=77, gt=0)
    rect_h_m: float = Field(default=51.5, gt=0)
    origin_x: float | None = None
    origin_y: float | None = None
    mountain_policy: Literal["blocked", "allowed"] | None = None
    field_policy: Literal["blocked", "allowed", "costly"] | None = None
    field_cost: float | None = Field(default=None, gt=0, le=1)
    exclusion_zones: list[ZoneRequest] | None = None
    feasible_zones: list[ZoneRequest] | None = None
    diagonal_access: bool = False
    road_setback_m: float = Field(default=5.0, ge=0)
    water_setback_m: float = Field(default=5.0, ge=0)

    @model_validator(mode="after")
    def validate_constraint_set(self) -> "SiteReportRequest":
        values = (
            self.mountain_policy,
            self.field_policy,
            self.field_cost,
            self.exclusion_zones,
            self.feasible_zones,
        )
        if any(value is not None for value in values) and not all(value is not None for value in values):
            raise ValueError("site-report constraint fields must be supplied together")
        return self


class PoseRequest(BaseModel):
    x: float
    y: float
    theta: float


class PoseObjectivesRequest(BaseModel):
    """The search payload of the current edit plus decoded poses in 1 m local meters."""

    model_config = ConfigDict(extra="forbid")

    rect_w_m: float = Field(gt=0)
    rect_h_m: float = Field(gt=0)
    mountain_policy: Literal["blocked", "allowed"]
    field_policy: Literal["blocked", "allowed", "costly"]
    field_cost: float = Field(gt=0, le=1)
    exclusion_zones: list[ZoneRequest]
    feasible_zones: list[ZoneRequest]
    include_demand: bool
    diagonal_access: bool = False
    road_setback_m: float = Field(default=5.0, ge=0)
    water_setback_m: float = Field(default=5.0, ge=0)
    origin_x: float | None = None
    origin_y: float | None = None
    poses: list[PoseRequest] = Field(min_length=1, max_length=200)


class ConstructionFeasibilityRequest(BaseModel):
    """Current workspace rules needed to compose the hard-constraint grid."""

    model_config = ConfigDict(extra="forbid")

    mountain_policy: Literal["blocked", "allowed"]
    field_policy: Literal["blocked", "allowed", "costly"]
    field_cost: float = Field(gt=0, le=1)
    exclusion_zones: list[ZoneRequest]
    feasible_zones: list[ZoneRequest]
    road_setback_m: float = Field(default=5.0, ge=0)
    water_setback_m: float = Field(default=5.0, ge=0)


class ExperimentResponse(BaseModel):
    id: str
    name: str
    algorithm: str
    summary: dict[str, Any]
    artifacts: list[ArtifactResponse]
    modified_at: str


class SoftwareUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str


class SoftwareUpdateAccepted(BaseModel):
    id: str
    message: str


class SoftwareUpdateStatus(BaseModel):
    configured: bool
    updating: bool
    id: str
    result: Literal["succeeded", "rolled_back", "failed"] | None
    message: str
    commit: str


def _artifact_url(experiment_id: str, artifact_id: str) -> str:
    return (
        "/api/v1/experiments/"
        f"{quote(experiment_id, safe='')}/artifacts/{quote(artifact_id, safe='')}"
    )


def router() -> APIRouter:
    """Create the router and keep request handlers thin.

    Handlers translate HTTP data into application calls. They do not contain
    algorithm or persistence logic.
    """
    api = APIRouter(prefix="/api/v1")

    def service(request: Request) -> JobService:
        return request.app.state.job_service

    def experiments(request: Request) -> ExperimentCatalog:
        return request.app.state.experiment_catalog

    @api.get("/scenes", response_model=list[SceneResponse])
    async def list_scenes() -> list[dict[str, Any]]:
        from experiments.scene_store import list_scenes as read_scenes

        return await asyncio.to_thread(read_scenes)

    @api.get("/scenes/{scene_id}/landuse-overlay/{layer}")
    async def scene_landuse_overlay(scene_id: str, layer: str) -> FileResponse:
        from experiments.scene_store import landuse_overlay_path

        try:
            path = await asyncio.to_thread(landuse_overlay_path, scene_id, layer)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "scene_overlay_missing", "message": str(exc)},
            ) from exc
        return FileResponse(
            path,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @api.get("/scenes/{scene_id}/obstacle-overlay")
    async def scene_obstacle_overlay(scene_id: str) -> FileResponse:
        from experiments.scene_store import obstacle_overlay_path

        try:
            path = await asyncio.to_thread(obstacle_overlay_path, scene_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "scene_overlay_missing", "message": str(exc)},
            ) from exc
        return FileResponse(path, media_type="image/png")

    @api.get("/scenes/{scene_id}/map-layers")
    async def scene_map_layers(scene_id: str) -> dict[str, Any]:
        from experiments.scene_store import scene_layer_info

        try:
            return await asyncio.to_thread(scene_layer_info, scene_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "scene_layers_missing", "message": str(exc)},
            ) from exc

    def _scene_directory(scene_id: str):
        from experiments.scene_store import scene_directory, scenes_root

        try:
            return scene_directory(scenes_root(None), scene_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "scene_missing", "message": str(exc)},
            ) from exc

    def _reject_busy_scene(request: Request, scene_id: str) -> None:
        names = request.app.state.job_service.repository.active_scene_names()
        if scene_id in names:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "farmland_scene_busy",
                    "message": "该场景有正在运行的构建或优化任务，结束后才能更改永久基本农田。",
                },
            )

    @api.post("/scenes/{scene_id}/protected-farmland/preview")
    async def preview_protected_farmland(scene_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
        from experiments.protected_farmland import MAX_ZIP_BYTES, FarmlandImportError, preview_zip

        directory = _scene_directory(scene_id)
        chunks: list[bytes] = []
        total = 0
        while True:
            block = await file.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > MAX_ZIP_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail={
                        "code": "farmland_import_rejected",
                        "message": f"压缩包不能超过 {MAX_ZIP_BYTES // (1024 * 1024)} MB",
                    },
                )
            chunks.append(block)
        try:
            return await asyncio.to_thread(
                preview_zip,
                directory,
                file.filename or "protected_farmland.zip",
                b"".join(chunks),
            )
        except FarmlandImportError as exc:
            raise HTTPException(
                status_code=exc.status,
                detail={"code": "farmland_import_rejected", "message": str(exc)},
            ) from exc

    @api.get("/scenes/{scene_id}/protected-farmland/preview/{token}")
    async def preview_protected_farmland_overlay(scene_id: str, token: str) -> FileResponse:
        from experiments.protected_farmland import FarmlandImportError, preview_overlay_file

        try:
            path = await asyncio.to_thread(preview_overlay_file, _scene_directory(scene_id), token)
        except FarmlandImportError as exc:
            raise HTTPException(
                status_code=exc.status,
                detail={"code": "farmland_preview_missing", "message": str(exc)},
            ) from exc
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})

    @api.post("/scenes/{scene_id}/protected-farmland/confirm")
    async def confirm_protected_farmland(
        scene_id: str,
        payload: FarmlandConfirmRequest,
        request: Request,
    ) -> dict[str, Any]:
        from experiments.protected_farmland import FarmlandImportError, commit_preview

        _reject_busy_scene(request, scene_id)
        try:
            return await asyncio.to_thread(commit_preview, _scene_directory(scene_id), payload.token)
        except FarmlandImportError as exc:
            raise HTTPException(
                status_code=exc.status,
                detail={"code": "farmland_import_rejected", "message": str(exc)},
            ) from exc

    @api.delete("/scenes/{scene_id}/protected-farmland", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_protected_farmland(scene_id: str, request: Request) -> Response:
        from experiments.protected_farmland import FarmlandImportError, delete_layer

        _reject_busy_scene(request, scene_id)
        directory = _scene_directory(scene_id)
        if not directory.is_dir():
            raise HTTPException(
                status_code=404,
                detail={"code": "scene_missing", "message": f"场景 {scene_id} 不存在"},
            )
        try:
            await asyncio.to_thread(delete_layer, directory)
        except FarmlandImportError as exc:
            raise HTTPException(
                status_code=exc.status,
                detail={"code": "farmland_import_rejected", "message": str(exc)},
            ) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @api.get("/scenes/{scene_id}/protected-farmland-overlay")
    async def protected_farmland_overlay(scene_id: str) -> FileResponse:
        from experiments.protected_farmland import overlay_file

        try:
            path = await asyncio.to_thread(overlay_file, _scene_directory(scene_id))
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "farmland_overlay_missing", "message": str(exc)},
            ) from exc
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})

    @api.get("/scenes/{scene_id}/dem-overlay")
    async def scene_dem_overlay(scene_id: str) -> FileResponse:
        from experiments.scene_store import dem_overlay_info

        try:
            path, _ = await asyncio.to_thread(dem_overlay_info, scene_id)
        except (FileNotFoundError, ValueError, OSError) as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "scene_dem_missing", "message": str(exc)},
            ) from exc
        return FileResponse(path, media_type="image/png")

    @api.get("/scenes/{scene_id}/road-segments")
    async def scene_road_segments(scene_id: str) -> dict[str, Any]:
        from experiments.scene_store import road_segments

        try:
            segments = await asyncio.to_thread(road_segments, scene_id)
        except (FileNotFoundError, ValueError, OSError) as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "scene_roads_missing", "message": str(exc)},
            ) from exc
        return {"segments": segments, "count": len(segments)}

    @api.post("/scenes/{scene_id}/landuse-patch")
    async def scene_landuse_patch(scene_id: str, payload: LandusePatchRequest) -> dict[str, Any]:
        import numpy as np

        from experiments.landuse_patch import connected_class_ring
        from experiments.scene_store import scene_directory, scenes_root

        landuse_path = scene_directory(scenes_root(None), scene_id) / "landuse_1m.npy"
        if not landuse_path.is_file():
            raise HTTPException(
                status_code=404,
                detail={"code": "scene_landuse_missing", "message": scene_id},
            )
        landuse = await asyncio.to_thread(np.load, landuse_path)
        try:
            patch = connected_class_ring(landuse, payload.x, payload.y, payload.max_cells)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "landuse_patch_rejected", "message": str(exc)},
            ) from exc
        return patch

    @api.get("/scenes/{scene_id}/landuse-edits")
    async def scene_landuse_edits(scene_id: str, response: Response) -> dict[str, Any]:
        from experiments.landuse_edits import list_landuse_edits

        response.headers["Cache-Control"] = "no-store"
        try:
            items = await asyncio.to_thread(list_landuse_edits, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "scene_landuse_missing", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "landuse_edits_invalid", "message": str(exc)},
            ) from exc
        return {"items": items}

    @api.delete("/scenes/{scene_id}/landuse-edits")
    async def clear_scene_landuse_edits(scene_id: str) -> dict[str, Any]:
        from experiments.landuse_edits import clear_landuse_edits

        try:
            items = await asyncio.to_thread(clear_landuse_edits, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "scene_landuse_missing", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "landuse_edits_invalid", "message": str(exc)},
            ) from exc
        return {"items": items}

    @api.post("/scenes/{scene_id}/landuse-edits")
    async def create_scene_landuse_edit(scene_id: str, payload: LanduseEditRequest) -> dict[str, Any]:
        from experiments.landuse_edits import create_landuse_edit

        try:
            items = await asyncio.to_thread(
                create_landuse_edit,
                scene_id,
                payload.class_id,
                payload.points,
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "scene_landuse_missing", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "landuse_edit_rejected", "message": str(exc)},
            ) from exc
        return {"items": items}

    @api.put("/scenes/{scene_id}/landuse-edits/{edit_id}")
    async def update_scene_landuse_edit(
        scene_id: str,
        edit_id: str,
        payload: LanduseEditUpdateRequest,
    ) -> dict[str, Any]:
        from experiments.landuse_edits import update_landuse_edit

        try:
            items = await asyncio.to_thread(
                update_landuse_edit,
                scene_id,
                edit_id,
                payload.points,
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "landuse_edit_missing", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "landuse_edit_rejected", "message": str(exc)},
            ) from exc
        return {"items": items}

    @api.delete("/scenes/{scene_id}/landuse-edits/{edit_id}")
    async def delete_scene_landuse_edit(scene_id: str, edit_id: str) -> dict[str, Any]:
        from experiments.landuse_edits import delete_landuse_edit

        try:
            items = await asyncio.to_thread(delete_landuse_edit, scene_id, edit_id)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "landuse_edit_missing", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "landuse_edit_rejected", "message": str(exc)},
            ) from exc
        return {"items": items}

    @api.post("/scenes/{scene_id}/site-report")
    async def scene_site_report(scene_id: str, payload: SiteReportRequest) -> dict[str, Any]:
        from experiments.scene_store import scene_directory, scenes_root
        from experiments.site_report import build_site_report

        directory = scene_directory(scenes_root(None), scene_id)
        if not (directory / "dem_1m.npy").is_file():
            raise HTTPException(status_code=404, detail={"code": "scene_dem_missing", "message": scene_id})
        origin = None
        if payload.origin_x is not None and payload.origin_y is not None:
            origin = (payload.origin_x, payload.origin_y)
        elif payload.origin_x is not None or payload.origin_y is not None:
            raise HTTPException(
                status_code=422,
                detail={"code": "origin_incomplete", "message": "进货原点需要同时给出 x 和 y"},
            )
        constraint_form = None
        if payload.field_policy is not None:
            constraint_form = payload.model_dump(
                include={
                    "mountain_policy",
                    "field_policy",
                    "field_cost",
                    "exclusion_zones",
                    "feasible_zones",
                }
            )
            if payload.diagonal_access:
                constraint_form["diagonal_access"] = True
        try:
            report = await asyncio.to_thread(
                build_site_report,
                directory,
                payload.x,
                payload.y,
                payload.theta,
                payload.rect_w_m,
                payload.rect_h_m,
                origin,
                constraint_form=constraint_form,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "site_report_rejected", "message": str(exc)},
            ) from exc
        return report

    @api.post("/scenes/{scene_id}/pose-objectives")
    async def scene_pose_objectives(scene_id: str, payload: PoseObjectivesRequest) -> dict[str, Any]:
        from experiments.launch_site_run import evaluate_form_poses

        form = {**payload.model_dump(exclude={"poses"}), "scene_name": scene_id}
        poses = [(pose.x, pose.y, pose.theta) for pose in payload.poses]
        try:
            records = await asyncio.to_thread(evaluate_form_poses, form, poses)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "pose_objectives_rejected", "message": str(exc)},
            ) from exc
        return {"items": records}

    @api.post("/scenes/{scene_id}/construction-feasibility-overlay")
    async def scene_construction_feasibility_overlay(
        scene_id: str,
        payload: ConstructionFeasibilityRequest,
    ) -> Response:
        from experiments.scene_store import construction_feasibility_png

        try:
            content = await asyncio.to_thread(
                construction_feasibility_png,
                scene_id,
                payload.model_dump(),
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "scene_landuse_missing", "message": str(exc)},
            ) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "construction_feasibility_rejected", "message": str(exc)},
            ) from exc
        return Response(
            content=content,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @api.get("/health", response_model=HealthResponse)
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "site-modeling-api", "version": "0.1.0"}

    @api.get("/plugins", response_model=PluginCatalogResponse)
    async def plugins(request: Request) -> dict[str, Any]:
        items = await asyncio.to_thread(service(request).list_plugins)
        return {"items": items}

    @api.get("/experiments", response_model=list[ExperimentResponse])
    async def list_experiments(request: Request) -> list[dict[str, Any]]:
        catalog = experiments(request)
        records = await asyncio.to_thread(catalog.list_experiments)
        return [
            {
                **record.to_dict(),
                "artifacts": [
                    {
                        **artifact.to_dict(),
                        "url": _artifact_url(record.id, artifact.id),
                    }
                    for artifact in record.artifacts
                ],
            }
            for record in records
        ]

    @api.get("/experiments/{experiment_id}", response_model=ExperimentResponse)
    async def get_experiment(experiment_id: str, request: Request) -> dict[str, Any]:
        try:
            record = await asyncio.to_thread(experiments(request).get_experiment, experiment_id)
        except ExperimentNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "experiment_not_found", "message": experiment_id},
            ) from exc
        return {
            **record.to_dict(),
            "artifacts": [
                {
                    **artifact.to_dict(),
                    "url": _artifact_url(record.id, artifact.id),
                }
                for artifact in record.artifacts
            ],
        }

    @api.delete("/experiments/{experiment_id}")
    async def delete_experiment(experiment_id: str, request: Request) -> dict[str, Any]:
        try:
            await asyncio.to_thread(experiments(request).delete_experiment, experiment_id)
        except ExperimentNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "experiment_not_found", "message": experiment_id},
            ) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail={"code": "experiment_delete_failed", "message": "结果目录不可写，无法删除。"},
            ) from exc
        return {"id": experiment_id, "deleted": True}

    @api.get("/experiments/{experiment_id}/artifacts/{artifact_id}")
    async def get_artifact(experiment_id: str, artifact_id: str, request: Request) -> FileResponse:
        try:
            path, artifact = await asyncio.to_thread(
                experiments(request).resolve_artifact, experiment_id, artifact_id
            )
        except ExperimentNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "artifact_not_found", "message": artifact_id},
            ) from exc
        return FileResponse(
            path,
            media_type=media_type_for(path),
            headers={"X-Artifact-Kind": artifact.kind},
        )

    @api.post("/jobs", status_code=status.HTTP_202_ACCEPTED, response_model=JobResponse)
    async def create_job(payload: JobCreateRequest, request: Request) -> dict[str, Any]:
        try:
            record = await asyncio.to_thread(
                service(request).create_job, payload.plugin_id, payload.config
            )
        except PluginError as exc:
            raise HTTPException(status_code=400, detail={"code": "invalid_plugin_or_config", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "invalid_config", "message": str(exc)}) from exc
        return record.to_dict()

    @api.post("/jobs/{job_id}/cancel", response_model=JobResponse)
    async def cancel_job(job_id: str, request: Request) -> dict[str, Any]:
        try:
            record = await asyncio.to_thread(service(request).cancel_job, job_id)
        except PluginError as exc:
            raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": str(exc)}) from exc
        return record.to_dict()

    @api.get("/jobs/{job_id}", response_model=JobResponse)
    async def get_job(job_id: str, request: Request) -> dict[str, Any]:
        record = await asyncio.to_thread(service(request).get_job, job_id)
        if record is None:
            raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": job_id})
        return record.to_dict()

    @api.get("/jobs/{job_id}/result")
    async def get_result(job_id: str, request: Request) -> dict[str, Any]:
        record = await asyncio.to_thread(service(request).get_job, job_id)
        if record is None:
            raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": job_id})
        if record.result is None:
            raise HTTPException(status_code=409, detail={"code": "result_not_ready", "message": record.status.value})
        return record.result

    @api.get("/software-update", response_model=SoftwareUpdateStatus)
    async def software_update_status() -> dict[str, Any]:
        return await asyncio.to_thread(read_status)

    @api.post("/software-update", status_code=status.HTTP_202_ACCEPTED, response_model=SoftwareUpdateAccepted)
    async def software_update(body: SoftwareUpdateRequest) -> dict[str, str]:
        try:
            return await asyncio.to_thread(begin_update, body.password)
        except UpdateRejected as exc:
            raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message}) from exc

    return api
