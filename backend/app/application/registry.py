from backend.app.domain.plugins import PluginRegistry
from plugins.demo.plugin import DemoAlgorithmPlugin
from plugins.routing_plugin import RoutingPlugin
from plugins.site_plugin import (
    BuildScenePlugin,
    CmaEsSitePlugin,
    GuidedSitePlugin,
    MultiStartAdamSitePlugin,
    PartitionedGuidedSitePlugin,
    PrepareScenePlugin,
)


def build_registry() -> PluginRegistry:
    registry = PluginRegistry()
    registry.register(DemoAlgorithmPlugin())
    registry.register(RoutingPlugin())
    registry.register(GuidedSitePlugin())
    registry.register(PartitionedGuidedSitePlugin())
    registry.register(CmaEsSitePlugin())
    registry.register(MultiStartAdamSitePlugin())
    registry.register(PrepareScenePlugin())
    registry.register(BuildScenePlugin())
    return registry
