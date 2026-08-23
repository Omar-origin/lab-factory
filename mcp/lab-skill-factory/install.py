#!/usr/bin/env python3
"""Install Lab Skill Factory MCP config for Claude Code and/or Codex."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any


SERVER_DIR = Path(__file__).resolve().parent
REPO_ROOT = SERVER_DIR.parents[1]
DEFAULT_SKILL_ROOT = REPO_ROOT / "skills" / "lab-skill-factory"
DEFAULT_CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
DEFAULT_CLAUDE_CONFIG = Path.home() / ".claude.json"
SERVER_NAME = "lab-skill-factory"
DEPRECATED_AUTH_ENV = {
    "LAB_FACTORY_DEV_ALLOW", "LAB_FACTORY_LICENSE_DB", "LAB_FACTORY_LICENSE_FILE",
    "LAB_FACTORY_AUTH_URL", "LAB_FACTORY_LEASE_PUBLIC_KEY",
}


def server_command(binary: str | None) -> tuple[str, list[str]]:
    if binary:
        return str(Path(binary).expanduser().resolve()), ["serve-mcp"]
    return sys.executable, [str(SERVER_DIR / "cli.py"), "serve-mcp"]


def env_map(args: argparse.Namespace) -> dict[str, str]:
    env = {}
    if getattr(args, "skill_root", None):
        env["LAB_FACTORY_SKILL_ROOT"] = str(Path(args.skill_root).expanduser().resolve())
    if getattr(args, "workspace_root", None):
        env["LAB_FACTORY_WORKSPACE_ROOT"] = str(Path(args.workspace_root).expanduser().resolve())
    if args.product_id:
        env["LAB_FACTORY_PRODUCT_ID"] = args.product_id
    env["LAB_FACTORY_PURCHASE_URL"] = args.purchase_url
    env["LAB_FACTORY_SUPPORT_EMAIL"] = args.support_email
    env["LAB_FACTORY_FEEDBACK_EMAIL"] = args.feedback_email or args.support_email
    if getattr(args, "control_url", None):
        env["LAB_FACTORY_CONTROL_URL"] = args.control_url.rstrip("/")
    return env


def merge_env(existing: dict[str, Any], requested: dict[str, str]) -> dict[str, str]:
    merged = {str(key): str(value) for key, value in existing.items() if isinstance(value, (str, int, float, bool))}
    merged.update(requested)
    return merged


def read_codex_env(config_path: Path) -> dict[str, str]:
    if not config_path.exists():
        return {}
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}
    servers = data.get("mcp_servers")
    if not isinstance(servers, dict):
        return {}
    server = servers.get(SERVER_NAME)
    if not isinstance(server, dict):
        return {}
    env = server.get("env")
    return merge_env(env if isinstance(env, dict) else {}, {})


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def server_env_from_config(data: dict[str, Any]) -> dict[str, str]:
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return {}
    server = servers.get(SERVER_NAME)
    if not isinstance(server, dict):
        return {}
    env = server.get("env")
    return merge_env(env if isinstance(env, dict) else {}, {})


def read_claude_env(scope: str, *, cwd: Path | None = None, home: Path | None = None) -> dict[str, str]:
    cwd = (cwd or Path.cwd()).resolve()
    home = home or Path.home()
    config = read_json(home / ".claude.json")
    merged = server_env_from_config(config)

    if scope in {"local", "project"}:
        projects = config.get("projects")
        if isinstance(projects, dict):
            project = projects.get(str(cwd))
            if isinstance(project, dict):
                merged = merge_env(merged, server_env_from_config(project))

    if scope == "project":
        merged = merge_env(merged, server_env_from_config(read_json(cwd / ".mcp.json")))
    return merged


def effective_codex_env(args: argparse.Namespace, requested: dict[str, str]) -> dict[str, str]:
    config_path = Path(args.codex_config or DEFAULT_CODEX_CONFIG).expanduser()
    existing = read_codex_env(config_path)
    for key in DEPRECATED_AUTH_ENV:
        existing.pop(key, None)
    return merge_env(existing, requested)


def effective_claude_env(args: argparse.Namespace, requested: dict[str, str]) -> dict[str, str]:
    existing = read_claude_env(args.claude_scope)
    for key in DEPRECATED_AUTH_ENV:
        existing.pop(key, None)
    return merge_env(existing, requested)


def codex_config_snippet(command: str, command_args: list[str], env: dict[str, str]) -> str:
    lines = [
        "[mcp_servers.lab-skill-factory]",
        f"command = {json.dumps(command, ensure_ascii=False)}",
        f"args = {json.dumps(command_args, ensure_ascii=False)}",
        "",
        "[mcp_servers.lab-skill-factory.env]",
    ]
    lines.extend(f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in env.items())
    return "\n".join(lines) + "\n"


def remove_existing_codex_section(text: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    skip = False
    for line in lines:
        if line.strip() == "[mcp_servers.lab-skill-factory]":
            skip = True
            continue
        if skip and line.startswith("[") and line.strip() != "[mcp_servers.lab-skill-factory.env]":
            skip = False
        if skip:
            continue
        output.append(line)
    return "\n".join(output).rstrip() + ("\n" if output else "")


def install_codex(args: argparse.Namespace, command: str, command_args: list[str], env: dict[str, str]) -> Path:
    config_path = Path(args.codex_config or DEFAULT_CODEX_CONFIG).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = config_path.read_text(encoding="utf-8", errors="replace") if config_path.exists() else ""
    clean = remove_existing_codex_section(existing)
    snippet = codex_config_snippet(command, command_args, env)
    config_path.write_text((clean + "\n" + snippet).lstrip(), encoding="utf-8")
    return config_path


def claude_manual_config(command: str, command_args: list[str], env: dict[str, str]) -> dict[str, Any]:
    return {
        "mcpServers": {
            "lab-skill-factory": {
                "command": command,
                "args": command_args,
                "env": env,
            }
        }
    }


def claude_env_args(env: dict[str, str], flag: str) -> list[str]:
    args: list[str] = []
    for key, value in env.items():
        args.extend([flag, f"{key}={value}"])
    return args


def claude_command_candidates(
    claude: str,
    command: str,
    command_args: list[str],
    env: dict[str, str],
    scope: str,
) -> list[dict[str, Any]]:
    # Claude Code's `mcp add` syntax has changed in small ways across versions.
    # Current builds make `-e/--env` variadic, so `--` must terminate option
    # parsing before the server name. Keep fallbacks for older accepted shapes.
    base = [claude, "mcp", "add"]
    server = ["lab-skill-factory", command, *command_args]
    legacy_separator_server = ["lab-skill-factory", "--", command, *command_args]
    return [
        {
            "name": "scope-short-env-option-terminator",
            "command": [*base, "--scope", scope, *claude_env_args(env, "-e"), "--", *server],
        },
        {
            "name": "scope-long-env-option-terminator",
            "command": [
                *base,
                "--scope",
                scope,
                *claude_env_args(env, "--env"),
                "--",
                *server,
            ],
        },
        {
            "name": "short-env-option-terminator-no-scope",
            "command": [*base, *claude_env_args(env, "-e"), "--", *server],
        },
        {
            "name": "short-env-after-server",
            "command": [*base, "--scope", scope, *server, *claude_env_args(env, "-e")],
        },
        {
            "name": "legacy-long-env-command-separator",
            "command": [
                *base,
                "--transport",
                "stdio",
                *claude_env_args(env, "--env"),
                *legacy_separator_server,
            ],
        },
    ]


def install_claude(args: argparse.Namespace, command: str, command_args: list[str], env: dict[str, str]) -> dict:
    claude = shutil.which("claude")
    if not claude:
        return {
            "ok": False,
            "error": "claude CLI not found on PATH",
            "manual_config": claude_manual_config(command, command_args, env),
        }
    candidates = claude_command_candidates(claude, command, command_args, env, args.claude_scope)
    if args.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "preferred_command": candidates[0]["command"],
            "fallback_commands": [candidate["command"] for candidate in candidates[1:]],
            "manual_config": claude_manual_config(command, command_args, env),
        }

    attempts = []
    for candidate in candidates:
        proc = subprocess.run(
            candidate["command"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        attempt = {
            "name": candidate["name"],
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "command": candidate["command"],
        }
        attempts.append(attempt)
        if proc.returncode == 0:
            return {
                "ok": True,
                "selected": candidate["name"],
                "returncode": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
                "command": candidate["command"],
                "attempts": attempts,
            }

    return {
        "ok": False,
        "error": "all claude mcp add command variants failed",
        "attempts": attempts,
        "manual_config": claude_manual_config(command, command_args, env),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Lab Skill Factory MCP for Claude Code and/or Codex.")
    parser.add_argument("--target", choices=["claude", "codex", "both"], default="both")
    parser.add_argument("--binary", help="Path to packaged lab-factory binary. Defaults to python cli.py serve-mcp.")
    parser.add_argument("--skill-root", default=str(DEFAULT_SKILL_ROOT))
    parser.add_argument("--workspace-root", default=str(REPO_ROOT))
    parser.add_argument("--product-id", default="lab-factory-1")
    parser.add_argument("--purchase-url", required=True)
    parser.add_argument("--support-email", required=True)
    parser.add_argument("--feedback-email")
    parser.add_argument("--codex-config", default=str(DEFAULT_CODEX_CONFIG))
    parser.add_argument("--claude-scope", choices=["local", "user", "project"], default="user")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    command, command_args = server_command(args.binary)
    requested_env = env_map(args)
    result: dict[str, object] = {
        "ok": True,
        "command": command,
        "args": command_args,
        "requested_env": requested_env,
    }

    if args.target in {"codex", "both"}:
        codex_env = effective_codex_env(args, requested_env)
        snippet = codex_config_snippet(command, command_args, codex_env)
        if args.dry_run:
            result["codex"] = {"ok": True, "dry_run": True, "config": snippet, "env": codex_env}
        else:
            path = install_codex(args, command, command_args, codex_env)
            result["codex"] = {"ok": True, "config_path": str(path), "env": codex_env}

    if args.target in {"claude", "both"}:
        claude_env = effective_claude_env(args, requested_env)
        result["claude"] = install_claude(args, command, command_args, claude_env)
        result["claude"]["env"] = claude_env

    target_results = [value for key, value in result.items() if key in {"codex", "claude"} and isinstance(value, dict)]
    result["ok"] = all(value.get("ok") is True for value in target_results)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
