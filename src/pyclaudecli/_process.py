"""Low-level process plumbing shared by ClaudeCLI's methods."""

from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import threading
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


def resolve_binary(binary: str, env: Optional[dict] = None) -> str:
    """Finds the executable to run, the same way a shell would.

    On Windows the `claude` CLI is an npm shim (`claude.cmd`), and
    CreateProcess only ever appends `.exe` — so a bare "claude" is not found
    unless it is resolved through PATHEXT first. `shutil.which` handles that,
    and on POSIX it is a no-op beyond returning the absolute path.

    Falls back to the name as given (an explicit path, or something the OS can
    still resolve), so the usual ClaudeNotFoundError is what callers see.
    """
    if os.path.dirname(binary):
        return binary
    path = (env or os.environ).get("PATH")
    return shutil.which(binary, path=path) or binary


class _PipeReader:
    """Reads a child's stdout from a thread, so waiting works everywhere.

    `select` only accepts sockets on Windows, so it cannot be used to poll a
    subprocess pipe. A daemon thread doing blocking reads is portable, and
    still hands back partial output the moment it arrives — which matters for
    a login prompt that never ends in a newline.
    """

    _EOF = object()

    def __init__(self, fd: int) -> None:
        self._fd = fd
        self._chunks: "queue.Queue" = queue.Queue()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        try:
            while True:
                data = os.read(self._fd, 4096)
                if not data:
                    break
                self._chunks.put(data)
        except (OSError, ValueError):
            pass  # pipe closed underneath us; treated as EOF
        finally:
            self._chunks.put(self._EOF)

    def read(self, timeout: float) -> Optional[str]:
        """Returns decoded output, "" if nothing arrived in time, None at EOF."""
        try:
            item = self._chunks.get(timeout=timeout)
        except queue.Empty:
            return ""
        if item is self._EOF:
            return None
        return item.decode("utf-8", errors="replace")


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
    command = [resolve_binary(binary, env), *args]
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
    command = [resolve_binary(binary, env), *args]
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
    command = [resolve_binary(binary, env), *args]
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
    command = [resolve_binary(binary, env), *args]
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
    # Send exactly "\n", not the platform line ending: on Windows text mode
    # would translate it to "\r\n" and the CLI would read a stray CR.
    if hasattr(proc.stdin, "reconfigure"):
        proc.stdin.reconfigure(newline="\n")
    reader = _PipeReader(proc.stdout.fileno())
    buffer = ""
    url: Optional[str] = None
    deadline = time.time() + timeout

    try:
        while time.time() < deadline and proc.poll() is None:
            chunk = reader.read(0.5)
            if chunk is None:  # the child closed its output
                break
            if not chunk:
                continue

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
            chunk = reader.read(0.5)
            if chunk is None:
                break
            if chunk and on_output:
                on_output(chunk)

        # Reaching EOF on stdout does not mean the child has exited yet, so
        # give it a moment to actually finish rather than calling it a timeout.
        try:
            return proc.wait(timeout=max(drain_deadline - time.time(), 5))
        except subprocess.TimeoutExpired:
            raise ClaudeTimeoutError(
                f"'{format_command(command)}' did not finish after the code was submitted",
                cmd=redact_command(command),
            ) from None
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
