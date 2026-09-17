"""pyclaudecli: a Python library that wraps the `claude` CLI (Claude Code)."""

from .client import ClaudeCLI, build_flags
from .exceptions import (
    ClaudeCLIError,
    ClaudeNotFoundError,
    ClaudeTimeoutError,
    ClaudeUsageError,
)

__version__ = "1.0.6"

__all__ = [
    "ClaudeCLI",
    "build_flags",
    "ClaudeCLIError",
    "ClaudeNotFoundError",
    "ClaudeTimeoutError",
    "ClaudeUsageError",
]
