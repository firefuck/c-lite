"""Every product-name string in one place.

``scripts/rename_project.py`` rewrites the whole tree, but code should still read these
constants rather than spell the name out, so a rename stays a mechanical change.
"""

APP_NAME = "clite"  # Python package, CLI command
DISPLAY_NAME = "C-lite"  # what users read
ENV_PREFIX = "CLITE"  # CLITE_HOME, CLITE_TUI, ...
HOME_DIRNAME = ".clite"  # ~/.clite

HOME_ENV = f"{ENV_PREFIX}_HOME"
PLUGIN_NAMESPACE = f"{APP_NAME}_plugins"  # synthetic import namespace for loaded plugins
ENTRY_POINT_GROUP = f"{APP_NAME}.plugins"  # pip entry-point group for plugins
PROJECT_CONTEXT_FILENAMES = (f".{APP_NAME}.md", f"{APP_NAME.upper()}.md")
PROJECT_DIRNAME = f".{APP_NAME}"  # ./.clite/ inside a project (plugins, skills, plans)

# ``metadata.<key>`` blocks read from SKILL.md frontmatter. Hermes skills use
# ``metadata.hermes``; reading both lets skills written for either agent load unchanged.
SKILL_METADATA_KEYS = (APP_NAME, "hermes")

# First line a headless ``serve`` prints once it is listening; the desktop app watches for it.
BACKEND_READY_SENTINEL = f"{ENV_PREFIX}_BACKEND_READY"
SESSION_TOKEN_ENV = f"{ENV_PREFIX}_SESSION_TOKEN"
