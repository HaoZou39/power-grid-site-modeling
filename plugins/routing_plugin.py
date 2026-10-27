"""Routing Jobs adapter; task schemas are independent of plugin execution."""

from backend.app.domain.plugins import PluginResult, PluginSpec
from config.routing_task import ConnectionPoint, RoutingParameters, RoutingRunConfig
from plugins.schema import plugin_schema


class RoutingPlugin:
    id = "routing.nsga2"
    version = "0.1.0"

    def describe(self) -> PluginSpec:
        schema = plugin_schema(RoutingRunConfig)
        # Generic forms and the routing UI share the resolved schema defaults.
        schema["properties"]["algorithm"]["default"] = RoutingParameters().model_dump()
        return PluginSpec(self.id, self.version, "algorithm", "四目标杆塔选线",
            "固定接入点，优化新增塔数、DEM三维长度、水平曲折度与等权跨越长度；净空未校核。", schema)

    def validate_config(self, config: dict) -> None:
        RoutingRunConfig.model_validate(config)

    def run(self, config: dict, reporter) -> PluginResult:
        from experiments.launch_routing_run import launch_routing_run
        directory = launch_routing_run(RoutingRunConfig.model_validate(config), reporter)
        return PluginResult("succeeded", {}, {"experiment_id": directory.name, "problem_type": "routing",
            "optimizer_executed": True, "expected_artifacts": ["routes.json", "run_summary.json", "solutions.csv", "pareto_solutions.csv"]})
