from pyclaudecli import ClaudeCLI, ClaudeCLIError

claude = ClaudeCLI()  # add cwd=..., env=... if needed

# Plain text answer
claude.prompt("Explain this function", model="haiku")

# Structured result: cost, session_id, etc.
result = claude.prompt_json("2+2?", model="haiku")
result["result"], result["total_cost_usd"]

# Live token/event stream
for event in claude.prompt_stream("Write a haiku"):
    print(event["type"])

# Background agent (long-running task)
sid = claude.start_background("Refactor auth module", model="sonnet")
claude.list_agents()
claude.logs(sid, strip_ansi=True)
claude.stop(sid); claude.rm(sid)

# Auth
claude.auth_status()
claude.auth_login()   # prints URL, prompts you for the pasted code

# MCP / plugins
claude.mcp_add("sentry", "https://mcp.sentry.dev/mcp", transport="http")
claude.plugin_install("some-plugin", yes=True)
