# pyclaudecli

A Python library that wraps the [Claude Code](https://claude.com/claude-code) CLI (`claude`) so you can drive it from Python instead of shelling out by hand: one-shot prompts, JSON/streaming output, background agents, authentication, MCP servers, plugins, and the rest of the CLI's surface.

It's a thin wrapper, not a reimplementation — every call runs the real `claude` binary, so it always reflects whatever version, auth, and config you have installed locally.

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

# Structured result (cost, session id, etc.)
result = claude.prompt_json("What's 2+2?", model="haiku")
print(result["result"], result["total_cost_usd"])

# Live streaming events
for event in claude.prompt_stream("Write a haiku about tests.", model="haiku"):
    print(event["type"])
```

## Background agents

```python
session_id = claude.start_background("Refactor the auth module", model="sonnet")
claude.list_agents()
claude.logs(session_id, strip_ansi=True)
claude.stop(session_id)
claude.rm(session_id)
```

## Auth

```python
claude.auth_status()  # {"loggedIn": True, "email": "...", ...}

# Prints the sign-in URL, then forwards the pasted code to finish login
claude.auth_login()
```

## MCP servers and plugins

```python
claude.mcp_add("sentry", "https://mcp.sentry.dev/mcp", transport="http")
claude.mcp_list()

claude.plugin_install("some-plugin", yes=True)
claude.plugin_list(as_json=True)
```

See `ClaudeCLI`'s docstrings for the full method list — it covers every top-level `claude` command (`auth`, `mcp`, `plugin`, `project`, `agents`/background sessions, `auto-mode`, `doctor`, `update`, `install`, `import`, `ultrareview`, `gateway`) plus the main prompt flags. Anything not exposed as a named parameter can still be passed through via each method's `extra_flags` dict.

## Errors

All CLI failures raise `ClaudeCLIError` (or `ClaudeNotFoundError` / `ClaudeTimeoutError`), carrying `returncode`, `stdout`, and `stderr`.

## License

MIT
