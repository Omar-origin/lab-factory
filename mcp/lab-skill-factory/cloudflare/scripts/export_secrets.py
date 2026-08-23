#!/usr/bin/env python3
"""Export seller-only control secrets for Wrangler without printing values."""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--format", choices=["dev-vars", "json"], required=True)
    parser.add_argument("--lease-private-key", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and not args.force:
        parser.error("output exists; use --force only for intentional replacement")
    lease = json.loads(args.lease_private_key.expanduser().read_text(encoding="utf-8"))
    values = {
        "ADMIN_TOKEN": os.environ.get("LAB_CONTROL_ADMIN_TOKEN", ""),
        "KEY_PEPPER": os.environ.get("LAB_CONTROL_KEY_PEPPER", ""),
        "TOKEN_SECRET": os.environ.get("LAB_CONTROL_TOKEN_SECRET", ""),
        "LEASE_PRIVATE_KEY_B64": str(lease.get("private_key", "")),
    }
    if any(len(value) < 32 for value in values.values()):
        parser.error("source environment or lease private key is missing/invalid")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    if args.format == "json":
        content = json.dumps(values, ensure_ascii=False, indent=2) + "\n"
    else:
        content = "\n".join(f"{key}={json.dumps(value)}" for key, value in values.items()) + "\n"
    temporary.write_text(content, encoding="utf-8")
    if os.name != "nt":
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
    os.replace(temporary, output)
    print(json.dumps({"ok": True, "output": str(output), "secret_names": sorted(values)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
