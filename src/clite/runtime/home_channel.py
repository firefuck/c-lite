"""Home channels for messaging platforms: ``platform -> chat_id``."""

from __future__ import annotations

import threading
from typing import Any

from clite.core.config import get_path
from clite.core.constants import get_home
from clite.core.io import atomic_write_json, read_json


class HomeChannels:
    """``platform -> home chat id``, in ``<home>/gateway/home_channels.json``."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.path = get_home() / "gateway" / "home_channels.json"
        self.config = config or {}
        self._lock = threading.Lock()

    def _load(self) -> dict[str, str]:
        data = read_json(self.path, {})
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def get(self, platform: str) -> str | None:
        with self._lock:
            val = self._load().get(platform)
        if val:
            return val
        cfg_channels = get_path(self.config, "gateway.home_channels", {})
        if isinstance(cfg_channels, dict) and platform in cfg_channels:
            return str(cfg_channels[platform])
        return None

    def set(self, platform: str, chat_id: str) -> None:
        with self._lock:
            data = self._load()
            data[platform] = str(chat_id)
            atomic_write_json(self.path, data)
