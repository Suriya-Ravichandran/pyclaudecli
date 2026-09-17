"""`python -m pyclaudecli` — a minimal CLI wrapper for quick scripting.

For anything beyond a one-off prompt, use `pyclaudecli.ClaudeCLI` directly.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional, Tuple

from .client import ClaudeCLI
from .exceptions import (
    ClaudeCLIError,
    ClaudeNotFoundError,
    ClaudeTimeoutError,
    ClaudeUsageError,
)

USAGE = """\
pyclaudecli — send a one-off prompt to Claude Code from the shell.

Usage:
  pyclaudecli [options] <prompt>...
  pyclaudecli [options] -- <prompt>...

Options:
  -m, --model <name>    Model to prompt with (default: haiku)
      --model=<name>    Same, inline form
  -t, --timeout <secs>  Give up on the call after this long
  -h, --help            Show this help and exit
  -V, --version         Show pyclaudecli and claude CLI versions and exit
  --                    Treat everything after this as prompt text

Examples:
  pyclaudecli "What's 2+2?"
  pyclaudecli -m sonnet "Explain this diff"
  pyclaudecli -- "--version"        # prompt about a flag, don't run it

Exit codes:
  0    success
  1    the claude CLI reported an error
  2    bad usage (unknown option, missing prompt)
  124  the call timed out
  127  the claude CLI is not installed or not on PATH
  130  interrupted (Ctrl-C)

This command covers one-shot prompts only. Streaming, background agents, auth,
MCP servers and plugins live in the Python API:

  from pyclaudecli import ClaudeCLI
"""

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_TIMEOUT = 124
EXIT_NOT_FOUND = 127
EXIT_INTERRUPTED = 130
EXIT_BROKEN_PIPE = 141

_HELP_FLAGS = frozenset({"-h", "--help"})
_VERSION_FLAGS = frozenset({"-V", "--version"})


def version_lines() -> List[str]:
    """This library's version, plus the CLI it drives (if it can be found)."""
    from . import __version__

    lines = ["pyclaudecli " + __version__]
    try:
        lines.append("claude CLI " + ClaudeCLI().version())
    except Exception:  # not installed, not on PATH, or not runnable
        lines.append("claude CLI not found on PATH")
    return lines


def _value_for(argv: List[str], index: int, flag: str) -> str:
    if index + 1 >= len(argv):
        raise ClaudeUsageError(
            "Missing value for {0}.".format(flag),
            hint="Example: pyclaudecli {0} <value> \"your prompt\"".format(flag),
        )
    return argv[index + 1]


def parse_args(argv: List[str]) -> Tuple[str, str, Optional[float]]:
    """Returns (model, prompt, timeout). Raises ClaudeUsageError if malformed."""
    model = "haiku"
    timeout: Optional[float] = None
    prompt_parts: List[str] = []
    index = 0

    while index < len(argv):
        arg = argv[index]

        # Everything after `--` is prompt text, dashes and all.
        if arg == "--":
            prompt_parts.extend(argv[index + 1 :])
            break

        if arg in {"--model", "-m"}:
            model = _value_for(argv, index, arg)
            index += 2
            continue

        if arg.startswith("--model="):
            model = arg.split("=", 1)[1]
            index += 1
            continue

        if arg in {"--timeout", "-t"} or arg.startswith("--timeout="):
            raw = arg.split("=", 1)[1] if "=" in arg else _value_for(argv, index, arg)
            try:
                timeout = float(raw)
            except ValueError:
                raise ClaudeUsageError(
                    "--timeout wants a number of seconds, got: {0!r}".format(raw)
                ) from None
            if timeout <= 0:
                raise ClaudeUsageError("--timeout must be greater than zero.")
            index += 1 if "=" in arg else 2
            continue

        # A stray flag is a mistake far more often than it is a prompt, and
        # guessing wrong means a needless API call. Say so instead.
        if arg.startswith("-") and arg != "-":
            raise ClaudeUsageError(
                "Unknown option: {0}".format(arg),
                hint=(
                    "This command understands --model, --timeout, --help and --version.\n"
                    "To prompt with that text instead, put it after --:\n"
                    "  pyclaudecli -- {0}".format(arg)
                ),
            )

        prompt_parts.append(arg)
        index += 1

    prompt = " ".join(prompt_parts).strip()
    if not prompt:
        raise ClaudeUsageError(
            "No prompt given.", hint="Try: pyclaudecli --help"
        )
    return model, prompt, timeout


def _fail(message: str, code: int, hint: Optional[str] = None) -> int:
    """Reports an error the way a command-line tool should, and returns its code."""
    print("pyclaudecli: {0}".format(message), file=sys.stderr)
    if hint:
        print(hint, file=sys.stderr)
    return code


def _dispatch(argv: List[str]) -> int:
    """The actual command, with errors left for `main` to translate."""
    # --help/--version are handled here, never forwarded as a prompt. Only
    # honoured before a `--`, so `pyclaudecli -- --help` still prompts.
    head = argv[: argv.index("--")] if "--" in argv else argv
    if not argv or any(arg in _HELP_FLAGS for arg in head):
        print(USAGE, end="")
        return EXIT_OK
    if any(arg in _VERSION_FLAGS for arg in head):
        print("\n".join(version_lines()))
        return EXIT_OK

    model, prompt, timeout = parse_args(argv)
    # `--` keeps a prompt that starts with a dash from being parsed as flags
    # by the CLI it shells out to.
    args = ["--print", "--model", model, "--", prompt]
    result = ClaudeCLI().run(args, timeout=timeout, check=False)

    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    return result.returncode


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    try:
        return _dispatch(list(argv))

    except ClaudeUsageError as exc:
        return _fail(str(exc), EXIT_USAGE, exc.hint)

    except ClaudeNotFoundError as exc:
        return _fail(
            str(exc),
            EXIT_NOT_FOUND,
            "Install Claude Code, then try again: https://claude.com/claude-code",
        )

    except ClaudeTimeoutError as exc:
        return _fail(str(exc), EXIT_TIMEOUT, "Raise the limit with --timeout <seconds>.")

    except ClaudeCLIError as exc:
        # Anything else the wrapper raises: already redacted, already explained.
        return _fail(str(exc), exc.returncode or EXIT_ERROR)

    except KeyboardInterrupt:
        # Report it the way a shell does, rather than dumping a traceback.
        print("", file=sys.stderr)
        return _fail("interrupted.", EXIT_INTERRUPTED)

    except BrokenPipeError:
        # Downstream went away (`pyclaudecli ... | head`). Retarget stdout so
        # the interpreter does not complain again while shutting down.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except OSError:
            pass
        return EXIT_BROKEN_PIPE

    except OSError as exc:
        # Unreadable cwd, exhausted file handles, and similar.
        return _fail(str(exc), EXIT_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())
