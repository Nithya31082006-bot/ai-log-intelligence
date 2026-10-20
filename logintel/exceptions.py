"""Domain exceptions. The API layer maps these onto HTTP status codes."""
from __future__ import annotations


class LogIntelError(Exception):
    """Base class for all expected, user-facing errors."""
    http_status = 400


class ValidationError(LogIntelError):
    """Input is malformed, too large, or otherwise unusable."""
    http_status = 400


class NotFoundError(LogIntelError):
    """A referenced batch/run does not exist."""
    http_status = 404


class AnalysisError(LogIntelError):
    """Input is valid but the requested analysis cannot be performed."""
    http_status = 422
