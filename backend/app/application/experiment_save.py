"""Save a complete site or routing case from a retained workspace."""

from time import perf_counter
from typing import Any

from backend.app.infrastructure.experiment_catalog import ExperimentCatalog
from backend.app.infrastructure.repository import JobRepository
from experiments.auto_result_retention import pin_auto_result
from experiments.scene_lock import SceneBusyError, scene_compute_lock


class ActiveSceneJobs(Exception):
    def __init__(self, job_ids: list[str]) -> None:
        super().__init__("该场景有排队、运行或取消中的任务，退出后才能更改场景数据。")
        self.job_ids = job_ids


class InvalidSaveScene(Exception):
    """A scene name does not resolve inside the scene root."""


def require_idle_scene(repository: JobRepository, scene_name: str) -> None:
    if scene_name in repository.active_scene_names():
        raise ActiveSceneJobs([
            record.id for record in repository.list_active_jobs()
            if scene_name in (record.config.get("scene_name"), record.config.get("scene_id"))
        ])


def save_site_case(
    catalog: ExperimentCatalog,
    repository: JobRepository,
    name: str,
    form: dict[str, Any],
    poses: list[dict[str, Any]],
    source_id: str | None,
    fast_source_id: str | None,
) -> str:
    from experiments.fast_save import log_save_path, try_fast_save
    from experiments.save_workspace import save_workspace
    from experiments.scene_store import scene_directory, scenes_root

    scene_name = form["scene_name"]
    require_idle_scene(repository, scene_name)
    started = perf_counter()
    fast_id = (fast_source_id or "").strip() or None
    mode = "not_requested"
    reason = ""
    validation_s = write_s = 0.0
    experiment_id = None
    timings: dict[str, float] = {}
    try:
        with pin_auto_result(catalog.root, source_id):
            if fast_id:
                mode = "fallback"
                attempt = try_fast_save(catalog, name, form, poses, source_id, fast_id)
                validation_s = attempt.validation_s
                reason = attempt.reason
                if attempt.experiment_id:
                    mode = "hit"
                    experiment_id = attempt.experiment_id
                    write_s = attempt.write_s
            if experiment_id is None:
                try:
                    directory = scene_directory(scenes_root(), scene_name)
                except ValueError as exc:
                    raise InvalidSaveScene(str(exc)) from exc
                with scene_compute_lock(scene_name, directory.parent):
                    require_idle_scene(repository, scene_name)
                    experiment_id = save_workspace(catalog.root, name, form, poses, source_id, timings)
                write_s = timings.get("write_s", 0.0)
    except SceneBusyError:
        raise
    except (FileNotFoundError, ValueError):
        reason = reason or "rejected"
        raise
    except OSError:
        reason = reason or "write_failed"
        raise
    finally:
        log_save_path(mode, fast_id or source_id, experiment_id, len(poses), reason,
                      validation_s, timings.get("evaluate_s", 0.0), timings.get("pareto_s", 0.0),
                      write_s, perf_counter() - started)
    return experiment_id


def save_routing_case(
    catalog: ExperimentCatalog,
    repository: JobRepository,
    name: str,
    task_config: dict[str, Any],
    source_id: str,
) -> tuple[str, int]:
    from config.routing_task import RoutingRunConfig
    from experiments.save_routing_workspace import save_routing_workspace

    # The display name is stored separately from the task's directory name.
    task = RoutingRunConfig.model_validate({**task_config, "experiment_name": "routing-workspace"})
    require_idle_scene(repository, task.scene_name)
    with pin_auto_result(catalog.root, source_id):
        record = catalog.get_experiment(source_id)
        has_snapshot = any(item.name == "filter_snapshot.json" for item in record.artifacts)
        source_name = "filter_snapshot.json" if has_snapshot or record.summary.get("case_kind") == "filter_result" else "routes.json"
        source, _ = catalog.resolve_artifact(source_id, source_name)
        return save_routing_workspace(catalog.root, name, task, source)
