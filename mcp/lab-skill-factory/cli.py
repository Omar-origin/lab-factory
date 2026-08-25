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
    requested_env = installer.env_map(args)
    result: dict[str, Any] = {
        "ok": True,
        "command": command,
        "args": command_args,
        "requested_env": requested_env,
    }

    if args.target in {"codex", "both"}:
        codex_env = installer.effective_codex_env(args, requested_env)
        snippet = installer.codex_config_snippet(command, command_args, codex_env)
        if args.dry_run:
            result["codex"] = {"ok": True, "dry_run": True, "config": snippet, "env": codex_env}
        else:
            path = installer.install_codex(args, command, command_args, codex_env)
            result["codex"] = {"ok": True, "config_path": str(path), "env": codex_env}

    if args.target in {"claude", "both"}:
        claude_env = installer.effective_claude_env(args, requested_env)
        result["claude"] = installer.install_claude(args, command, command_args, claude_env)
        result["claude"]["env"] = claude_env

    target_results = [value for key, value in result.items() if key in {"codex", "claude"} and isinstance(value, dict)]
    result["ok"] = all(value.get("ok") is True for value in target_results)

    print_json(result)
    return 0 if result["ok"] else 1


def run_beta_tests(_: argparse.Namespace) -> int:
    script_root = server.BUNDLE_ROOT if server.FROZEN else server.SERVER_DIR
    scripts = [
        script_root / "scripts" / "run_beta_smoke_tests.py",
        script_root / "scripts" / "run_v2_tests.py",
        script_root / "scripts" / "run_autopilot_tests.py",
    ]
    missing = [str(script) for script in scripts if not script.exists()]
    if missing:
        print_json(
            {
                "ok": False,
                "error": "beta smoke test scripts are not available in this build",
                "missing": missing,
            }
        )
        return 1
    if server.FROZEN:
        for script in scripts:
            original_argv = sys.argv[:]
            try:
                sys.argv = [str(script)]
                runpy.run_path(str(script), run_name="__main__")
            except SystemExit as exc:
                code = int(exc.code or 0) if isinstance(exc.code, int) else 1
                if code:
                    return code
            finally:
                sys.argv = original_argv
        return 0
    for script in scripts:
        proc = subprocess.run(
            [sys.executable, str(script)], text=True, encoding="utf-8", errors="replace", check=False,
        )
        if proc.returncode:
            return proc.returncode
    return 0


