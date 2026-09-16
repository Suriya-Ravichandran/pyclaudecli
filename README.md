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
- [Command-line usage](#command-line-usage)
- [Errors](#errors)
- [`build_flags`](#build_flags)
- [Every method, with an example](#every-method-with-an-example)
- [Development](#development)
- [License](#license)

## Install

```bash
pip install pyclaudecli
```

Requires the `claude` CLI itself to be installed and on `PATH` (see the [Claude Code docs](https://claude.com/claude-code)).

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

## Command-line usage

The package also installs a minimal `pyclaudecli` command (and `python -m pyclaudecli`) for quick one-off prompts — for anything beyond that, use `ClaudeCLI` directly.

```bash
pyclaudecli "What's 2+2?"                    # defaults to model "haiku"
pyclaudecli --model sonnet "Explain this diff"
pyclaudecli -m sonnet "Explain this diff"

python -m pyclaudecli "Hello, Claude!"
```

## Errors

All CLI failures raise `ClaudeCLIError` (or `ClaudeNotFoundError` / `ClaudeTimeoutError`), carrying `returncode`, `stdout`, `stderr`, and `cmd`.

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

# Non-interactive login: supply the code yourself
claude.auth_login(code="123456")

# Or fetch the code programmatically from the printed sign-in URL
claude.auth_login(code_provider=lambda url: fetch_code_from_my_browser(url))

# Route the printed sign-in URL/output somewhere other than stdout
claude.auth_login(on_output=lambda chunk: log.info(chunk), console=True, timeout=120)

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

## Development

```bash
git clone https://github.com/Suriya-Ravichandran/pyclaudecli.git
cd pyclaudecli
pip install -e .
pytest
```

## License

MIT
