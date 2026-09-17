"""The `pyclaudecli` command itself: help and version must never become prompts."""

import pytest

from pyclaudecli import ClaudeUsageError
from pyclaudecli.__main__ import main, parse_args, version_lines


class Boom(Exception):
    """Raised if the CLI would have shelled out to claude."""


@pytest.fixture
def no_subprocess(monkeypatch):
    """Fails the test if anything reaches the claude binary."""
    import pyclaudecli.__main__ as entry

    class Guard:
        def __init__(self, *a, **k):
            pass

        def run(self, *a, **k):
            raise Boom("the CLI was invoked")

        def version(self):
            raise Boom("the CLI was invoked")

    monkeypatch.setattr(entry, "ClaudeCLI", Guard)


# -- help -----------------------------------------------------------------

@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_prints_usage_without_prompting(flag, no_subprocess, capsys):
    assert main([flag]) == 0
    out = capsys.readouterr().out
    assert "Usage:" in out
    assert "--model" in out
    assert "pyclaudecli" in out


def test_help_wins_over_other_options(no_subprocess, capsys):
    assert main(["-m", "sonnet", "--help"]) == 0
    assert "Usage:" in capsys.readouterr().out


def test_no_arguments_shows_usage_instead_of_a_default_prompt(no_subprocess, capsys):
    assert main([]) == 0
    assert "Usage:" in capsys.readouterr().out


# -- version --------------------------------------------------------------

@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_version_reports_the_library_version(flag, capsys):
    assert main([flag]) == 0
    out = capsys.readouterr().out

    from pyclaudecli import __version__

    assert "pyclaudecli " + __version__ in out


def test_version_survives_a_missing_claude_binary(no_subprocess, capsys):
    assert main(["--version"]) == 0
    out = capsys.readouterr().out
    assert "pyclaudecli " in out
    assert "not found on PATH" in out


def test_version_lines_reports_both_components(monkeypatch):
    import pyclaudecli.__main__ as entry

    class Fake:
        def version(self):
            return "9.9.9 (Claude Code)"

    monkeypatch.setattr(entry, "ClaudeCLI", lambda *a, **k: Fake())
    lines = version_lines()
    assert lines[0].startswith("pyclaudecli ")
    assert lines[1] == "claude CLI 9.9.9 (Claude Code)"


# -- the `--` escape hatch ------------------------------------------------

def test_double_dash_makes_help_a_prompt():
    assert parse_args(["--", "--help"]) == ("haiku", "--help", None)


def test_double_dash_keeps_the_model_flag():
    assert parse_args(["-m", "sonnet", "--", "--version"]) == ("sonnet", "--version", None)


def test_flags_after_double_dash_are_text():
    assert parse_args(["--", "-m", "sonnet"]) == ("haiku", "-m sonnet", None)


# -- ordinary parsing is unchanged ---------------------------------------

def test_default_model_is_haiku():
    assert parse_args(["hello"]) == ("haiku", "hello", None)


@pytest.mark.parametrize("args", [["-m", "sonnet", "hi"], ["--model", "sonnet", "hi"],
                                  ["--model=sonnet", "hi"]])
def test_model_flag_forms(args):
    assert parse_args(args) == ("sonnet", "hi", None)


def test_prompt_words_are_joined():
    assert parse_args(["explain", "this", "diff"]) == ("haiku", "explain this diff", None)


# -- malformed invocations fail fast, without an API call ----------------

def test_unknown_flag_is_rejected_with_guidance():
    with pytest.raises(ClaudeUsageError) as exc:
        parse_args(["--modle", "sonnet", "hi"])
    assert "--modle" in str(exc.value)
    assert "pyclaudecli -- --modle" in exc.value.hint


def test_typo_flag_does_not_reach_the_api(no_subprocess):
    assert main(["--dangerously-skip-permissions", "hi"]) == 2


def test_missing_model_value_is_rejected():
    with pytest.raises(ClaudeUsageError):
        parse_args(["--model"])


def test_empty_prompt_is_rejected():
    with pytest.raises(ClaudeUsageError) as exc:
        parse_args(["--"])
    assert "No prompt given" in str(exc.value)
