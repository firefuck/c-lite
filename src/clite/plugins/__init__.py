"""Plugin system: discovery, loading, and the hook bus.

``clite.plugins.hooks`` is a leaf module any layer may import. The manager and the plugin
context sit above ``tools`` and ``agent`` and are imported lazily by the surfaces.
"""
