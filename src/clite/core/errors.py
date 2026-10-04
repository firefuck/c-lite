"""Exception types shared across packages."""

from __future__ import annotations


class CliteError(Exception):
    """Base class for errors the CLI reports without a traceback."""


class ConfigError(CliteError):
    """The configuration file is unreadable or holds an invalid value."""


class AuthError(CliteError):
    """A provider could not be resolved to usable credentials."""

    def __init__(self, message: str, *, provider: str = "", code: str = "") -> None:
        super().__init__(message)
        self.provider = provider
        self.code = code


class ProviderError(CliteError):
    """A model provider request failed in a way the caller should surface."""


class ProfileError(CliteError):
    """A profile operation was refused."""
