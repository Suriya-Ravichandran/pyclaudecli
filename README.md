# pyclaudecli

[![PyPI](https://img.shields.io/pypi/v/pyclaudecli.svg?color=blue)](https://pypi.org/project/pyclaudecli/)
[![Python versions](https://img.shields.io/pypi/pyversions/pyclaudecli.svg)](https://pypi.org/project/pyclaudecli/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Downloads](https://img.shields.io/pypi/dm/pyclaudecli.svg)](https://pypi.org/project/pyclaudecli/)

A Python library that wraps the [Claude Code](https://claude.com/claude-code) CLI (`claude`) so you can drive it from Python instead of shelling out by hand: one-shot prompts, JSON/streaming output, background agents, authentication, MCP servers, plugins, and the rest of the CLI's surface.

It's a thin wrapper, not a reimplementation — every call runs the real `claude` binary, so it always reflects whatever version, auth, and config you have installed locally.

## Contents

- [Install](#install)
- [Quickstart](#quickstart)
- [Setup](#setup)
- [Authentication](#authentication)
- [Command-line usage](#command-line-usage)
- [Errors](#errors)
- [`build_flags`](#build_flags)
- [Security notes](#security-notes)
- [Every method, with an example](#every-method-with-an-example)
- [Development](#development)
- [License](#license)

## Install

```bash
pip install pyclaudecli
```

Requires the `claude` CLI itself to be installed and on `PATH` (see the [Claude Code docs](https://claude.com/claude-code)).

Runs on Linux, macOS and Windows, Python 3.8+. On Windows the CLI is installed as
`claude.cmd`, which `CreateProcess` won't find from a bare `"claude"` — the wrapper
resolves it through `PATHEXT` for you, so the default `ClaudeCLI()` works there too.

## Quickstart

```python
from pyclaudecli import ClaudeCLI

claude = ClaudeCLI()

# One-shot prompt
print(claude.prompt("Summarize this repo's README.", model="haiku"))
```

## Setup

```python
from pyclaudecli import ClaudeCLI

# Defaults: binary="claude" on PATH, inherited cwd/env, no timeout
claude = ClaudeCLI()

# Pointing at a specific binary/project, with a default timeout for every call
claude = ClaudeCLI(
    "claude",
    cwd="/path/to/project",
    env={"ANTHROPIC_API_KEY": "sk-ant-..."},
    timeout=120,
)
```

`env` is merged **over** the current environment, so `PATH`, `HOME` and the rest still
reach the CLI — passing one API key doesn't cost you the ability to find the binary or
its credentials. Pass `replace_env=True` if you really want the child to start from a
clean slate:

```python
claude = ClaudeCLI(env={"PATH": "/usr/bin", "HOME": "/tmp/sandbox"}, replace_env=True)
```

## Authentication

`claude` handles auth itself, so `pyclaudecli` just drives it. You have two options.

### API key

Pass the key through the environment — either inherited from your shell or set per client:

```python
from pyclaudecli import ClaudeCLI

claude = ClaudeCLI(env={"ANTHROPIC_API_KEY": "sk-ant-..."})
```

### OAuth login (paste the code)

`auth_login()` runs `claude auth login`, prints the sign-in URL, waits for the CLI's
"Paste code here" prompt, and writes your code back to it. With no arguments it reads the
code from stdin, so this is the whole interactive flow:

```python
from pyclaudecli import ClaudeCLI

claude = ClaudeCLI()

if not claude.auth_status().get("loggedIn"):
    # Prints the sign-in URL, then asks: "Paste the code from the browser here:"
    exit_code = claude.auth_login()
    print("login exit code:", exit_code)

print(claude.auth_status())   # {"loggedIn": True, "email": "you@example.com", ...}
```

To capture the URL yourself (open it in a browser, send it to a chat, log it) and paste the
code back without stdin, use `on_output` plus `code_provider`:

```python
import re

URL_RE = re.compile(r"https://\S+")
login_url = None

def capture(chunk: str) -> None:
    global login_url
    print(chunk, end="", flush=True)          # or log.info(chunk)
    if login_url is None:
        match = URL_RE.search(chunk)
        if match:
            login_url = match.group(0)

def supply_code(url: str) -> str:
    # `url` is the sign-in URL pyclaudecli found in the CLI's output.
    # Open it however you like, then return the code the browser shows.
    print(f"\nOpen this URL and approve the login:\n{url}\n")
    return input("Paste code here: ").strip()

claude.auth_login(
    on_output=capture,
    code_provider=supply_code,
    console=True,      # --console: force the URL/console flow instead of opening a browser
    timeout=300,       # how long to wait for the "Paste code here" prompt
)
```

Fully non-interactive — when the code already came from somewhere else (a queue, a
browser-automation step, an operator pasting it into your own UI):

```python
claude.auth_login(code="123456")

# Or fetch it programmatically from the printed sign-in URL
claude.auth_login(code_provider=lambda url: fetch_code_from_my_browser(url))

# Enterprise SSO, or pre-filling the account
claude.auth_login(sso=True)
claude.auth_login(email="you@example.com")
```

`auth_login()` returns the CLI's exit code (`0` on success) and raises `ClaudeTimeoutError`
if the login prompt never appears within `timeout` seconds.

Signing out, and long-lived tokens for CI:

```python
claude.auth_logout()
claude.setup_token()   # interactive; sets up a long-lived auth token
```

## Command-line usage

The package also installs a minimal `pyclaudecli` command (and `python -m pyclaudecli`) for quick one-off prompts — for anything beyond that, use `ClaudeCLI` directly.

```bash
pyclaudecli "What's 2+2?"                    # defaults to model "haiku"
pyclaudecli --model sonnet "Explain this diff"
pyclaudecli -m sonnet "Explain this diff"

pyclaudecli --help                            # usage; -h works too
pyclaudecli --version                         # this library + the claude CLI
pyclaudecli --timeout 30 "Explain this diff"  # give up after 30s
pyclaudecli -- "--version"                    # prompt *about* a flag

python -m pyclaudecli "What's 2+2?"
```

`--help` and `--version` are answered locally — they're never forwarded to Claude, so
neither costs an API call. Anything after `--` is prompt text, dashes included. An
unrecognised flag is rejected with a pointer to `--` rather than silently prompted, so a
typo like `--modle sonnet` fails instead of billing you for it. Running `pyclaudecli` with
no arguments prints the usage.

Failures print `pyclaudecli: <what went wrong>` on stderr — never a traceback — and pick
an exit code you can branch on:

| Code | Meaning |
| --- | --- |
| `0` | success |
| `1` | the `claude` CLI reported an error (its own exit code is used when it has one) |
| `2` | bad usage — unknown option, missing value, no prompt |
| `124` | the call exceeded `--timeout` |
| `127` | the `claude` CLI isn't installed or isn't on `PATH` |
| `130` | interrupted with Ctrl-C |
| `141` | the pipe was closed downstream (`pyclaudecli ... \| head`) |

```bash
pyclaudecli --timeout 10 "Summarize this repo" || case $? in
  2)   echo "I typed it wrong" ;;
  124) echo "too slow" ;;
  127) echo "install Claude Code first" ;;
esac
```

## Errors

All CLI failures raise `ClaudeCLIError` (or `ClaudeNotFoundError` / `ClaudeTimeoutError` /
`ClaudeUsageError`), carrying `returncode`, `stdout`, `stderr`, and `cmd`. Every one is a
subclass of `ClaudeCLIError`, so a single `except ClaudeCLIError` catches anything the
library raises.

```python
from pyclaudecli import ClaudeCLI, ClaudeCLIError, ClaudeNotFoundError, ClaudeTimeoutError

claude = ClaudeCLI()

try:
    claude.prompt("Do something", model="haiku", timeout=30)
except ClaudeTimeoutError as exc:
    print("timed out:", exc.cmd)
except ClaudeNotFoundError as exc:
    print("claude binary not on PATH:", exc)
except ClaudeCLIError as exc:
    print(exc.returncode, exc.stdout, exc.stderr)
```

`ClaudeUsageError` is what the `pyclaudecli` command raises for a malformed command line
(`returncode` 2, plus a `hint` naming the fix). It's exported so you can reuse the same
parser and error style in your own wrapper scripts.

## `build_flags`

The helper `ClaudeCLI` uses internally to turn a `{python_name: value}` dict into CLI flags — handy if you're composing your own `extra_flags` or calling `.run()` directly. `None`/`False` are omitted, `True` becomes a bare flag, lists/tuples repeat the flag followed by each value, and anything else becomes the flag plus `str(value)`.

```python
from pyclaudecli import build_flags

build_flags({"model": "haiku", "verbose": True, "quiet": False, "add_dir": ["a", "b"]})
# ["--model", "haiku", "--verbose", "--add-dir", "a", "b"]
```

## Every method, with an example

All examples assume:

```python
from pyclaudecli import ClaudeCLI

claude = ClaudeCLI()
```

### Raw / internal

```python
# .run() — lowest-level call; returns a CommandResult(returncode, stdout, stderr)
result = claude.run(["--version"], check=False)
print(result.returncode, result.stdout)
```

### Version / health

```python
claude.version()   # "claude --version" -> "1.2.3"
claude.doctor()    # "claude doctor" -> health-check report
claude.update()    # "claude update" -> checks for and installs updates

claude.install()                       # "claude install" (latest default)
claude.install("stable")               # "claude install stable"
claude.install("1.2.3", force=True)    # "claude install 1.2.3 --force"
```

### Prompting

```python
# One-shot prompt -> plain text
claude.prompt("Summarize this repo's README.", model="haiku")

# Structured result (cost, session id, etc.)
result = claude.prompt_json("What's 2+2?", model="haiku")
print(result["result"], result["total_cost_usd"])

# Live streaming events
for event in claude.prompt_stream("Write a haiku about tests.", model="haiku"):
    print(event["type"])

# Full option surface
claude.prompt(
    "Refactor this function for clarity.",
    model="sonnet",
    output_format="json",
    system_prompt="You are a terse senior engineer.",
    append_system_prompt="Always answer in bullet points.",
    allowed_tools=["Read", "Edit"],
    disallowed_tools=["Bash"],
    add_dir=["../shared-lib"],
    permission_mode="acceptEdits",
    mcp_config=["./mcp.json"],
    settings="./claude-settings.json",
    resume="session-id-123",
    fork_session=True,
    effort="high",
    fallback_model="haiku",
    max_budget_usd=0.50,
    json_schema='{"type": "object"}',
    betas=["some-beta-flag"],
    no_session_persistence=True,
    dangerously_skip_permissions=False,
    restricted=True,
    input_text="piped stdin content",
    timeout=60,
    extra_flags={"worktree": True},  # anything without a named parameter
)

# continue_session=True appends --continue (keeps typing in the latest session)
claude.prompt("And now add tests for it.", continue_session=True)
```

### Background sessions ("agents")

```python
session_id = claude.start_background("Refactor the auth module", model="sonnet")

claude.list_agents()                          # all sessions, as a list of dicts
claude.list_agents(all=True, cwd="/repo")      # include finished ones, scoped to a project

claude.attach(session_id)                      # interactive; requires a real TTY
claude.logs(session_id)                        # raw terminal snapshot
claude.logs(session_id, strip_ansi=True)       # best-effort plain text

claude.stop(session_id)                        # stop, keep state
claude.respawn(session_id)                     # restart one stopped session
claude.respawn(all=True)                       # restart every stopped session
claude.rm(session_id)                          # delete a stopped session
```

### Auth

```python
claude.auth_status()                # {"loggedIn": True, "email": "...", ...}
claude.auth_status(as_json=False)   # human-readable text instead

# Interactive OAuth: prints the sign-in URL, then reads the pasted code from stdin
claude.auth_login()

# Non-interactive login: supply the code yourself
claude.auth_login(code="123456")

# Or fetch the code programmatically from the printed sign-in URL
claude.auth_login(code_provider=lambda url: fetch_code_from_my_browser(url))

# Route the printed sign-in URL/output somewhere other than stdout
claude.auth_login(on_output=lambda chunk: log.info(chunk), console=True, timeout=120)

claude.auth_login(sso=True)                      # enterprise SSO
claude.auth_login(email="you@example.com")       # pre-fill the account

claude.auth_logout()
claude.setup_token()   # interactive; sets up a long-lived auth token
```

### MCP servers

```python
claude.mcp_list()
claude.mcp_get("sentry")

claude.mcp_add("sentry", "https://mcp.sentry.dev/mcp", transport="http")
claude.mcp_add(
    "local-tool", "node", "server.js",
    transport="stdio", env=["API_KEY=abc"], scope="project",
)

claude.mcp_add_json("sentry", {"type": "http", "url": "https://mcp.sentry.dev/mcp"})
claude.mcp_add_from_claude_desktop(scope="user")

claude.mcp_remove("sentry", scope="project")
claude.mcp_login("sentry")             # interactive OAuth
claude.mcp_logout("sentry")
claude.mcp_reset_project_choices()
```

### Plugins

```python
claude.plugin_list()
claude.plugin_list(as_json=True)

claude.plugin_install("some-plugin", yes=True)
claude.plugin_install("some-plugin@my-marketplace", scope="user", as_json=True)

claude.plugin_uninstall("some-plugin", yes=True, prune=True)
claude.plugin_enable("some-plugin")
claude.plugin_disable("some-plugin")
claude.plugin_disable(all=True)        # disable every plugin

claude.plugin_update("some-plugin", yes=True)
claude.plugin_details("some-plugin")
claude.plugin_validate("./my-plugin", strict=True, as_json=True)
claude.plugin_prune(dry_run=True)

claude.plugin_marketplace_list()
claude.plugin_marketplace_add("https://github.com/org/marketplace-repo")
claude.plugin_marketplace_remove("marketplace-name")
claude.plugin_marketplace_update()             # update all
claude.plugin_marketplace_update("marketplace-name")
```

### Project state

```python
claude.project_purge()                 # purge state for the current project
claude.project_purge("/path/to/repo")  # or for a specific path
```

### Auto mode

```python
claude.auto_mode_config()      # effective classifier config, as a dict
claude.auto_mode_defaults()    # shipped default rules, as a dict
claude.auto_mode_reset()       # remove custom rules from user settings
claude.auto_mode_critique()    # AI feedback on your custom rules
```

### Misc

```python
claude.import_config("cursor", dry_run=True, yes=True)   # source: codex, gemini, or cursor

claude.ultrareview()                                 # review the current branch
claude.ultrareview("main")                            # review against a base branch
claude.ultrareview(482, as_json=True, post=True)       # review a PR, post results, get JSON

# Long-running server: returns a Popen handle, doesn't block
gateway = claude.start_gateway(config="./gateway.json")
...
gateway.terminate()
```

See `ClaudeCLI`'s docstrings for the exact CLI flags behind each method — it covers every top-level `claude` command (`auth`, `mcp`, `plugin`, `project`, `agents`/background sessions, `auto-mode`, `doctor`, `update`, `install`, `import`, `ultrareview`, `gateway`) plus the main prompt flags. Anything not exposed as a named parameter can still be passed through via each method's `extra_flags` dict.

## Security notes

A few things the wrapper does on your behalf, worth knowing if you're feeding it input
from anywhere but your own code:

**Prompts can't smuggle in CLI flags.** `prompt()`, `prompt_stream()`, `start_background()`
and the `pyclaudecli` command put `--` between the options and your text, so a prompt that
starts with a dash is text, not a flag. Without it, user-supplied input like
`--dangerously-skip-permissions` or `--settings /tmp/evil.json` would be parsed by the CLI:

```python
claude.prompt("--version")   # asks Claude about "--version"; does not run the flag
```

Flags you actually want still go through named parameters or `extra_flags`. Note this
protection covers the prompt text — if you interpolate untrusted input into a *flag value*
(`model=`, `settings=`, `add_dir=`), validate it yourself.

**Errors don't spill credentials.** `ClaudeCLIError.args`/`.cmd` and the exception message
are redacted before they're raised, so MCP auth headers, injected `--env` values, tokens
inside an `mcp add-json` payload and anything shaped like `sk-ant-…`, `Bearer …` or
`password=…` come back as `<redacted>`. Flag names survive so the command is still
recognisable, and long values are truncated. Tracebacks and log aggregators get the
redacted form; `exc.stdout`/`exc.stderr` still hold the raw output for local debugging.

**Login codes are handled as single-use secrets.** `auth_login()` writes exactly one line
to the CLI's stdin — a code containing a newline can't inject extra input — and drops the
code and the captured output from memory once it's submitted. The child process and its
pipes are always cleaned up, including when your `code_provider` raises.

Two things it deliberately does *not* do: it never runs a shell (every call is an argv
list, so there's no shell-injection surface), and it doesn't manage credentials itself —
auth lives with the `claude` CLI and your environment. Remember the argv of a running
process is visible to other users on the same machine via `ps`, so prefer env vars over
flags for anything sensitive.

Every call is an argv list on every platform — no shell, and no `shell=True` fallback on
Windows, so quoting rules can't be turned into an injection.

## Development

```bash
git clone https://github.com/Suriya-Ravichandran/pyclaudecli.git
cd pyclaudecli
pip install -e .
pytest          # offline; does not invoke the claude binary
```

## License

MIT
