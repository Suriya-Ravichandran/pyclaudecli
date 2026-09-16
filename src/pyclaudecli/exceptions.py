"""Exceptions raised by pyclaudecli."""

from __future__ import annotations

from typing import Optional, Sequence


class ClaudeCLIError(Exception):
    """Raised when the `claude` CLI exits with a non-zero status."""

    def __init__(
        self,
        message: str,
        *,
        returncode: Optional[int] = None,
        stdout: Optional[str] = None,
        stderr: Optional[str] = None,
        cmd: Optional[Sequence[str]] = None,
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.cmd = list(cmd) if cmd is not None else None


class ClaudeNotFoundError(ClaudeCLIError):
    """Raised when the `claude` binary can't be found on PATH."""


class ClaudeTimeoutError(ClaudeCLIError):
    """Raised when a `claude` invocation exceeds its timeout."""
