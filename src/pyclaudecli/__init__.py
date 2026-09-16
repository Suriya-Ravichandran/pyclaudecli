"""pyclaudecli: a Python library that wraps the `claude` CLI (Claude Code)."""

from .client import ClaudeCLI, build_flags
from .exceptions import ClaudeCLIError, ClaudeNotFoundError, ClaudeTimeoutError

__version__ = "0.1.0"

__all__ = [
    "ClaudeCLI",
    "build_flags",
    "ClaudeCLIError",
    "ClaudeNotFoundError",
    "ClaudeTimeoutError",
]
