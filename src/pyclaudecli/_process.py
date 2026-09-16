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
            cmd=command,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        raise ClaudeTimeoutError(
            f"'{' '.join(command)}' did not finish within {timeout}s",
            cmd=command,
            stdout=stdout,
            stderr=stderr,
        ) from exc

    result = CommandResult(command, completed.returncode, completed.stdout, completed.stderr)
    if check and not result.ok:
        detail = (result.stderr or result.stdout or "").strip()
        raise ClaudeCLIError(
            f"'{' '.join(command)}' exited with {result.returncode}: {detail}",
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            cmd=command,
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
            cmd=command,
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
                f"'{' '.join(command)}' exited with {returncode}",
                returncode=returncode,
                cmd=command,
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
            cmd=command,
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
            cmd=command,
        ) from exc

    assert proc.stdout is not None and proc.stdin is not None
    fd = proc.stdout.fileno()
    buffer = ""
    url: Optional[str] = None
    deadline = time.time() + timeout

    while time.time() < deadline and proc.poll() is None:
        ready, _, _ = select.select([fd], [], [], 0.5)
        if not ready:
            continue

        chunk = os.read(fd, 4096).decode(errors="replace")
        if not chunk:
            break

        buffer += chunk
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
                entered_code = input("\nPaste the code from the browser here: ").strip()

            proc.stdin.write(entered_code + "\n")
            proc.stdin.flush()
            proc.stdin.close()
            buffer = ""
            break
    else:
        if proc.poll() is None:
            proc.kill()
            raise ClaudeTimeoutError(
                f"'{' '.join(command)}' did not produce a login prompt within {timeout}s",
                cmd=command,
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
        proc.kill()
        raise ClaudeTimeoutError(
            f"'{' '.join(command)}' did not finish after the code was submitted",
            cmd=command,
        )

    return proc.returncode
