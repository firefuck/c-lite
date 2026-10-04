"""Agent Client Protocol server: lets an editor (Zed and others) drive the agent over stdio.

Not implemented yet. ``clite acp`` prints where the work is specified
(``docs/roadmap/fase-6-ekosistem.md``, task F6-T4). The package exists so the layer has a
place in the import rules (see ``tests/test_architecture.py``): it is a surface, at the same
level as ``server``, and will sit on top of ``clite.runtime`` like every other surface.
"""
