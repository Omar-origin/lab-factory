#!/usr/bin/env python3
"""Lab Factory CLI product entrypoint.

The CLI is the product surface. MCP is exposed as the `serve-mcp` subcommand so
Claude Code, Codex, and other MCP clients can use the same engine.
"""

from __future__ import annotations

import argparse
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import install as installer
import server


def configure_stdio() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")


configure_stdio()


def print_json(data: Any) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    sys.stdout.write(text + "\n")


def call_tool(handler: Callable[[dict[str, Any]], dict[str, Any]], args: dict[str, Any]) -> int:
    try:
        result = handler(args)
        print_json(result)
        return 0 if result.get("ok", True) is not False else 1
    except server.ToolError as exc:
        print_json({"ok": False, "error": str(exc)})
        return 1


def run_install(args: argparse.Namespace) -> int:
    binary = args.binary or (sys.executable if server.FROZEN else None)
    command, command_args = installer.server_command(binary)
    env = installer.env_map(args)
    result: dict[str, Any] = {"ok": True, "command": command, "args": command_args, "env": env}

    if args.target in {"codex", "both"}:
        snippet = installer.codex_config_snippet(command, command_args, env)
        if args.dry_run:
            result["codex"] = {"ok": True, "dry_run": True, "config": snippet}
        else:
            path = installer.install_codex(args, command, command_args, env)
            result["codex"] = {"ok": True, "config_path": str(path)}

    if args.target in {"claude", "both"}:
        result["claude"] = installer.install_claude(args, command, command_args, env)

    print_json(result)
    return 0 if result.get("ok", True) is not False else 1


