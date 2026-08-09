#!/usr/bin/env python3
"""Smoke test Lab Factory's MCP stdio transport with newline JSON-RPC."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


def encode_message(message: dict) -> bytes:
    return (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def parse_json_lines(output: bytes) -> list[dict]:
    messages = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        messages.append(json.loads(line.decode("utf-8")))
    if not messages:
        raise RuntimeError("MCP server produced no stdout JSON line")
    return messages


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test a Lab Factory MCP stdio command.")
    parser.add_argument("command", nargs="+", help="Command and args that start the MCP server.")
    args = parser.parse_args()

    initialize_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "lab-factory-smoke", "version": "0"},
        },
    }
    tools_request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.Popen(
        args.command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = proc.communicate(
            encode_message(initialize_request) + encode_message(tools_request), timeout=10
        )
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        raise RuntimeError(f"MCP server timed out. stderr={stderr.decode('utf-8', errors='replace')}")

    if proc.returncode != 0:
        raise RuntimeError(
            "MCP server exited with non-zero status "
            f"{proc.returncode}. stderr={stderr.decode('utf-8', errors='replace')}"
        )

    messages = parse_json_lines(stdout)
    by_id = {message.get("id"): message for message in messages}
    response = by_id.get(1, {})
    result = response.get("result") if isinstance(response, dict) else None
    server_info = result.get("serverInfo") if isinstance(result, dict) else None
    if response.get("id") != 1 or not isinstance(server_info, dict):
        raise RuntimeError(f"Unexpected MCP initialize response: {response}")
    if server_info.get("name") != "lab-factory-mcp":
        raise RuntimeError(f"Unexpected MCP server name: {server_info}")

    tools_response = by_id.get(2, {})
    tools = ((tools_response.get("result") or {}).get("tools")) if isinstance(tools_response, dict) else None
    if not isinstance(tools, list):
        raise RuntimeError(f"Unexpected tools/list response: {tools_response}")
    tool_names = {item.get("name") for item in tools if isinstance(item, dict)}
    expected_autopilot = {
        "lab_factory_v2_prepare_autopilot", "lab_factory_v2_answer_questions",
        "lab_factory_v2_confirm_checkpoint", "lab_factory_v2_advance_autopilot",
        "lab_factory_v2_autopilot_status",
    }
    missing = sorted(expected_autopilot - tool_names)
    if missing:
        raise RuntimeError(f"MCP build is missing autopilot tools: {missing}")

    print(json.dumps({
        "ok": True, "response": response, "tool_count": len(tool_names),
        "autopilot_tools": sorted(expected_autopilot),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1)
