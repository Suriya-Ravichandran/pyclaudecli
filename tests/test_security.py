"""Regression tests for the hardening in 1.0.3 — all offline, no `claude` needed."""

import os

import pytest

from pyclaudecli import ClaudeCLI, build_flags
from pyclaudecli._process import format_command, redact_arg, redact_command


class RecordingCLI(ClaudeCLI):
    """Captures the argv a method would run instead of executing it."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls = []

    def run(self, args, **kwargs):
        self.calls.append(list(args))
        raise AssertionError("not executed")


def argv_for(method, *args, **kwargs):
    client = RecordingCLI()
    with pytest.raises(AssertionError):
        getattr(client, method)(*args, **kwargs)
    return client.calls[-1]


# -- argument injection ---------------------------------------------------

def test_prompt_separates_options_from_text():
    argv = argv_for("prompt", "--version")
    assert argv[-2:] == ["--", "--version"]


def test_prompt_separator_comes_after_continue():
    argv = argv_for("prompt", "-h", continue_session=True)
    assert argv.index("--continue") < argv.index("--")


@pytest.mark.parametrize(
    "hostile",
    ["--version", "--dangerously-skip-permissions", "-p", "--settings=/tmp/evil.json"],
)
def test_hostile_prompts_stay_positional(hostile):
    argv = argv_for("prompt", hostile)
    assert argv[-1] == hostile
    assert argv[argv.index("--") + 1] == hostile


def test_start_background_separates_task():
    argv = argv_for("start_background", "--version")
    assert argv[-2:] == ["--", "--version"]


def test_module_entrypoint_separates_prompt():
    from pyclaudecli.__main__ import main

    captured = {}

    class Fake(ClaudeCLI):
        def run(self, args, **kwargs):
            captured["argv"] = list(args)
            raise SystemExit(0)

    import pyclaudecli.__main__ as entry

    original = entry.ClaudeCLI
    entry.ClaudeCLI = Fake
    try:
        with pytest.raises(SystemExit):
            # `--` is the entrypoint's own escape hatch; --version alone is
            # handled locally now (see tests/test_cli.py).
            main(["--", "--version"])
    finally:
        entry.ClaudeCLI = original

    assert captured["argv"][-2:] == ["--", "--version"]


# -- secret redaction -----------------------------------------------------

def test_redacts_values_of_credential_flags():
    argv = ["claude", "mcp", "add", "--header", "Authorization: Bearer tok123", "s", "https://x"]
    safe = redact_command(argv)
    assert "tok123" not in " ".join(safe)
    assert "--header" in safe  # flag names stay, for debuggability


def test_redacts_env_flag_values():
    safe = format_command(["claude", "mcp", "add", "--env", "API_KEY=supersecret", "s", "cmd"])
    assert "supersecret" not in safe


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-abcdef123456",
        "pypi-AgEIcHlwaS5vcmcXYZ",
        "ghp_abcdefghijklmnop",
        '{"token": "abcdef123456"}',
        "password=hunter2",
    ],
)
def test_redacts_credential_shapes_anywhere(secret):
    assert secret not in redact_arg(secret)
    assert "<redacted>" in redact_arg(secret)


def test_add_json_payload_is_redacted():
    payload = '{"type":"http","url":"https://x","headers":{"Authorization":"Bearer sk-ant-abc123"}}'
    assert "sk-ant-abc123" not in format_command(["claude", "mcp", "add-json", "s", payload])


def test_long_arguments_are_truncated():
    assert len(redact_arg("a" * 5000)) < 200


def test_ordinary_arguments_survive():
    argv = ["claude", "--print", "--model", "haiku", "--", "Summarize this repo"]
    assert redact_command(argv) == argv


# -- environment handling -------------------------------------------------

def test_env_is_merged_over_os_environ_by_default():
    env = ClaudeCLI(env={"ANTHROPIC_API_KEY": "sk-ant-x"})._env()
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-x"
    assert env.get("PATH") == os.environ.get("PATH")


def test_replace_env_gives_a_clean_slate():
    env = ClaudeCLI(env={"ANTHROPIC_API_KEY": "sk-ant-x"}, replace_env=True)._env()
    assert env == {"ANTHROPIC_API_KEY": "sk-ant-x"}


def test_no_env_means_inherit():
    assert ClaudeCLI()._env() is None


# -- unchanged behaviour --------------------------------------------------

def test_build_flags_still_builds_flags():
    assert build_flags({"model": "haiku", "verbose": True, "quiet": False, "add_dir": ["a", "b"]}) == [
        "--model", "haiku", "--verbose", "--add-dir", "a", "b",
    ]


def test_cli_stderr_is_redacted_in_error_messages():
    from pyclaudecli._process import redact_arg

    stderr = 'invalid header "Authorization: Bearer sk-ant-leak123"'
    assert "sk-ant-leak123" not in redact_arg(stderr, limit=2000)


def test_detail_redaction_keeps_long_errors_readable():
    from pyclaudecli._process import redact_arg

    long_error = "error: " + ("context " * 100)
    assert len(redact_arg(long_error, limit=2000)) > 500
