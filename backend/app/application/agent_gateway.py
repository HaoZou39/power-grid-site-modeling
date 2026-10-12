"""Adapt existing read-only services into the assistant's tool context."""

from __future__ import annotations

from backend.app.domain.plugins import PluginRegistry
from backend.app.infrastructure.experiment_catalog import ExperimentCatalog

from agent.memory import MemoryEntry
from agent.preference.history import load_choices, preference_path
from agent.tools import ToolContext
from agent.workspace import WorkspaceSnapshot


def live_tool_context(
    snapshot: WorkspaceSnapshot,
    catalog: ExperimentCatalog,
    registry: PluginRegistry,
    memory: list[MemoryEntry] | None = None,
) -> ToolContext:
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

    return ToolContext(
        snapshot=snapshot,
        list_scenes=list_scenes,
        list_experiments=list_experiments,
        get_experiment=get_experiment,
        list_plugins=list_plugins,
        evaluate_pose=evaluate_pose,
        footprint_terrain=footprint_terrain,
        preference_choices=lambda: load_choices(preference_path()),
        memory=tuple(memory or ()),
    )