def run_beta_tests(_: argparse.Namespace) -> int:
    script_root = server.BUNDLE_ROOT if server.FROZEN else server.SERVER_DIR
    script = script_root / "scripts" / "run_beta_smoke_tests.py"
    if not script.exists():
        print_json(
            {
                "ok": False,
                "error": "beta smoke test script is not available in this build",
                "script": str(script),
            }
        )
        return 1
    if server.FROZEN:
        original_argv = sys.argv[:]
        try:
            sys.argv = [str(script)]
            runpy.run_path(str(script), run_name="__main__")
            return 0
        except SystemExit as exc:
            return int(exc.code or 0) if isinstance(exc.code, int) else 1
        finally:
            sys.argv = original_argv
    proc = subprocess.run(
        [sys.executable, str(script)],
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.returncode


def run_mcp_smoke(_: argparse.Namespace) -> int:
    command = (
        [sys.executable, "serve-mcp"]
        if server.FROZEN
        else [sys.executable, str(server.SERVER_DIR / "cli.py"), "serve-mcp"]
    )
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "lab-factory-cli-smoke", "version": "0"},
        },
    }
    payload = (json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        stdout, stderr = proc.communicate(payload, timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        print_json(
            {
                "ok": False,
                "error": "MCP stdio smoke test timed out",
                "command": command,
                "stderr": stderr.decode("utf-8", errors="replace"),
            }
        )
        return 1
    if proc.returncode != 0:
        print_json(
            {
                "ok": False,
                "error": f"MCP server exited with status {proc.returncode}",
                "command": command,
                "stderr": stderr.decode("utf-8", errors="replace"),
            }
        )
        return 1
    try:
        first_line = next(line for line in stdout.splitlines() if line.strip())
        response = json.loads(first_line.decode("utf-8"))
    except Exception as exc:
        print_json(
            {
                "ok": False,
                "error": f"Failed to parse MCP response: {exc}",
                "command": command,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
            }
        )
        return 1
    server_info = ((response.get("result") or {}).get("serverInfo") or {}) if isinstance(response, dict) else {}
    ok = response.get("id") == 1 and server_info.get("name") == "lab-factory-mcp"
    print_json({"ok": ok, "command": command, "response": response})
    return 0 if ok else 1


def run_embedded_skill_script(argv: list[str]) -> int:
    if len(argv) < 3:
        print_json({"ok": False, "error": "--run-skill-script requires a script path"})
        return 2
    script = Path(argv[2]).expanduser().resolve()
    original_argv = sys.argv[:]
    try:
        sys.argv = [str(script), *argv[3:]]
        runpy.run_path(str(script), run_name="__main__")
        return 0
    except SystemExit as exc:
        return int(exc.code or 0) if isinstance(exc.code, int) else 1
    finally:
        sys.argv = original_argv


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--run-skill-script":
        return run_embedded_skill_script(sys.argv)

    parser = argparse.ArgumentParser(
        prog="lab-factory",
        description="Lab Skill Factory CLI: activation, installation, diagnostics, writeback, tests, and MCP serving.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve-mcp", help="Run the stdio MCP server.")
    sub.add_parser("status", help="Show activation and runtime status.")
    sub.add_parser("check-runtime", help="Check bundled/runtime Python dependencies.")
    sub.add_parser("mcp-smoke", help="Run a local MCP stdio handshake smoke test.")

    activate = sub.add_parser("activate", help="Activate with a beta activation code.")
    activate.add_argument("activation_code")
    activate.add_argument("--customer-id")

    export_config = sub.add_parser("export-config", help="Export MCP client config.")
    export_config.add_argument("--client", choices=["claude_code", "codex", "generic_stdio"], default="generic_stdio")

    install = sub.add_parser("install", help="Install MCP config for Claude Code and/or Codex.")
    install.add_argument("--target", choices=["claude", "codex", "both"], default="both")
    install.add_argument("--binary")
    install.add_argument("--skill-root", default=str(server.DEFAULT_SKILL_ROOT))
    install.add_argument("--workspace-root", default=str(server.REPO_ROOT))
    install.add_argument("--license-db", default=str(server.DEFAULT_LICENSE_DB))
    install.add_argument("--auth-url")
    install.add_argument("--product-id", default="lab-skill-factory-beta")
    install.add_argument("--codex-config")
    install.add_argument("--claude-scope", choices=["local", "user", "project"], default="user")
    install.add_argument("--dry-run", action="store_true")

    inspect = sub.add_parser("inspect", help="Inspect lab materials and infer roles.")
    inspect.add_argument("paths", nargs="+")
    inspect.add_argument("--max-files", type=int, default=300)

    extract = sub.add_parser("extract-docx", help="Extract DOCX text, tables, anchors, and requirement paragraphs.")
    extract.add_argument("docx_path")

    validate_spec = sub.add_parser("validate-spec", help="Validate skill-spec.md.")
    validate_spec.add_argument("skill_spec_path")

    scaffold = sub.add_parser("scaffold-skill", help="Generate a user-editable subject skill from skill-spec.md.")
    scaffold.add_argument("skill_spec_path")
    scaffold.add_argument("output_dir")
    scaffold.add_argument("--slug")
    scaffold.add_argument("--scope-level", choices=["subject", "template", "experiment"])
    scaffold.add_argument("--skip-validation", action="store_true")

    validate_fill = sub.add_parser("validate-fill-map", help="Validate fill-map.json.")
    validate_fill.add_argument("fill_map_path")

    apply_fill = sub.add_parser("apply-fill-map", help="Copy target DOCX/MD and apply fill.md by fill-map.json.")
    apply_fill.add_argument("fill_map_path")
    apply_fill.add_argument("--output")
    apply_fill.add_argument("--overwrite", action="store_true")

    validate_skill = sub.add_parser("validate-skill", help="Validate a generated user subject skill.")
    validate_skill.add_argument("skill_dir")

    sub.add_parser("test", help="Run beta smoke tests.")

    args = parser.parse_args()

    if args.command == "serve-mcp":
        return server.serve_stdio()
    if args.command == "status":
        return call_tool(server.tool_status, {})
    if args.command == "check-runtime":
        return call_tool(server.tool_check_runtime, {})
    if args.command == "mcp-smoke":
        return run_mcp_smoke(args)
    if args.command == "activate":
        return call_tool(
            server.tool_activate,
            {"activation_code": args.activation_code, "customer_id": args.customer_id},
        )
    if args.command == "export-config":
        return call_tool(server.tool_export_client_config, {"client": args.client})
    if args.command == "install":
        return run_install(args)
    if args.command == "inspect":
        return call_tool(server.tool_inspect_materials, {"paths": args.paths, "max_files": args.max_files})
    if args.command == "extract-docx":
        return call_tool(server.tool_extract_docx_outline, {"docx_path": args.docx_path})
    if args.command == "validate-spec":
        return call_tool(server.tool_validate_skill_spec, {"skill_spec_path": args.skill_spec_path})
    if args.command == "scaffold-skill":
        payload: dict[str, Any] = {
            "skill_spec_path": args.skill_spec_path,
            "output_dir": args.output_dir,
            "skip_validation": args.skip_validation,
        }
        if args.slug:
            payload["slug"] = args.slug
        if args.scope_level:
            payload["scope_level"] = args.scope_level
        return call_tool(server.tool_scaffold_subject_skill, payload)
    if args.command == "validate-fill-map":
        return call_tool(server.tool_validate_fill_map, {"fill_map_path": args.fill_map_path})
    if args.command == "apply-fill-map":
        payload = {"fill_map_path": args.fill_map_path, "overwrite": args.overwrite}
        if args.output:
            payload["output_path"] = args.output
        return call_tool(server.tool_apply_fill_map, payload)
    if args.command == "validate-skill":
        return call_tool(server.tool_validate_scaffolded_skill, {"skill_dir": args.skill_dir})
    if args.command == "test":
        return run_beta_tests(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
