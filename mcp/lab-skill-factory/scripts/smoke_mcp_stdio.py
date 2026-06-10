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


def parse_first_json_line(output: bytes) -> dict:
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        return json.loads(line.decode("utf-8"))
    raise RuntimeError("MCP server produced no stdout JSON line")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test a Lab Factory MCP stdio command.")
    parser.add_argument("command", nargs="+", help="Command and args that start the MCP server.")
    args = parser.parse_args()

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "lab-factory-smoke", "version": "0"},
        },
    }
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
        stdout, stderr = proc.communicate(encode_message(request), timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        raise RuntimeError(f"MCP server timed out. stderr={stderr.decode('utf-8', errors='replace')}")

    if proc.returncode != 0:
        raise RuntimeError(
            "MCP server exited with non-zero status "
            f"{proc.returncode}. stderr={stderr.decode('utf-8', errors='replace')}"
        )

    response = parse_first_json_line(stdout)
    result = response.get("result") if isinstance(response, dict) else None
    server_info = result.get("serverInfo") if isinstance(result, dict) else None
    if response.get("id") != 1 or not isinstance(server_info, dict):
        raise RuntimeError(f"Unexpected MCP initialize response: {response}")
    if server_info.get("name") != "lab-factory-mcp":
        raise RuntimeError(f"Unexpected MCP server name: {server_info}")

    print(json.dumps({"ok": True, "response": response}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1)
