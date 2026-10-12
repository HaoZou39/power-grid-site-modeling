"""Adapt existing read-only services into the assistant's tool context."""

from __future__ import annotations

from backend.app.domain.plugins import PluginRegistry
from backend.app.infrastructure.experiment_catalog import ExperimentCatalog

from agent.memory import MemoryEntry
from agent.preference.candidates import load_pareto_csv
from agent.preference.models import ObjectiveSpec
from agent.preference.service import PreferenceService
from agent.tools import ToolContext
from agent.workspace import WorkspaceSnapshot


def live_tool_context(
    snapshot: WorkspaceSnapshot,
    catalog: ExperimentCatalog,
    registry: PluginRegistry,
    memory: list[MemoryEntry] | None = None,
) -> ToolContext:
    preference_service = PreferenceService()

    def list_scenes() -> list[dict]:
        from experiments.scene_store import list_scenes as read_scenes

        return read_scenes()

    def list_experiments() -> list[dict]:
        return [
            {
                "id": record.id,
                "name": record.name,
                "algorithm": record.algorithm,
                "modified_at": record.modified_at,
                "summary": record.summary,
            }
            for record in catalog.list_experiments()
        ]

    def get_experiment(experiment_id: str) -> dict:
        return catalog.get_experiment(experiment_id).to_dict()

    def list_plugins() -> list[dict]:
        return [spec.to_dict() for spec in registry.list_specs()]

    def evaluate_pose(x: float, y: float, theta: float) -> dict:
        from experiments.scene_store import scene_directory, scenes_root
        from experiments.site_report import build_site_report

        origin = None
        if snapshot.origin is not None:
            origin = (snapshot.origin.x, snapshot.origin.y)
        report = build_site_report(
            scene_directory(scenes_root(None), snapshot.scene_name),
            x,
            y,
            theta,
            snapshot.building.width_m,
            snapshot.building.height_m,
            origin,
        )
        # The polyline is for the map. The model only needs the measured numbers.
        return {key: value for key, value in report.items() if key != "haul_path"}

    def footprint_terrain(x: float, y: float, theta: float) -> dict:
        from experiments.scene_store import scene_directory, scenes_root
        from experiments.site_report import build_footprint_terrain

        return build_footprint_terrain(
            scene_directory(scenes_root(None), snapshot.scene_name),
            x,
            y,
            theta,
            snapshot.building.width_m,
            snapshot.building.height_m,
        )

    def _objective_specs(args: dict) -> list[ObjectiveSpec]:
        names = args.get("objective_names")
        if not isinstance(names, list) or not names or not all(isinstance(name, str) and name for name in names):
            raise ValueError("objective_names 必须是非空字符串数组")
        directions = args.get("objective_directions", {})
        if not isinstance(directions, dict):
            raise ValueError("objective_directions 必须是对象")
        return [ObjectiveSpec(name, directions.get(name, "min")) for name in names]

    def recommend_pareto(args: dict) -> dict:
        experiment_id = args.get("experiment_id")
        if not isinstance(experiment_id, str) or not experiment_id:
            raise ValueError("recommend_site_solutions 需要 experiment_id")
        specs = _objective_specs(args)
        path, _ = catalog.resolve_artifact(experiment_id, "pareto_solutions.csv")
        return preference_service.recommend_from_csv(path, specs, top_k=int(args.get("top_k", 5)))

    def fit_preference(args: dict) -> dict:
        experiment_id = args.get("experiment_id")
        if not isinstance(experiment_id, str) or not experiment_id:
            raise ValueError("fit_preference_model 需要 experiment_id")
        specs = _objective_specs(args)
        path, _ = catalog.resolve_artifact(experiment_id, "pareto_solutions.csv")
        candidates = load_pareto_csv(path, [spec.name for spec in specs])
        return preference_service.fit_model(candidates, specs)

    return ToolContext(
        snapshot=snapshot,
        list_scenes=list_scenes,
        list_experiments=list_experiments,
        get_experiment=get_experiment,
        list_plugins=list_plugins,
        evaluate_pose=evaluate_pose,
        footprint_terrain=footprint_terrain,
        memory=tuple(memory or ()),
        preference_service=preference_service,
        recommend_pareto=recommend_pareto,
        fit_preference=fit_preference,
    )
