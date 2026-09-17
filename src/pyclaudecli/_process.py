"""Low-level process plumbing shared by ClaudeCLI's methods."""

from __future__ import annotations

import os
import re
import select
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Iterator, Optional, Sequence

from .exceptions import ClaudeCLIError, ClaudeNotFoundError, ClaudeTimeoutError

_URL_PATTERN = re.compile(r"https://\S+")

# Flags whose values are credentials (MCP auth headers, injected env vars).
_SECRET_FLAGS = frozenset({"--header", "--env", "--client-id", "--client-secret"})

# Credential shapes that can turn up anywhere in an argv, including inside the
# JSON blob passed to `mcp add-json`.
_SECRET_VALUE_PATTERN = re.compile(
    r"""(
        sk-ant-[\w-]+                      # Anthropic API keys
      | pypi-[\w-]+                        # PyPI tokens
      | gh[pousr]_[A-Za-z0-9]+             # GitHub tokens
      | [Bb]earer\s+\S+                    # bearer tokens
      | (?i:[\w.-]*(?:token|secret|key|password|passwd|auth)[\w.-]*)
        \s*["\s]*[=:]\s*"?[^\s"',}]+       # anything token/secret/key-ish = value
    )""",
    re.VERBOSE,
)

_REDACTED = "<redacted>"
_MAX_ARG_LEN = 120
_MAX_DETAIL_LEN = 2000
_MAX_LOGIN_BUFFER = 64 * 1024


def redact_arg(value: str, limit: Optional[int] = _MAX_ARG_LEN) -> str:
    """Masks credential-looking substrings, and truncates very long values."""
    cleaned = _SECRET_VALUE_PATTERN.sub(_REDACTED, str(value))
    if limit is not None and len(cleaned) > limit:
        cleaned = cleaned[:limit] + "…"
    return cleaned


def redact_command(command: Sequence[str]) -> list:
    """Returns a copy of an argv safe to put in an error message or a log.

    Values of credential-bearing flags are replaced wholesale; everything else
    is scanned for embedded secrets and truncated. Flag *names* survive, so the
    command stays recognisable when debugging.
    """
    safe = []
    masking = False
    for token in command:
        token = str(token)
        if token.startswith("-"):
            masking = token in _SECRET_FLAGS
            safe.append(token)
            continue
        safe.append(_REDACTED if masking else redact_arg(token))
    return safe


def format_command(command: Sequence[str]) -> str:
    """A redacted, shell-ish rendering of an argv for error messages."""
    return " ".join(redact_command(command))


