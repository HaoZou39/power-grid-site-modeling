from backend.app.domain.plugins import PluginRegistry
from plugins.demo.plugin import DemoAlgorithmPlugin


def build_registry() -> PluginRegistry:
    registry = PluginRegistry()
    registry.register(DemoAlgorithmPlugin())
    return registry
