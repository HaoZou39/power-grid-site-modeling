"""Submit and execute a site or routing job bound to one immutable workspace revision."""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.app.domain.jobs import JobBinding, JobRecord
from backend.app.domain.planning_content import (
    PlanContentHashMismatch,
    PlanInvalid,
    PlanningDocument,
    parse_stored_plan,
)
from backend.app.domain.plugins import PluginError, PluginResult
from backend.app.infrastructure.base_snapshot_repository import BaseSnapshotRepository
from backend.app.infrastructure.workspace_repository import PlanningWorkspace, WorkspaceRepository

logger = logging.getLogger(__name__)

_BUILD_PLUGINS = {"site.build_scene", "site.prepare_scene"}
_COMPUTE_PLUGINS = {
    "site.guided_search",
    "site.partitioned_guided_search",
    "site.cma_es",
    "site.multistart_adam",
    "routing.nsga2",
}
_SITE_RUN_FIELDS = {
    "seed",
    "device",
    "popsize",
    "generations",
    "sigma0",
    "evolution_backend",
    "evaluation_batch_size",
    "initialization",
    "partition_count",
    "max_iters",
    "restarts_per_weight",
    "starts_per_weight",
    "max_steps",
    "learning_rate",
    "init_eps",
    "objective_weights",
}
_CLIENT_BINDING_FIELDS = {
    "owner_id",
    "workspace_id",
    "workspace_revision",
    "base_scene_id",
    "base_frame_id",
    "base_revision",
    "base_snapshot_id",
    "planning_content_hash",
    "effective_config_hash",
    "snapshot_id",
    "snapshot_dir",
    "resolved_config_json",
    "snapshot_manifest_sha256",
}


