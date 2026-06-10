#!/usr/bin/env python3
"""Hash activation codes for the Lab Skill Factory MCP MVP allowlist."""

from __future__ import annotations

import argparse
import hashlib
import json


def sha256_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an activation code hash entry.")
    parser.add_argument("activation_code", help="Plain activation code to hash.")
    parser.add_argument("--label", default="customer", help="Optional label stored with the hash.")
    parser.add_argument("--expires-at", help="Optional expiry date, e.g. 2026-12-31.")
    args = parser.parse_args()

    entry = {"sha256": sha256_code(args.activation_code), "label": args.label}
    if args.expires_at:
        entry["expires_at"] = args.expires_at
    print(json.dumps(entry, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