@dataclass
class CommandResult:
    args: list
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run(
    binary: str,
    args: Sequence[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    input_text: Optional[str] = None,
    timeout: Optional[float] = None,
    check: bool = True,
) -> CommandResult:
    command = [binary, *args]
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ClaudeNotFoundError(
            f"'{binary}' was not found on PATH. Is Claude Code installed?",
            cmd=redact_command(command),
        ) from exc
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        raise ClaudeTimeoutError(
            f"'{format_command(command)}' did not finish within {timeout}s",
            cmd=redact_command(command),
            stdout=stdout,
            stderr=stderr,
        ) from exc

    result = CommandResult(command, completed.returncode, completed.stdout, completed.stderr)
    if check and not result.ok:
        detail = redact_arg((result.stderr or result.stdout or "").strip(), limit=_MAX_DETAIL_LEN)
        raise ClaudeCLIError(
            f"'{format_command(command)}' exited with {result.returncode}: {detail}",
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            cmd=redact_command(command),
        )
    return result


def stream_lines(
    binary: str,
    args: Sequence[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
) -> Iterator[str]:
    """Runs a command and yields decoded stdout lines as they arrive."""
    command = [binary, *args]
    try:
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        raise ClaudeNotFoundError(
            f"'{binary}' was not found on PATH. Is Claude Code installed?",
            cmd=redact_command(command),
        ) from exc

    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            yield line.rstrip("\n")
    finally:
        proc.stdout.close()
        returncode = proc.wait()
        if returncode != 0:
            raise ClaudeCLIError(
                f"'{format_command(command)}' exited with {returncode}",
                returncode=returncode,
                cmd=redact_command(command),
            )


def run_interactive(
    binary: str,
    args: Sequence[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
) -> int:
    """Runs a command with stdio inherited from the current process.

    For subcommands that need a real terminal (attach, setup-token, an
    interactive mcp/import picker) rather than captured output.
    """
    command = [binary, *args]
    try:
        return subprocess.call(command, cwd=cwd, env=env)
    except FileNotFoundError as exc:
        raise ClaudeNotFoundError(
            f"'{binary}' was not found on PATH. Is Claude Code installed?",
            cmd=redact_command(command),
        ) from exc


def oauth_login(
    binary: str,
    args: Sequence[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    code: Optional[str] = None,
    code_provider: Optional[Callable[[str], str]] = None,
    on_output: Optional[Callable[[str], None]] = None,
    prompt_marker: str = "Paste code here",
    timeout: float = 180,
) -> int:
    """Drives an interactive OAuth login (`claude auth login` / `mcp login`).

    Streams the child's output (forwarding it to `on_output`, if given) until
    it prints its "paste the code" prompt, then writes back `code` — or
    whatever `code_provider(url)` returns, where `url` is the login URL
    found in the output so far. Falls back to `input()` if neither is given.
    Returns the child's exit code.
    """
    command = [binary, *args]
    try:
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        raise ClaudeNotFoundError(
            f"'{binary}' was not found on PATH. Is Claude Code installed?",
            cmd=redact_command(command),
        ) from exc

    assert proc.stdout is not None and proc.stdin is not None
    fd = proc.stdout.fileno()
    buffer = ""
    url: Optional[str] = None
    deadline = time.time() + timeout

    try:
        while time.time() < deadline and proc.poll() is None:
            ready, _, _ = select.select([fd], [], [], 0.5)
            if not ready:
                continue

            chunk = os.read(fd, 4096).decode(errors="replace")
            if not chunk:
                break

            buffer += chunk
            # A login that never reaches its prompt must not grow the buffer
            # without bound; the marker and URL both live near the tail.
            if len(buffer) > _MAX_LOGIN_BUFFER:
                buffer = buffer[-_MAX_LOGIN_BUFFER:]
            if on_output:
                on_output(chunk)

            if url is None:
                match = _URL_PATTERN.search(buffer)
                if match:
                    url = match.group(0)

            if prompt_marker in buffer:
                if code is not None:
                    entered_code = code
                elif code_provider is not None:
                    entered_code = code_provider(url or "")
                else:
                    entered_code = input("\nPaste the code from the browser here: ")

                # Only ever hand the child a single line: a code carrying a
                # newline would otherwise write extra lines into its stdin.
                entered_code = str(entered_code or "").splitlines()
                entered_code = entered_code[0].strip() if entered_code else ""

                proc.stdin.write(entered_code + "\n")
                proc.stdin.flush()
                proc.stdin.close()
                # Drop the code and the captured output rather than holding
                # them in memory for the rest of the call.
                entered_code = ""
                buffer = ""
                break
        else:
            if proc.poll() is None:
                raise ClaudeTimeoutError(
                    f"'{format_command(command)}' did not produce a login prompt within {timeout}s",
                    cmd=redact_command(command),
                )

        drain_deadline = time.time() + 30
        while proc.poll() is None and time.time() < drain_deadline:
            ready, _, _ = select.select([fd], [], [], 0.5)
            if ready:
                chunk = os.read(fd, 4096).decode(errors="replace")
                if not chunk:
                    break
                if on_output:
                    on_output(chunk)

        if proc.poll() is None:
            raise ClaudeTimeoutError(
                f"'{format_command(command)}' did not finish after the code was submitted",
                cmd=redact_command(command),
            )

        return proc.returncode
    finally:
        # Never leave a half-driven login (or its pipes) behind, whatever
        # went wrong — including an exception raised by `code_provider`.
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        for stream in (proc.stdin, proc.stdout):
            try:
                if stream is not None and not stream.closed:
                    stream.close()
            except (OSError, ValueError):
                pass
