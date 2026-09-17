"""Cross-platform behaviour: nothing here is POSIX-only or needs the claude CLI."""

import os
import subprocess
import sys
import textwrap

import pytest

from pyclaudecli import _process
from pyclaudecli._process import _PipeReader, oauth_login, resolve_binary
from pyclaudecli.exceptions import ClaudeTimeoutError


# -- no POSIX-only polling ------------------------------------------------

def test_module_does_not_use_select():
    """`select` accepts only sockets on Windows, so pipes must not rely on it."""
    assert not hasattr(_process, "select")


def test_source_has_no_select_call():
    import inspect

    assert "select.select(" not in inspect.getsource(_process)


# -- binary resolution ----------------------------------------------------

def test_resolve_binary_finds_an_executable_on_path():
    name = "cmd" if os.name == "nt" else "sh"
    resolved = resolve_binary(name)
    assert os.path.isabs(resolved)
    assert os.path.exists(resolved)


def test_resolve_binary_passes_through_unknown_names():
    # Left as-is so the usual ClaudeNotFoundError is what the caller sees.
    assert resolve_binary("definitely-not-installed-xyz") == "definitely-not-installed-xyz"


def test_resolve_binary_leaves_explicit_paths_alone():
    assert resolve_binary(sys.executable) == sys.executable
    assert resolve_binary(os.path.join("some", "dir", "claude")) == os.path.join("some", "dir", "claude")


def test_resolve_binary_honours_a_custom_path(tmp_path):
    name = "fake-claude.bat" if os.name == "nt" else "fake-claude"
    fake = tmp_path / name
    fake.write_text("")
    fake.chmod(0o755)
    assert resolve_binary(name, {"PATH": str(tmp_path)}) == str(fake)


# -- portable pipe reader -------------------------------------------------

def test_pipe_reader_returns_partial_output():
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, b"no trailing newline here")
        reader = _PipeReader(read_fd)
        assert reader.read(2.0) == "no trailing newline here"
    finally:
        os.close(write_fd)


def test_pipe_reader_signals_eof_with_none():
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    assert _PipeReader(read_fd).read(2.0) is None


def test_pipe_reader_returns_empty_string_when_idle():
    read_fd, write_fd = os.pipe()
    try:
        assert _PipeReader(read_fd).read(0.2) == ""
    finally:
        os.close(write_fd)
        os.close(read_fd)


# -- oauth_login driven against a stand-in CLI ----------------------------

def write_fake_cli(tmp_path, body):
    script = tmp_path / "fake_cli.py"
    script.write_text(textwrap.dedent(body))
    return script


PROMPTING_CLI = '''
    import sys
    record = sys.argv[1]
    sys.stdout.write("Open https://claude.ai/oauth/authorize?x=1 in your browser\\n")
    sys.stdout.write("Paste code here: ")   # no newline, like the real prompt
    sys.stdout.flush()
    line = sys.stdin.readline()
    with open(record, "w") as fh:
        fh.write(repr(line))
    sys.stdout.write("\\nLogged in\\n")
    sys.exit(0)
'''


def test_oauth_login_completes_with_a_supplied_code(tmp_path):
    record = tmp_path / "received.txt"
    script = write_fake_cli(tmp_path, PROMPTING_CLI)

    seen = []
    rc = oauth_login(
        sys.executable,
        [str(script), str(record)],
        code="123456",
        on_output=seen.append,
        timeout=30,
    )

    assert rc == 0
    assert record.read_text() == repr("123456\n")   # exactly one line, no stray CR
    assert "claude.ai/oauth" in "".join(seen)


def test_oauth_login_passes_the_url_to_code_provider(tmp_path):
    record = tmp_path / "received.txt"
    script = write_fake_cli(tmp_path, PROMPTING_CLI)
    urls = []

    def provider(url):
        urls.append(url)
        return "abc999"

    assert oauth_login(sys.executable, [str(script), str(record)],
                       code_provider=provider, on_output=lambda _: None, timeout=30) == 0
    assert urls and urls[0].startswith("https://claude.ai/oauth/authorize")
    assert record.read_text() == repr("abc999\n")


def test_oauth_login_sends_only_the_first_line(tmp_path):
    record = tmp_path / "received.txt"
    script = write_fake_cli(tmp_path, PROMPTING_CLI)

    oauth_login(sys.executable, [str(script), str(record)],
                code="code1\nrm -rf /\n", on_output=lambda _: None, timeout=30)

    assert record.read_text() == repr("code1\n")


def test_oauth_login_times_out_and_kills_the_child(tmp_path):
    script = write_fake_cli(tmp_path, '''
        import time
        time.sleep(30)
    ''')

    with pytest.raises(ClaudeTimeoutError):
        oauth_login(sys.executable, [str(script)], code="x",
                    on_output=lambda _: None, timeout=1.5)


def test_oauth_login_cleans_up_when_code_provider_raises(tmp_path):
    record = tmp_path / "received.txt"
    script = write_fake_cli(tmp_path, PROMPTING_CLI)

    def boom(url):
        raise RuntimeError("no code available")

    with pytest.raises(RuntimeError):
        oauth_login(sys.executable, [str(script), str(record)],
                    code_provider=boom, on_output=lambda _: None, timeout=30)


# -- the plain runners still work through the same resolution -------------

def test_run_executes_a_resolved_binary(tmp_path):
    script = write_fake_cli(tmp_path, '''
        print("hello from the stand-in CLI")
    ''')
    result = _process.run(sys.executable, [str(script)])
    assert result.ok
    assert "hello from the stand-in CLI" in result.stdout


def test_stream_lines_yields_output(tmp_path):
    script = write_fake_cli(tmp_path, '''
        for i in range(3):
            print("line", i, flush=True)
    ''')
    lines = list(_process.stream_lines(sys.executable, [str(script)]))
    assert lines == ["line 0", "line 1", "line 2"]


def test_start_gateway_resolves_its_binary(monkeypatch):
    """The gateway builds its own Popen, so it needs the same resolution."""
    import subprocess as sp

    from pyclaudecli import ClaudeCLI

    seen = {}

    def fake_popen(args, **kwargs):
        seen["args"] = args
        return object()

    monkeypatch.setattr(sp, "Popen", fake_popen)
    ClaudeCLI("sh" if os.name != "nt" else "cmd").start_gateway()

    assert os.path.isabs(seen["args"][0])
    assert seen["args"][1] == "gateway"
