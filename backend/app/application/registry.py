from backend.app.domain.plugins import PluginRegistry
from plugins.demo.plugin import DemoAlgorithmPlugin
from plugins.site_plugin import CmaEsSitePlugin, MultiStartAdamSitePlugin, GuidedSitePlugin, PrepareScenePlugin


def build_registry() -> PluginRegistry:
    registry = PluginRegistry()
    registry.register(DemoAlgorithmPlugin())
    registry.register(GuidedSitePlugin())
    registry.register(CmaEsSitePlugin())
    registry.register(MultiStartAdamSitePlugin())
    registry.register(PrepareScenePlugin())
    return registry
