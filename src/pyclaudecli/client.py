"""ClaudeCLI: a Python wrapper around every `claude` CLI command."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Union

from . import _process
from .exceptions import ClaudeCLIError

_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07")


def _kebab(name: str) -> str:
    return "--" + name.replace("_", "-")


def build_flags(options: Dict[str, Any]) -> List[str]:
    """Converts a {python_name: value} dict into CLI flags.

    None/False -> omitted. True -> bare flag. list/tuple -> the flag once,
    followed by each value (matches commander.js variadic `<x...>` options).
    Anything else -> the flag followed by str(value).
    """
    flags: List[str] = []
    for key, value in options.items():
        if value is None or value is False:
            continue
        flag = _kebab(key)
        if value is True:
            flags.append(flag)
        elif isinstance(value, (list, tuple)):
            if not value:
                continue
            flags.append(flag)
            flags.extend(str(v) for v in value)
        else:
            flags.append(flag)
            flags.append(str(value))
    return flags


class ClaudeCLI:
    """Wraps the `claude` CLI (Claude Code) for programmatic use.

    Every method shells out to the real `claude` binary, so whatever is
    installed and authenticated on this machine is what runs. Methods that
    capture output raise `ClaudeCLIError` (or a subclass) on a non-zero exit;
    pass `check=False` to a raw call via `.run()` if you'd rather inspect the
    result yourself.
    """

    def __init__(
        self,
        binary: str = "claude",
        *,
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self.binary = binary
        self.cwd = cwd
        self.env = env
        self.timeout = timeout

    # -- internals -----------------------------------------------------

    def run(
        self,
        args: Sequence[str],
        *,
        input_text: Optional[str] = None,
        timeout: Optional[float] = None,
        check: bool = True,
    ) -> _process.CommandResult:
        """Runs `claude <args>` and returns the captured result."""
        return _process.run(
            self.binary,
            args,
            cwd=self.cwd,
            env=self.env,
            input_text=input_text,
            timeout=timeout if timeout is not None else self.timeout,
            check=check,
        )

    def _text(self, args: Sequence[str], **kwargs: Any) -> str:
        return self.run(args, **kwargs).stdout

    def _json(self, args: Sequence[str], **kwargs: Any) -> Any:
        result = self.run(args, **kwargs)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ClaudeCLIError(
                f"Expected JSON from `{self.binary} {' '.join(args)}`, "
                f"got: {result.stdout[:200]!r}",
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                cmd=[self.binary, *args],
            ) from exc

    def _interactive(self, args: Sequence[str]) -> int:
        return _process.run_interactive(self.binary, args, cwd=self.cwd, env=self.env)

    # -- version / health ------------------------------------------------

    def version(self) -> str:
        """`claude --version`"""
        return self._text(["--version"]).strip()

    def doctor(self) -> str:
        """`claude doctor` — health-checks the local installation."""
        return self._text(["doctor"])

    def update(self) -> str:
        """`claude update` — checks for and installs updates."""
        return self._text(["update"])

    def install(self, target: Optional[str] = None, *, force: bool = False) -> str:
        """`claude install [target]` (target: stable, latest, or a version)."""
        args = ["install"] + ([target] if target else []) + build_flags({"force": force})
        return self._text(args)

    # -- prompting (non-interactive / --print) ----------------------------

    def prompt(
        self,
        text: str,
        *,
        model: Optional[str] = None,
        output_format: Optional[str] = None,
        system_prompt: Optional[str] = None,
        append_system_prompt: Optional[str] = None,
        allowed_tools: Optional[Sequence[str]] = None,
        disallowed_tools: Optional[Sequence[str]] = None,
        tools: Optional[Sequence[str]] = None,
        add_dir: Optional[Sequence[str]] = None,
        permission_mode: Optional[str] = None,
        permission_prompts: Optional[str] = None,
        mcp_config: Optional[Sequence[str]] = None,
        settings: Optional[str] = None,
        session_id: Optional[str] = None,
        resume: Optional[str] = None,
        continue_session: bool = False,
        fork_session: bool = False,
        effort: Optional[str] = None,
        fallback_model: Optional[str] = None,
        max_budget_usd: Optional[float] = None,
        json_schema: Optional[str] = None,
        betas: Optional[Sequence[str]] = None,
        no_session_persistence: bool = False,
        dangerously_skip_permissions: bool = False,
        restricted: bool = False,
        input_text: Optional[str] = None,
        timeout: Optional[float] = None,
        extra_flags: Optional[Dict[str, Any]] = None,
    ) -> Union[str, dict]:
        """Runs a single non-interactive prompt (`claude --print ...`).

        Returns the response text, or the parsed JSON result object when
        `output_format="json"`. Anything not exposed as a named parameter
        (e.g. `--cloud`, `--worktree`, `--file`) can be passed via
        `extra_flags={"worktree": True}`.
        """
        options = dict(
            model=model,
            output_format=output_format,
            system_prompt=system_prompt,
            append_system_prompt=append_system_prompt,
            allowed_tools=allowed_tools,
            disallowed_tools=disallowed_tools,
            tools=tools,
            add_dir=add_dir,
            permission_mode=permission_mode,
            permission_prompts=permission_prompts,
            mcp_config=mcp_config,
            settings=settings,
            session_id=session_id,
            resume=resume,
            fork_session=fork_session,
            effort=effort,
            fallback_model=fallback_model,
            max_budget_usd=max_budget_usd,
            json_schema=json_schema,
            betas=betas,
            no_session_persistence=no_session_persistence,
            dangerously_skip_permissions=dangerously_skip_permissions,
            restricted=restricted,
        )
        options.update(extra_flags or {})
        if options.get("output_format") == "stream-json":
            options["verbose"] = True  # required by the CLI for --print + stream-json

        args = ["--print"] + build_flags(options)
        if continue_session:
            args.append("--continue")
        args.append(text)

        result = self.run(args, input_text=input_text, timeout=timeout)
        if output_format == "json":
            return json.loads(result.stdout)
        return result.stdout

    def prompt_json(self, text: str, **kwargs: Any) -> dict:
        """`prompt()` forced to `--output-format json`; returns the parsed dict."""
        kwargs["output_format"] = "json"
        return self.prompt(text, **kwargs)  # type: ignore[return-value]

    def prompt_stream(self, text: str, **kwargs: Any) -> Iterator[dict]:
        """`prompt()` with `--output-format stream-json`; yields each event dict."""
        extra_flags = dict(kwargs.pop("extra_flags", None) or {})
        extra_flags.update(kwargs)
        extra_flags["output_format"] = "stream-json"
        extra_flags["verbose"] = True  # required by the CLI for --print + stream-json

        options = {k: v for k, v in extra_flags.items() if v is not None and v is not False}
        args = ["--print"] + build_flags(options) + [text]
        for line in _process.stream_lines(self.binary, args, cwd=self.cwd, env=self.env):
            line = line.strip()
            if line:
                yield json.loads(line)

    # -- background sessions ("agents") -----------------------------------

    def start_background(
        self,
        task: str,
        *,
        model: Optional[str] = None,
        name: Optional[str] = None,
        resume: Optional[str] = None,
        extra_flags: Optional[Dict[str, Any]] = None,
    ) -> str:
        """`claude --bg <task>`; returns the short session id it prints."""
        options = dict(model=model, name=name, resume=resume)
        options.update(extra_flags or {})
        args = ["--bg"] + build_flags(options) + [task]
        output = self._text(args)
        match = re.search(r"backgrounded\W*([0-9a-fA-F]+)", output)
        if not match:
            raise ClaudeCLIError(
                f"Could not find a session id in `claude --bg` output: {output!r}",
                stdout=output,
                cmd=[self.binary, *args],
            )
        return match.group(1)

    def list_agents(self, *, all: bool = False, cwd: Optional[str] = None) -> List[dict]:
        """`claude agents --json`; lists interactive and background sessions."""
        args = ["agents", "--json"] + build_flags({"all": all, "cwd": cwd})
        return self._json(args)

    def attach(self, session_id: str) -> int:
        """`claude attach <id>` — opens a background session in this terminal.

        Requires a real TTY (stdio is inherited, not captured).
        """
        return self._interactive(["attach", session_id])

    def logs(self, session_id: str, *, strip_ansi: bool = False) -> str:
        """`claude logs <id>` — a raw terminal snapshot of recent output.

        Pass `strip_ansi=True` for a best-effort plain-text version.
        """
        text = self._text(["logs", session_id])
        return _ANSI_PATTERN.sub("", text) if strip_ansi else text

    def stop(self, session_id: str) -> str:
        """`claude stop <id>` — stops a background session (keeps its state)."""
        return self._text(["stop", session_id])

    def rm(self, session_id: str) -> str:
        """`claude rm <id>` — deletes a (stopped) background session."""
        return self._text(["rm", session_id])

    def respawn(self, session_id: Optional[str] = None, *, all: bool = False) -> str:
        """`claude respawn [id]` / `claude respawn --all`."""
        args = ["respawn"] + ([session_id] if session_id else []) + build_flags({"all": all})
        return self._text(args)

    # -- auth --------------------------------------------------------------

    def auth_status(self, *, as_json: bool = True) -> Union[dict, str]:
        """`claude auth status`."""
        if as_json:
            return self._json(["auth", "status", "--json"])
        return self._text(["auth", "status", "--text"])

    def auth_login(
        self,
        *,
        email: Optional[str] = None,
        console: bool = False,
        sso: bool = False,
        code: Optional[str] = None,
        code_provider: Optional[Callable[[str], str]] = None,
        on_output: Optional[Callable[[str], None]] = None,
        timeout: float = 180,
    ) -> int:
        """Drives `claude auth login` end to end.

        Prints (via `on_output`, or stdout if not given) the sign-in URL for
        you to open and complete in a browser, then forwards the resulting
        code back to the CLI. Pass `code` to supply it non-interactively, or
        `code_provider(url)` to fetch it programmatically (e.g. from your own
        browser-automation step); otherwise it's read from stdin.
        """
        args = ["auth", "login"]
        args += build_flags({"console": console, "sso": sso, "email": email})
        return _process.oauth_login(
            self.binary,
            args,
            cwd=self.cwd,
            env=self.env,
            code=code,
            code_provider=code_provider,
            on_output=on_output or (lambda chunk: print(chunk, end="", flush=True)),
            timeout=timeout,
        )

    def auth_logout(self) -> str:
        """`claude auth logout`."""
        return self._text(["auth", "logout"])

    def setup_token(self) -> int:
        """`claude setup-token` — sets up a long-lived auth token.

        Interactive (may involve a browser step); stdio is inherited.
        """
        return self._interactive(["setup-token"])

    # -- MCP servers ---------------------------------------------------------

    def mcp_list(self) -> str:
        """`claude mcp list`."""
        return self._text(["mcp", "list"])

    def mcp_get(self, name: str) -> str:
        """`claude mcp get <name>`."""
        return self._text(["mcp", "get", name])

    def mcp_add(
        self,
        name: str,
        command_or_url: str,
        *args: str,
        transport: Optional[str] = None,
        header: Optional[Sequence[str]] = None,
        env: Optional[Sequence[str]] = None,
        scope: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: bool = False,
        callback_port: Optional[int] = None,
    ) -> str:
        """`claude mcp add <name> <commandOrUrl> [args...]`."""
        options = build_flags(
            dict(
                transport=transport,
                header=header,
                env=env,
                scope=scope,
                client_id=client_id,
                client_secret=client_secret,
                callback_port=callback_port,
            )
        )
        return self._text(["mcp", "add", *options, name, command_or_url, *args])

    def mcp_add_json(
        self,
        name: str,
        config: Union[str, dict],
        *,
        scope: Optional[str] = None,
        client_secret: bool = False,
    ) -> str:
        """`claude mcp add-json <name> <json>`. `config` may be a dict or JSON string."""
        payload = json.dumps(config) if isinstance(config, dict) else config
        options = build_flags({"scope": scope, "client_secret": client_secret})
        return self._text(["mcp", "add-json", *options, name, payload])

    def mcp_add_from_claude_desktop(self, *, scope: Optional[str] = None) -> str:
        """`claude mcp add-from-claude-desktop` (Mac and WSL only)."""
        return self._text(["mcp", "add-from-claude-desktop", *build_flags({"scope": scope})])

    def mcp_remove(self, name: str, *, scope: Optional[str] = None) -> str:
        """`claude mcp remove <name>`."""
        return self._text(["mcp", "remove", *build_flags({"scope": scope}), name])

    def mcp_login(self, name: str, *, no_browser: bool = False) -> int:
        """`claude mcp login <name>` — interactive OAuth for an MCP server."""
        return self._interactive(["mcp", "login", *build_flags({"no_browser": no_browser}), name])

    def mcp_logout(self, name: str) -> str:
        """`claude mcp logout <name>`."""
        return self._text(["mcp", "logout", name])

    def mcp_reset_project_choices(self) -> str:
        """`claude mcp reset-project-choices`."""
        return self._text(["mcp", "reset-project-choices"])

    # -- plugins ---------------------------------------------------------------

    def plugin_list(self, *, as_json: bool = False) -> Union[str, list]:
        """`claude plugin list`."""
        args = ["plugin", "list"] + build_flags({"json": as_json})
        return self._json(args) if as_json else self._text(args)

    def plugin_install(
        self,
        plugin: str,
        *,
        scope: Optional[str] = None,
        yes: bool = False,
        config: Optional[Sequence[str]] = None,
        accept_command: Optional[str] = None,
        as_json: bool = False,
    ) -> Union[str, dict]:
        """`claude plugin install <plugin>` (use `plugin@marketplace` to pin one)."""
        options = build_flags(
            dict(scope=scope, yes=yes, config=config, accept_command=accept_command, json=as_json)
        )
        args = ["plugin", "install", *options, plugin]
        return self._json(args) if as_json else self._text(args)

    def plugin_uninstall(
        self,
        plugin: str,
        *,
        scope: Optional[str] = None,
        keep_data: bool = False,
        prune: bool = False,
        yes: bool = False,
        as_json: bool = False,
    ) -> Union[str, dict]:
        """`claude plugin uninstall <plugin>`."""
        options = build_flags(
            dict(scope=scope, keep_data=keep_data, prune=prune, yes=yes, json=as_json)
        )
        args = ["plugin", "uninstall", *options, plugin]
        return self._json(args) if as_json else self._text(args)

    def plugin_enable(self, plugin: str, *, scope: Optional[str] = None, as_json: bool = False) -> Union[str, dict]:
        """`claude plugin enable <plugin>`."""
        args = ["plugin", "enable", *build_flags({"scope": scope, "json": as_json}), plugin]
        return self._json(args) if as_json else self._text(args)

    def plugin_disable(
        self,
        plugin: Optional[str] = None,
        *,
        all: bool = False,
        scope: Optional[str] = None,
        as_json: bool = False,
    ) -> Union[str, dict]:
        """`claude plugin disable [plugin]` (or `all=True` for every plugin)."""
        options = build_flags({"all": all, "scope": scope, "json": as_json})
        args = ["plugin", "disable", *options] + ([plugin] if plugin else [])
        return self._json(args) if as_json else self._text(args)

    def plugin_update(
        self,
        plugin: str,
        *,
        scope: Optional[str] = None,
        yes: bool = False,
        accept_command: Optional[str] = None,
        as_json: bool = False,
    ) -> Union[str, dict]:
        """`claude plugin update <plugin>`."""
        options = build_flags(dict(scope=scope, yes=yes, accept_command=accept_command, json=as_json))
        args = ["plugin", "update", *options, plugin]
        return self._json(args) if as_json else self._text(args)

    def plugin_details(self, name: str) -> str:
        """`claude plugin details <name>`."""
        return self._text(["plugin", "details", name])

    def plugin_validate(self, path: str, *, strict: bool = False, as_json: bool = False) -> Union[str, dict]:
        """`claude plugin validate <path>`."""
        args = ["plugin", "validate", *build_flags({"strict": strict, "json": as_json}), path]
        return self._json(args) if as_json else self._text(args)

    def plugin_prune(self, *, scope: Optional[str] = None, yes: bool = False, dry_run: bool = False) -> str:
        """`claude plugin prune` — removes orphaned auto-installed dependencies."""
        args = ["plugin", "prune", *build_flags({"scope": scope, "yes": yes, "dry_run": dry_run})]
        return self._text(args)

    def plugin_marketplace_list(self) -> str:
        """`claude plugin marketplace list`."""
        return self._text(["plugin", "marketplace", "list"])

    def plugin_marketplace_add(self, source: str) -> str:
        """`claude plugin marketplace add <source>` (URL, path, or GitHub repo)."""
        return self._text(["plugin", "marketplace", "add", source])

    def plugin_marketplace_remove(self, name: str) -> str:
        """`claude plugin marketplace remove <name>`."""
        return self._text(["plugin", "marketplace", "remove", name])

    def plugin_marketplace_update(self, name: Optional[str] = None) -> str:
        """`claude plugin marketplace update [name]` (updates all if omitted)."""
        return self._text(["plugin", "marketplace", "update"] + ([name] if name else []))

    # -- project state -----------------------------------------------------

    def project_purge(self, path: Optional[str] = None) -> str:
        """`claude project purge [path]` — deletes all local state for a project."""
        return self._text(["project", "purge"] + ([path] if path else []))

    # -- auto mode -----------------------------------------------------------

    def auto_mode_config(self) -> dict:
        """`claude auto-mode config` — the effective classifier config as JSON."""
        return self._json(["auto-mode", "config"])

    def auto_mode_defaults(self) -> dict:
        """`claude auto-mode defaults` — the shipped default rules as JSON."""
        return self._json(["auto-mode", "defaults"])

    def auto_mode_reset(self) -> str:
        """`claude auto-mode reset` — removes custom rules from user settings."""
        return self._text(["auto-mode", "reset"])

    def auto_mode_critique(self) -> str:
        """`claude auto-mode critique` — AI feedback on your custom rules."""
        return self._text(["auto-mode", "critique"])

    # -- misc ---------------------------------------------------------------

    def import_config(
        self,
        source: str,
        *,
        dry_run: bool = False,
        yes: Union[bool, str, None] = None,
    ) -> str:
        """`claude import <source>` (source: codex, gemini, or cursor).

        Pass `dry_run=True` and/or `yes=True` (or a digest string) for
        non-interactive use; otherwise the CLI may prompt interactively.
        """
        args = ["import", source] + build_flags({"dry_run": dry_run, "yes": yes})
        return self._text(args)

    def ultrareview(
        self,
        target: Optional[str] = None,
        *,
        as_json: bool = False,
        post: bool = False,
        timeout_minutes: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> Union[str, dict]:
        """`claude ultrareview [target]` — cloud multi-agent code review.

        `target` is a PR number or base branch; omit it to review the current
        branch. `timeout` (seconds) bounds this call locally; `timeout_minutes`
        is the CLI's own remote-review budget (default 45).
        """
        options = build_flags({"json": as_json, "post": post, "timeout": timeout_minutes})
        args = ["ultrareview", *options] + ([target] if target else [])
        result = self.run(args, timeout=timeout)
        if as_json:
            return json.loads(result.stdout)
        return result.stdout

    def start_gateway(self, *, config: Optional[str] = None):
        """`claude gateway` — starts the enterprise auth/telemetry gateway.

        This is a long-running server, so it's started with `Popen` (not
        waited on) and the process handle is returned; call `.terminate()`
        on it when you're done.
        """
        import subprocess

        args = [self.binary, "gateway", *build_flags({"config": config})]
        return subprocess.Popen(args, cwd=self.cwd, env=self.env)
