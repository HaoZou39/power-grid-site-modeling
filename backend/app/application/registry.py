from backend.app.domain.plugins import PluginRegistry
from plugins.demo.plugin import DemoAlgorithmPlugin
from plugins.site_plugin import CmaEsSitePlugin, MultiStartAdamSitePlugin, Nsga2SitePlugin, PrepareScenePlugin


def build_registry() -> PluginRegistry:
    registry = PluginRegistry()
    registry.register(DemoAlgorithmPlugin())
    registry.register(Nsga2SitePlugin())
    registry.register(CmaEsSitePlugin())
    registry.register(MultiStartAdamSitePlugin())
    registry.register(PrepareScenePlugin())
    return registry