def run_mcp_smoke(_: argparse.Namespace) -> int:
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
    if server.FROZEN:
        response = server.handle_request(request)
        server_info = ((response or {}).get("result") or {}).get("serverInfo") or {}
        ok = bool(response) and response.get("id") == 1 and server_info.get("name") == "lab-factory-mcp"
        print_json({"ok": ok, "mode": "in_process_frozen_handshake", "response": response})
        return 0 if ok else 1
    command = [sys.executable, str(server.SERVER_DIR / "cli.py"), "serve-mcp"]
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

    request_license = sub.add_parser("license-request", help="Create a device request to send to the seller.")
    request_license.add_argument("--output", required=True)
    activate = sub.add_parser("activate", help="Import a seller-signed offline .lflicense file.")
    activate.add_argument("license_file")
    activate.add_argument("--accept-terms-version", required=True)
    activate.add_argument("--confirm-age-18", action="store_true", required=True)

    activate_key = sub.add_parser("activate-key", help="Bind an online activation key to this installation.")
    activate_key.add_argument("activation_key")
    activate_key.add_argument("--control-url")
    activate_key.add_argument("--accept-terms-version", required=True)
    activate_key.add_argument("--confirm-age-18", action="store_true", required=True)

    sub.add_parser("deactivate", help="Deactivate this installation.")
    sub.add_parser("request-refund", help="Show after-sales guidance for exceptional refund cases.")
    telemetry = sub.add_parser("telemetry", help="Enable, disable, or inspect anonymous usage data collection.")
    telemetry.add_argument("action", choices=["enable", "disable", "status", "clear"])
    feedback = sub.add_parser("feedback", help="Record one structured draft review locally.")
    feedback.add_argument("review_id")
    feedback.add_argument("--rating", type=int, choices=range(1, 6), required=True)
    feedback.add_argument("--edit-time", choices=["under_15m", "15_30m", "30_60m", "over_60m"], required=True)
    feedback.add_argument("--issue", action="append", default=[])
    feedback_export = sub.add_parser("feedback-export", help="Export local diagnostics for manual sending.")
    feedback_export.add_argument("--output", required=True)
    verify_update = sub.add_parser("verify-update", help="Verify a manually received update file.")
    verify_update.add_argument("path")
    verify_update.add_argument("--sha256", required=True)

    export_config = sub.add_parser("export-config", help="Export MCP client config.")
    export_config.add_argument("--client", choices=["claude_code", "codex", "generic_stdio"], default="generic_stdio")

    install = sub.add_parser("install", help="Install MCP config for Claude Code and/or Codex.")
    install.add_argument("--target", choices=["claude", "codex", "both"], default="both")
    install.add_argument("--binary")
    install.add_argument("--skill-root")
    install.add_argument("--workspace-root")
    install.add_argument("--product-id", default="lab-factory-1")
    install.add_argument("--purchase-url", required=True)
    install.add_argument("--support-email", required=True)
    install.add_argument("--feedback-email")
    install.add_argument("--control-url")
    install.add_argument("--codex-config", default=str(installer.DEFAULT_CODEX_CONFIG))
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

    inventory_v2 = sub.add_parser("inventory-v2", help="Build a structural OOXML inventory for a DOCX template.")
    inventory_v2.add_argument("docx_path")
    inventory_v2.add_argument("--output")

    profile_v2 = sub.add_parser("create-profile-v2", help="Compile confirmed inventory nodes into a v2 template profile.")
    profile_v2.add_argument("inventory_path")
    profile_v2.add_argument("output_path")
    profile_v2.add_argument("--subject", required=True)
    profile_v2.add_argument("--fields-json", required=True, help="JSON array of field definitions.")

    propose_v2 = sub.add_parser("propose-v2", help="Score v2 placements for a DOCX.")
    propose_v2.add_argument("profile_path")
    propose_v2.add_argument("docx_path")
    propose_v2.add_argument("--output")

    section_plan_v2 = sub.add_parser("section-plan-v2", help="Compile an AI-proposed level 2/3 heading expansion for user review.")
    section_plan_v2.add_argument("inventory_path")
    section_plan_v2.add_argument("output_path")
    section_plan_v2.add_argument("--proposal-json", required=True)

    apply_section_plan_v2 = sub.add_parser("apply-section-plan-v2", help="Apply a user-confirmed heading expansion to a DOCX copy.")
    apply_section_plan_v2.add_argument("section_plan_path")
    apply_section_plan_v2.add_argument("docx_path")
    apply_section_plan_v2.add_argument("output_path")
    apply_section_plan_v2.add_argument("--confirmation", required=True)
    apply_section_plan_v2.add_argument("--overwrite", action="store_true")

    apply_v2 = sub.add_parser("apply-v2", help="Apply a v2 content package with structural placement gates.")
    apply_v2.add_argument("profile_path")
    apply_v2.add_argument("docx_path")
    apply_v2.add_argument("content_package_path")
    apply_v2.add_argument("output_path")
    apply_v2.add_argument("--overwrite", action="store_true")

    create_session_v2 = sub.add_parser("create-session-v2", help="Create a persistent Lab Factory v2 workflow session.")
    create_session_v2.add_argument("workspace")
    create_session_v2.add_argument("--subject", required=True)
    create_session_v2.add_argument("--report-id")

    session_v2 = sub.add_parser("session-v2", help="Show a persistent Lab Factory v2 workflow session.")
    session_v2.add_argument("workspace")

    writing_v2 = sub.add_parser("writing-profile-v2", help="Create a course-scoped writing profile.")
    writing_v2.add_argument("output_path")
    writing_v2.add_argument("--subject", required=True)
    writing_v2.add_argument("--preset", choices=["balanced", "concise", "technical", "personal"], default="balanced")
    writing_v2.add_argument("--overrides-json", default="{}")

    sample_profile_v2 = sub.add_parser(
        "analyze-writing-samples-v2",
        help="Analyze 1-3 prior reports locally and write a privacy-safe personal writing profile.",
    )
    sample_profile_v2.add_argument("sample_paths", nargs="+")
    sample_profile_v2.add_argument("--output", required=True)

    humanization_v2 = sub.add_parser(
        "humanization-audit-v2",
        help="Audit a report for clustered AI-template prose without using detector scores.",
    )
    humanization_v2.add_argument("document_path")
    humanization_v2.add_argument("--output")

    structure_audit_v2 = sub.add_parser(
        "document-structure-audit-v2",
        help="Audit layout flow, numbered figure/table placeholders, cross-references, and unresolved template cues.",
    )
    structure_audit_v2.add_argument("document_path")
    structure_audit_v2.add_argument("--output")

    cohort_v2 = sub.add_parser(
        "cohort-similarity-v2",
        help="Check a report against local history or consented de-identified cohort reports.",
    )
    cohort_v2.add_argument("generated_path")
    cohort_v2.add_argument("comparison_paths", nargs="*")
    cohort_v2.add_argument("--whitelist-json", default="[]")

    similarity_v2 = sub.add_parser("similarity-v2", help="Run the strict reference-sample similarity gate.")
    similarity_v2.add_argument("generated_path")
    similarity_v2.add_argument("reference_paths", nargs="+")
    similarity_v2.add_argument("--whitelist-json", default="[]")

    migrate_v2 = sub.add_parser("migrate-v1", help="Convert a v1 fill-map into a v2 relocation draft.")
    migrate_v2.add_argument("fill_map_path")
    migrate_v2.add_argument("output_path")

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
    if args.command == "license-request":
        return call_tool(server.tool_create_license_request, {"output_path": args.output})
    if args.command == "activate":
        return call_tool(
            server.tool_activate,
            {"license_path": args.license_file, "adult_confirmed": args.confirm_age_18, "terms_version": args.accept_terms_version},
        )
    if args.command == "activate-key":
        return call_tool(
            server.tool_activate_key,
            {
                "activation_key": args.activation_key,
                "control_url": args.control_url,
                "adult_confirmed": args.confirm_age_18,
                "terms_version": args.accept_terms_version,
            },
        )
    if args.command == "deactivate":
        return call_tool(server.tool_deactivate, {})
    if args.command == "request-refund":
        return call_tool(server.tool_request_refund, {})
    if args.command == "telemetry":
        return call_tool(server.tool_telemetry_settings, {"action": args.action})
    if args.command == "feedback":
        return call_tool(server.tool_submit_draft_feedback, {
            "review_id": args.review_id, "rating": args.rating,
            "edit_time_bucket": args.edit_time, "issue_categories": args.issue,
        })
    if args.command == "feedback-export":
        return call_tool(server.tool_export_feedback, {"output_path": args.output})
    if args.command == "verify-update":
        return call_tool(server.tool_verify_update, {"path": args.path, "sha256": args.sha256})
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
    if args.command == "inventory-v2":
        payload = {"docx_path": args.docx_path}
        if args.output:
            payload["output_path"] = args.output
        return call_tool(server.tool_v2_inventory, payload)
    if args.command == "create-profile-v2":
        try:
            fields = json.loads(args.fields_json)
        except json.JSONDecodeError as exc:
            print_json({"ok": False, "error": f"Invalid --fields-json: {exc}"})
            return 2
        return call_tool(server.tool_v2_create_template_profile, {"inventory_path": args.inventory_path, "output_path": args.output_path, "subject": args.subject, "fields": fields})
    if args.command == "propose-v2":
        payload = {"profile_path": args.profile_path, "docx_path": args.docx_path}
        if args.output:
            payload["output_path"] = args.output
        return call_tool(server.tool_v2_propose_placements, payload)
    if args.command == "section-plan-v2":
        try:
            proposal = json.loads(args.proposal_json)
        except json.JSONDecodeError as exc:
            print_json({"ok": False, "error": f"Invalid --proposal-json: {exc}"})
            return 2
        return call_tool(server.tool_v2_propose_section_plan, {
            "inventory_path": args.inventory_path, "output_path": args.output_path, "proposal": proposal,
        })
    if args.command == "apply-section-plan-v2":
        command = [
            "apply-section-plan", server.resolve_user_path(args.section_plan_path),
            server.resolve_user_path(args.docx_path), "--confirmation", args.confirmation,
            "--output", server.resolve_user_path(args.output_path),
        ]
        if args.overwrite:
            command.append("--overwrite")
        try:
            print_json(server.run_v2(command, timeout=180))
            return 0
        except server.ToolError as exc:
            print_json({"ok": False, "error": str(exc)})
            return 1
    if args.command == "apply-v2":
        # Direct CLI use is diagnostic and does not advance an MCP workflow session.
        command = [
            "apply", server.resolve_user_path(args.profile_path), server.resolve_user_path(args.docx_path),
            server.resolve_user_path(args.content_package_path), "--output", server.resolve_user_path(args.output_path),
        ]
        if args.overwrite:
            command.append("--overwrite")
        try:
            print_json(server.run_v2(command, timeout=180))
            return 0
        except server.ToolError as exc:
            print_json({"ok": False, "error": str(exc)})
            return 1
    if args.command == "create-session-v2":
        payload = {"workspace": args.workspace, "subject": args.subject}
        if args.report_id:
            payload["report_id"] = args.report_id
        return call_tool(server.tool_v2_create_session, payload)
    if args.command == "session-v2":
        return call_tool(server.tool_v2_session_status, {"workspace": args.workspace})
    if args.command == "writing-profile-v2":
        try:
            overrides = json.loads(args.overrides_json)
        except json.JSONDecodeError as exc:
            print_json({"ok": False, "error": f"Invalid --overrides-json: {exc}"})
            return 2
        return call_tool(server.tool_v2_create_writing_profile, {"output_path": args.output_path, "subject": args.subject, "preset": args.preset, "overrides": overrides})
    if args.command == "analyze-writing-samples-v2":
        if not 1 <= len(args.sample_paths) <= 3:
            print_json({"ok": False, "error": "sample_paths must contain 1-3 files"})
            return 2
        return call_tool(server.tool_v2_analyze_writing_samples, {
            "sample_paths": args.sample_paths, "output_path": args.output,
        })
    if args.command == "humanization-audit-v2":
        payload = {"document_path": args.document_path}
        if args.output:
            payload["output_path"] = args.output
        return call_tool(server.tool_v2_humanization_audit, payload)
    if args.command == "document-structure-audit-v2":
        payload = {"document_path": args.document_path}
        if args.output:
            payload["output_path"] = args.output
        return call_tool(server.tool_v2_document_structure_audit, payload)
    if args.command == "cohort-similarity-v2":
        try:
            whitelist = json.loads(args.whitelist_json)
        except json.JSONDecodeError as exc:
            print_json({"ok": False, "error": f"Invalid --whitelist-json: {exc}"})
            return 2
        return call_tool(server.tool_v2_cohort_similarity, {
            "generated_path": args.generated_path,
            "comparison_paths": args.comparison_paths,
            "whitelist": whitelist,
        })
    if args.command == "similarity-v2":
        try:
            whitelist = json.loads(args.whitelist_json)
            result = server.run_v2([
                "similarity", server.resolve_user_path(args.generated_path),
                *(server.resolve_user_path(path) for path in args.reference_paths),
                "--whitelist-json", json.dumps(whitelist, ensure_ascii=False),
            ], allow_validation_failure=True)
            print_json(result)
            return 0 if result.get("ok") else 1
        except (server.ToolError, json.JSONDecodeError) as exc:
            print_json({"ok": False, "error": str(exc)})
            return 1
    if args.command == "migrate-v1":
        return call_tool(server.tool_v2_migrate_v1, {"fill_map_path": args.fill_map_path, "output_path": args.output_path})
    if args.command == "validate-skill":
        return call_tool(server.tool_validate_scaffolded_skill, {"skill_dir": args.skill_dir})
    if args.command == "test":
        return run_beta_tests(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
