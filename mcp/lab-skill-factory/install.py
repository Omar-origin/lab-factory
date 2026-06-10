#!/usr/bin/env python3
"""Install Lab Skill Factory MCP config for Claude Code and/or Codex."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parent
REPO_ROOT = SERVER_DIR.parents[1]
DEFAULT_SKILL_ROOT = REPO_ROOT / "skills" / "lab-skill-factory"
DEFAULT_LICENSE_DB = SERVER_DIR / "activation_codes.json"


def server_command(binary: str | None) -> tuple[str, list[str]]:
    if binary:
        return str(Path(binary).expanduser().resolve()), ["serve-mcp"]
    return sys.executable, [str(SERVER_DIR / "cli.py"), "serve-mcp"]


def env_map(args: argparse.Namespace) -> dict[str, str]:
    env = {
        "LAB_FACTORY_SKILL_ROOT": str(Path(args.skill_root).expanduser().resolve()),
        "LAB_FACTORY_WORKSPACE_ROOT": str(Path(args.workspace_root).expanduser().resolve()),
    }
    if args.auth_url:
        env["LAB_FACTORY_AUTH_URL"] = args.auth_url.rstrip("/")
    else:
        env["LAB_FACTORY_LICENSE_DB"] = str(Path(args.license_db).expanduser().resolve())
    if args.product_id:
        env["LAB_FACTORY_PRODUCT_ID"] = args.product_id
    return env


def codex_config_snippet(command: str, command_args: list[str], env: dict[str, str]) -> str:
    lines = [
        "[mcp_servers.lab-skill-factory]",
        f'command = "{command}"',
        f"args = {json.dumps(command_args, ensure_ascii=False)}",
        "",
        "[mcp_servers.lab-skill-factory.env]",
    ]
    lines.extend(f'{key} = "{value}"' for key, value in env.items())
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
    config_path = Path(args.codex_config).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = config_path.read_text(encoding="utf-8", errors="replace") if config_path.exists() else ""
    clean = remove_existing_codex_section(existing)
    snippet = codex_config_snippet(command, command_args, env)
    config_path.write_text((clean + "\n" + snippet).lstrip(), encoding="utf-8")
    return config_path


def install_claude(args: argparse.Namespace, command: str, command_args: list[str], env: dict[str, str]) -> dict:
    claude = shutil.which("claude")
    if not claude:
        return {
            "ok": False,
            "error": "claude CLI not found on PATH",
            "manual_config": {
                "mcpServers": {
                    "lab-skill-factory": {
                        "command": command,
                        "args": command_args,
                        "env": env,
                    }
                }
            },
        }
    cmd = [claude, "mcp", "add", "--transport", "stdio"]
    for key, value in env.items():
        cmd.extend(["--env", f"{key}={value}"])
    cmd.extend(["lab-skill-factory", "--", command, *command_args])
    if args.dry_run:
        return {"ok": True, "dry_run": True, "command": cmd}
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "command": cmd,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Lab Skill Factory MCP for Claude Code and/or Codex.")
    parser.add_argument("--target", choices=["claude", "codex", "both"], default="both")
    parser.add_argument("--binary", help="Path to packaged lab-factory binary. Defaults to python cli.py serve-mcp.")
    parser.add_argument("--skill-root", default=str(DEFAULT_SKILL_ROOT))
    parser.add_argument("--workspace-root", default=str(REPO_ROOT))
    parser.add_argument("--license-db", default=str(DEFAULT_LICENSE_DB))
    parser.add_argument("--auth-url", help="Remote activation service URL. If set, local license DB is not used.")
    parser.add_argument("--product-id", default="lab-skill-factory-beta")
    parser.add_argument("--codex-config", default=str(Path.home() / ".codex" / "config.toml"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    command, command_args = server_command(args.binary)
    env = env_map(args)
    result: dict[str, object] = {"ok": True, "command": command, "args": command_args, "env": env}

    if args.target in {"codex", "both"}:
        snippet = codex_config_snippet(command, command_args, env)
        if args.dry_run:
            result["codex"] = {"ok": True, "dry_run": True, "config": snippet}
        else:
            path = install_codex(args, command, command_args, env)
            result["codex"] = {"ok": True, "config_path": str(path)}

    if args.target in {"claude", "both"}:
        result["claude"] = install_claude(args, command, command_args, env)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
