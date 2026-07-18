"""Shared exception vocabulary (ADR 0001).

Package-root shared kernel: importable from every layer (policies, transport, ports,
adapters, resolvers, services) without creating a layering violation, since it sits
outside the layer hierarchy entirely, like `config.py`/`models.py`.
"""

from __future__ import annotations


class OpenProjectError(Exception):
    """Base error for safe OpenProject failures."""


class AuthenticationError(OpenProjectError):
    """Authentication failed."""


class PermissionDeniedError(OpenProjectError):
    """Access to the resource was denied."""


class NotFoundError(OpenProjectError):
    """The requested resource does not exist."""


class InvalidInputError(OpenProjectError):
    """A provided tool or request input is invalid."""


class OpenProjectServerError(OpenProjectError):
    """OpenProject returned an unexpected failure."""


class TransportError(OpenProjectError):
    """The request could not reach OpenProject safely."""
