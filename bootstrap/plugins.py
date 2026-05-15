class PluginRegistry:
    def __init__(self, plugins=None):
        self._plugins = list(plugins or [])

    def register(self, plugin):
        self._plugins.append(plugin)

    def initialize_all(self, app):
        for plugin in self._plugins:
            setup = getattr(plugin, "setup", None)
            if callable(setup):
                setup(app)