class FrozenInputError(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def reject_legacy_binding(config: dict[str, Any]) -> None:
    present = sorted(_CLIENT_BINDING_FIELDS.intersection(config))
    if present:
        raise ValueError("旧的任务接口不能绑定工作区或快照：" + ", ".join(present))


def submit_workspace_job(
    service,
    workspaces: WorkspaceRepository,
    workspace: PlanningWorkspace,
    *,
    plugin_id: str,
    expected_revision: str,
    experiment_name: str,
    overwrite_existing: bool,
    run_options: dict[str, Any],
) -> JobRecord:
    if workspace.workspace_revision != expected_revision:
        raise FrozenInputError("workspace_revision_conflict", "工作区修订已经变化，请重新打开后再提交", 409)
    try:
        revision = workspaces.get_revision(workspace.workspace_id, workspace.workspace_revision)
    except PlanContentHashMismatch as exc:
        raise FrozenInputError("plan_hash_mismatch", "规划修订校验失败", 422) from exc
    if revision is None:
        raise FrozenInputError("plan_hash_mismatch", "规划修订不存在", 422)
    try:
        document = parse_stored_plan(revision.content_json)
    except PlanInvalid as exc:
        raise FrozenInputError("plan_invalid", str(exc), 422) from exc
    plugin = _plugin(service, plugin_id)
    resolved = _resolved_config(plugin, document, revision.base_scene_id, experiment_name, overwrite_existing, run_options)
    from experiments.base_scene_snapshot import (
        SnapshotError,
        manifest_sha256,
        prepare_base_snapshot,
        register_ready_snapshot,
        verify_base_snapshot,
    )
    from experiments.frozen_inputs import content_sha256
    from experiments.scene_lock import SceneBusyError, scene_write_lock
    from experiments.scene_store import scene_directory, scenes_root
    from experiments.scene_version import scene_data_version

    root = scenes_root()
    try:
        with scene_write_lock(revision.base_scene_id, root, timeout=30):
            directory = scene_directory(root, revision.base_scene_id)
            version = scene_data_version(directory)
            if version["frame_id"] != revision.base_frame_id or version["scene_revision"] != revision.base_revision:
                raise FrozenInputError("workspace_base_changed", "公共场景已更新，这次提交不会改用新场景", 409)
            prepared = prepare_base_snapshot(revision.base_scene_id, scene_root=root)
            manifest = verify_base_snapshot(prepared.snapshot_id)
            if manifest["base_frame_id"] != revision.base_frame_id or manifest["base_revision"] != revision.base_revision:
                raise FrozenInputError("workspace_base_changed", "基础快照与工作区修订不一致", 409)
            digest = manifest_sha256(manifest)
            binding = JobBinding(
                workspace_id=workspace.workspace_id,
                workspace_revision=revision.revision_id,
                base_scene_id=revision.base_scene_id,
                base_frame_id=revision.base_frame_id,
                base_revision=revision.base_revision,
                base_snapshot_id=prepared.snapshot_id,
                planning_content_hash=revision.content_sha256,
                effective_config_hash=content_sha256(resolved),
                resolved_config_json=json.dumps(resolved, sort_keys=True, ensure_ascii=False),
                snapshot_manifest_sha256=digest,
            )
            record = service.repository.create_job(
                _job_id(), plugin.id, plugin.version, resolved["form"], workspace.owner_id, binding=binding,
            )
            _remember_reference(workspaces.database_url, prepared.snapshot_id, record.id, register_ready_snapshot)
            _enqueue(service, record.id)
            return record
    except SceneBusyError as exc:
        raise FrozenInputError("scene_busy", "场景正被其他计算读取或写入，请稍后再提交", 409) from exc
    except SnapshotError as exc:
        raise FrozenInputError(exc.code, exc.message, 409 if exc.code in {"scene_not_found", "scene_not_ready"} else 422) from exc
    except FileNotFoundError as exc:
        raise FrozenInputError("workspace_base_missing", "工作区绑定的公共场景已不存在", 409) from exc


def run_bound_job(service, record: JobRecord, report) -> PluginResult:
    _require_binding(record)
    url = _database_url(service.repository)
    workspaces = WorkspaceRepository(url)
    try:
        revision = workspaces.get_revision(record.workspace_id, record.workspace_revision)
    except PlanContentHashMismatch as exc:
        raise FrozenInputError("frozen_revision_mismatch", "规划修订哈希与保存的内容不一致") from exc
    if revision is None or revision.content_sha256 != record.planning_content_hash:
        raise FrozenInputError("frozen_revision_mismatch", "任务绑定的规划修订不存在或哈希不符")
    if revision.owner_id != record.owner_id:
        raise FrozenInputError("frozen_revision_mismatch", "任务主人与规划修订不一致")
    resolved = json.loads(record.resolved_config_json or "")
    from experiments.frozen_inputs import content_sha256

    if content_sha256(resolved) != record.effective_config_hash:
        raise FrozenInputError("frozen_config_mismatch", "有效算法配置与提交时的哈希不符")
    if resolved.get("plugin_id") != record.plugin_id or resolved.get("plugin_version") != record.plugin_version:
        raise FrozenInputError("plugin_version_mismatch", "任务记录的插件版本与冻结配置不一致")
    plugin = _plugin(service, record.plugin_id)
    if plugin.version != record.plugin_version:
        raise FrozenInputError("plugin_version_mismatch", "当前插件版本不能执行这份冻结配置")
    from experiments.base_scene_snapshot import (
        SnapshotError,
        _resolve_root,
        _snapshot_dir,
        manifest_sha256,
        register_ready_snapshot,
        verify_base_snapshot,
    )

    try:
        manifest = verify_base_snapshot(record.base_snapshot_id)
    except SnapshotError as exc:
        raise FrozenInputError(exc.code, exc.message) from exc
    if manifest_sha256(manifest) != record.snapshot_manifest_sha256:
        raise FrozenInputError("frozen_snapshot_mismatch", "基础快照清单哈希与任务记录不符")
    if (
        manifest["base_scene_id"] != record.base_scene_id
        or manifest["base_frame_id"] != record.base_frame_id
        or manifest["base_revision"] != record.base_revision
    ):
        raise FrozenInputError("frozen_snapshot_mismatch", "基础快照身份与任务记录不符")
    _remember_reference(url, record.base_snapshot_id, record.id, register_ready_snapshot)
    snapshot_dir = _snapshot_dir(_resolve_root(None), record.base_snapshot_id)
    provenance = _provenance(record)
    form = resolved["form"]
    if record.plugin_id == "routing.nsga2":
        from config.routing_task import RoutingRunConfig
        from experiments.launch_routing_run import launch_routing_run

        task = RoutingRunConfig.model_validate(form)
        if task.model_dump(mode="json") != form:
            raise FrozenInputError("frozen_config_mismatch", "执行时的选线配置与提交时不一致")
        output = launch_routing_run(task, report, snapshot_dir=snapshot_dir, provenance=provenance)
        return PluginResult("succeeded", {}, {"experiment_id": output.name, "problem_type": "routing", "optimizer_executed": True})
    from plugins.site_plugin import _search_result

    output = _launch_site(record.plugin_id, form, resolved, snapshot_dir, report, provenance)
    return PluginResult("succeeded", {}, _search_result(output, plugin.expected_artifacts))


def _launch_site(plugin_id: str, form: dict, resolved: dict, snapshot_dir, report, provenance: dict):
    width = resolved.get("protected_farmland_access_width_m")
    project = resolved.get("project")
    if not isinstance(width, (int, float)) or not isinstance(project, dict):
        raise FrozenInputError("frozen_config_mismatch", "选址任务缺少冻结的完整配置")
    if plugin_id == "site.partitioned_guided_search":
        from experiments.partitioned_search import launch_partitioned_site_run

        return launch_partitioned_site_run(
            form, report, snapshot_dir=snapshot_dir, farmland_access_width_m=float(width),
            frozen_project=project, provenance=provenance,
        )
    from experiments.launch_site_run import launch_site_run

    algorithm = resolved.get("algorithm")
    if algorithm not in {"guided_search", "cma_es", "multistart_adam"}:
        raise FrozenInputError("plugin_not_supported", "这个选址插件不能从工作区运行")
    return launch_site_run(
        form, algorithm, report, snapshot_dir=snapshot_dir, farmland_access_width_m=float(width),
        frozen_project=project, provenance=provenance,
    )


def _resolved_config(plugin, document: PlanningDocument, scene_id: str, experiment_name: str, overwrite: bool, run_options: dict) -> dict:
    if not isinstance(run_options, dict):
        raise FrozenInputError("invalid_run_options", "运行参数必须是对象")
    foreign = _CLIENT_BINDING_FIELDS.intersection(run_options)
    if foreign:
        raise FrozenInputError("invalid_run_options", "运行参数不能指定工作区或快照身份")
    if plugin.id == "routing.nsga2":
        return _routing_config(plugin, document, scene_id, experiment_name, overwrite, run_options)
    return _site_config(plugin, document, scene_id, experiment_name, overwrite, run_options)


def _site_config(plugin, document: PlanningDocument, scene_id: str, experiment_name: str, overwrite: bool, run_options: dict) -> dict:
    plan = document.site
    if plan is None:
        raise FrozenInputError("plan_incomplete", "选址规划是空的，不能提交选址任务")
    unknown = set(run_options) - _SITE_RUN_FIELDS
    if unknown:
        raise FrozenInputError("invalid_run_options", "选址运行参数含有不能在提交时覆盖的字段")
    payload = {
        "experiment_name": experiment_name,
        "overwrite_existing": overwrite,
        "scene_name": scene_id,
        "rect_w_m": plan.rect_w_m,
        "rect_h_m": plan.rect_h_m,
        "field_policy": plan.field_policy,
        "mountain_policy": plan.mountain_policy,
        "field_cost": plan.field_cost,
        "road_setback_m": plan.road_setback_m,
        "water_setback_m": plan.water_setback_m,
        "demand_on_buildable_only": False,
        "exclusion_zones": [{"points": [list(point) for point in zone.points]} for zone in plan.exclusion_zones],
        "feasible_zones": [{"points": [list(point) for point in zone.points]} for zone in plan.feasible_zones],
        **run_options,
    }
    if plan.highway_setback_m is not None:
        payload["highway_setback_m"] = plan.highway_setback_m
    if plan.elevation_enabled and plan.elevation_draft.strip():
        payload["max_elevation_m"] = float(plan.elevation_draft)
    if "origin_x" in plugin.model.model_fields:
        payload["origin_x"] = None if plan.origin is None else plan.origin.x
        payload["origin_y"] = None if plan.origin is None else plan.origin.y
        payload["include_demand"] = plan.include_demand
    try:
        form = plugin.model.model_validate(payload).model_dump(mode="json")
    except Exception as exc:
        raise FrozenInputError("plan_incomplete", str(exc)) from exc
    from config.project_config import load_default_config
    from experiments.frozen_inputs import dump_project
    from experiments.launch_site_run import apply_site_form

    current = load_default_config()
    width = float(current.data.protected_farmland_access_width_m)
    algorithm = "guided_search" if plugin.id == "site.partitioned_guided_search" else plugin.algorithm
    project = apply_site_form(current, form, algorithm)
    return {
        "plugin_id": plugin.id,
        "plugin_version": plugin.version,
        "algorithm": algorithm,
        "form": form,
        "project": dump_project(project),
        "protected_farmland_access_width_m": width,
    }


def _routing_config(plugin, document: PlanningDocument, scene_id: str, experiment_name: str, overwrite: bool, run_options: dict) -> dict:
    plan = document.routing
    if plan is None:
        raise FrozenInputError("plan_incomplete", "选线规划是空的，不能提交选线任务")
    if set(run_options) - {"algorithm"}:
        raise FrozenInputError("invalid_run_options", "选线运行参数只接受 algorithm")
    requested = run_options.get("algorithm", {})
    if not isinstance(requested, dict):
        raise FrozenInputError("invalid_run_options", "选线算法参数必须是对象")
    from config.routing_task import RoutingRunConfig

    payload = {
        "scene_name": scene_id,
        "experiment_name": experiment_name,
        "overwrite_existing": overwrite,
        "start": {"lng": float(plan.start.lng), "lat": float(plan.start.lat)},
        "end": {"lng": float(plan.end.lng), "lat": float(plan.end.lat)},
        "max_span_m": float(plan.max_span_m),
        "tower_radius_m": float(plan.tower_radius_m),
        "max_turn_deg": float(plan.max_turn_deg),
        "no_tower_zones": plan.no_tower_zones,
        "no_cross_zones": plan.no_cross_zones,
        "algorithm": {**plan.algorithm_overrides, **requested},
    }
    if plan.road_setback_m.strip():
        payload["road_setback_m"] = float(plan.road_setback_m)
    if plan.highway_setback_m.strip():
        payload["highway_setback_m"] = float(plan.highway_setback_m)
    try:
        form = RoutingRunConfig.model_validate(payload).model_dump(mode="json")
    except Exception as exc:
        raise FrozenInputError("plan_incomplete", str(exc)) from exc
    return {
        "plugin_id": plugin.id,
        "plugin_version": plugin.version,
        "algorithm": "routing_nsga2",
        "form": form,
        "project": None,
        "protected_farmland_access_width_m": None,
    }


def _plugin(service, plugin_id: str):
    if plugin_id in _BUILD_PLUGINS or plugin_id not in _COMPUTE_PLUGINS:
        raise FrozenInputError("plugin_not_supported", "工作区任务只接受选址或选线计算插件")
    try:
        plugin = service.registry.get(plugin_id)
    except PluginError as exc:
        raise FrozenInputError("plugin_not_supported", "工作区任务只接受选址或选线计算插件") from exc
    return plugin


def _require_binding(record: JobRecord) -> None:
    required = (
        record.workspace_id,
        record.workspace_revision,
        record.base_scene_id,
        record.base_frame_id,
        record.base_revision,
        record.base_snapshot_id,
        record.planning_content_hash,
        record.effective_config_hash,
        record.resolved_config_json,
        record.snapshot_manifest_sha256,
        record.owner_id,
    )
    if any(value in (None, "") for value in required):
        raise FrozenInputError("frozen_input_missing", "工作区任务缺少冻结输入，已拒绝执行")


def _remember_reference(database_url: str, snapshot_id: str, job_id: str, register) -> None:
    try:
        catalog = BaseSnapshotRepository(database_url)
        register(catalog, snapshot_id)
        catalog.add_reference(snapshot_id, "job", job_id)
    except Exception:
        logger.exception("workspace job %s could not record snapshot reference %s", job_id, snapshot_id)


def _enqueue(service, job_id: str) -> None:
    try:
        service.queue.enqueue(job_id)
    except Exception:
        logger.exception("workspace job %s stayed queued because enqueue failed", job_id)


def _database_url(repository) -> str:
    url = getattr(repository, "url", None)
    if isinstance(url, str) and url:
        return url
    path = getattr(repository, "path", None)
    if not path or path == ":memory:":
        raise FrozenInputError("job_database", "任务库不能回读工作区修订", 500)
    return "sqlite:///" + str(path)


def _job_id() -> str:
    import uuid

    return str(uuid.uuid4())


def _provenance(record: JobRecord) -> dict[str, str]:
    return {
        "owner_id": record.owner_id or "",
        "workspace_id": record.workspace_id or "",
        "workspace_revision": record.workspace_revision or "",
        "base_scene_id": record.base_scene_id or "",
        "base_frame_id": record.base_frame_id or "",
        "base_revision": record.base_revision or "",
        "base_snapshot_id": record.base_snapshot_id or "",
        "planning_content_hash": record.planning_content_hash or "",
        "effective_config_hash": record.effective_config_hash or "",
        "plugin_id": record.plugin_id,
        "plugin_version": record.plugin_version,
        "job_id": record.id,
    }
