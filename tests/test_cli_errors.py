"""Every CLI failure maps to a message on stderr and a documented exit code."""

import pytest

from pyclaudecli import (
    ClaudeCLIError,
    ClaudeNotFoundError,
    ClaudeTimeoutError,
    ClaudeUsageError,
)
from pyclaudecli.__main__ import (
    EXIT_BROKEN_PIPE,
    EXIT_ERROR,
    EXIT_INTERRUPTED,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_TIMEOUT,
    EXIT_USAGE,
    main,
    parse_args,
)


def raising(exc):
    """A ClaudeCLI stand-in whose `run` raises `exc`."""

    class Raiser:
        def __init__(self, *a, **k):
            pass

        def run(self, *a, **k):
            raise exc

    return Raiser


@pytest.fixture(autouse=True)
def no_fd_surgery(monkeypatch):
    """Records the broken-pipe handler's dup2 instead of letting it fire.

    Retargeting stdout to devnull is the right move for a process that is
    about to exit, but it would replace pytest's captured stdout for every
    test that runs afterwards.
    """
    calls = []
    monkeypatch.setattr("os.dup2", lambda *a, **k: calls.append(a))
    return calls


@pytest.fixture
def with_client(monkeypatch):
    import pyclaudecli.__main__ as entry

    def install(exc):
        monkeypatch.setattr(entry, "ClaudeCLI", raising(exc))

    return install


# -- each exception gets its own exit code --------------------------------

def test_not_found_exits_127_with_an_install_hint(with_client, capsys):
    with_client(ClaudeNotFoundError("'claude' was not found on PATH."))
    assert main(["hi"]) == EXIT_NOT_FOUND

    err = capsys.readouterr().err
    assert "pyclaudecli: " in err
    assert "not found on PATH" in err
    assert "claude.com/claude-code" in err


def test_timeout_exits_124_and_suggests_raising_it(with_client, capsys):
    with_client(ClaudeTimeoutError("did not finish within 2.0s"))
    assert main(["hi"]) == EXIT_TIMEOUT
    assert "--timeout" in capsys.readouterr().err


def test_cli_error_exits_with_the_child_returncode(with_client, capsys):
    with_client(ClaudeCLIError("exited with 3", returncode=3))
    assert main(["hi"]) == 3
    assert "exited with 3" in capsys.readouterr().err


def test_cli_error_without_a_returncode_falls_back_to_1(with_client):
    with_client(ClaudeCLIError("something broke"))
    assert main(["hi"]) == EXIT_ERROR


def test_usage_error_exits_2(capsys):
    assert main(["--nope"]) == EXIT_USAGE
    assert "Unknown option" in capsys.readouterr().err


def test_keyboard_interrupt_exits_130(with_client, capsys):
    with_client(KeyboardInterrupt())
    assert main(["hi"]) == EXIT_INTERRUPTED
    assert "interrupted" in capsys.readouterr().err


def test_broken_pipe_exits_141_quietly(with_client, no_fd_surgery, capsys):
    with_client(BrokenPipeError())
    assert main(["hi"]) == EXIT_BROKEN_PIPE
    assert capsys.readouterr().err == ""   # downstream is gone; say nothing
    assert no_fd_surgery, "stdout should be retargeted so shutdown stays quiet"


def test_oserror_exits_1(with_client, capsys):
    with_client(OSError("Too many open files"))
    assert main(["hi"]) == EXIT_ERROR
    assert "Too many open files" in capsys.readouterr().err


# -- no traceback ever reaches the user ----------------------------------

@pytest.mark.parametrize(
    "exc",
    [
        ClaudeNotFoundError("nope"),
        ClaudeTimeoutError("slow"),
        ClaudeCLIError("bad", returncode=7),
        ClaudeUsageError("wrong"),
        KeyboardInterrupt(),
        BrokenPipeError(),
        OSError("disk"),
    ],
)
def test_failures_return_a_code_instead_of_propagating(with_client, exc):
    with_client(exc)
    assert isinstance(main(["hi"]), int)


# -- the --timeout option -------------------------------------------------

def test_timeout_is_parsed_as_seconds():
    assert parse_args(["--timeout", "30", "hi"]) == ("haiku", "hi", 30.0)
    assert parse_args(["-t", "1.5", "hi"]) == ("haiku", "hi", 1.5)
    assert parse_args(["--timeout=45", "hi"]) == ("haiku", "hi", 45.0)


def test_timeout_defaults_to_none():
    assert parse_args(["hi"])[2] is None


@pytest.mark.parametrize("bad", ["abc", "", "1e", "nan-ish"])
def test_non_numeric_timeout_is_rejected(bad):
    with pytest.raises(ClaudeUsageError):
        parse_args(["--timeout", bad, "hi"])


@pytest.mark.parametrize("bad", ["0", "-5", "-0.1"])
def test_non_positive_timeout_is_rejected(bad):
    with pytest.raises(ClaudeUsageError):
        parse_args(["--timeout", bad, "hi"])


def test_timeout_reaches_the_client(monkeypatch):
    import pyclaudecli.__main__ as entry

    seen = {}

    class Recorder:
        def __init__(self, *a, **k):
            pass

        def run(self, args, **kwargs):
            seen.update(kwargs)

            class Result:
                returncode, stdout, stderr = 0, "", ""

            return Result()

    monkeypatch.setattr(entry, "ClaudeCLI", Recorder)
    assert main(["--timeout", "12", "hi"]) == EXIT_OK
    assert seen["timeout"] == 12.0


def test_timeout_after_double_dash_is_prompt_text():
    assert parse_args(["--", "--timeout", "30"]) == ("haiku", "--timeout 30", None)


# -- the usage error type -------------------------------------------------

def test_usage_error_is_a_claude_cli_error():
    """So `except ClaudeCLIError` still catches everything the library raises."""
    assert issubclass(ClaudeUsageError, ClaudeCLIError)


def test_usage_error_carries_returncode_2_and_a_hint():
    exc = ClaudeUsageError("bad flag", hint="try --help")
    assert exc.returncode == EXIT_USAGE
    assert exc.hint == "try --help"


def test_usage_error_hint_is_optional():
    assert ClaudeUsageError("bad flag").hint is None
