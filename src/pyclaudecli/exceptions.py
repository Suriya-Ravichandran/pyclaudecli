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


class ClaudeUsageError(ClaudeCLIError):
    """Raised for a malformed `pyclaudecli` command line.

    Carries `returncode=2`, the conventional exit status for a usage error,
    and an optional `hint` with the fix to suggest.
    """

    def __init__(self, message: str, *, hint: Optional[str] = None) -> None:
        super().__init__(message, returncode=2)
        self.hint = hint
