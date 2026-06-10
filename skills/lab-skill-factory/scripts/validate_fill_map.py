#!/usr/bin/env python3
"""Validate fill-map.json for subject lab-report skills."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ALLOWED_OPERATIONS = {"insert_after", "replace_placeholder", "fill_table_cell"}
REQUIRED_TOP_LEVEL = {
    "version",
    "source_fill",
    "target_document",
    "copy_mode",
    "format_strategy",
    "items",
}
REQUIRED_ITEM_FIELDS = {
    "id",
    "source",
    "target_anchor",
    "operation",
    "preserve_original",
    "format_strategy",
}


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_TOP_LEVEL:
        if field not in data:
            errors.append(f"missing top-level field: {field}")
    items = data.get("items")
    if data.get("copy_mode") != "byte_for_byte_first":
        errors.append("copy_mode must be byte_for_byte_first")
    if data.get("format_strategy") != "inherit_target_anchor":
        errors.append("format_strategy must be inherit_target_anchor")
    if not isinstance(items, list):
        errors.append("items must be a list")
        return errors
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"items[{index}] must be an object")
            continue
        for field in REQUIRED_ITEM_FIELDS:
            if field not in item:
                errors.append(f"items[{index}] missing field: {field}")
        if item.get("operation") not in ALLOWED_OPERATIONS:
            errors.append(f"items[{index}] invalid operation: {item.get('operation')}")
        if item.get("preserve_original") is not True:
            errors.append(f"items[{index}] preserve_original should be true for first-pass drafts")
        if item.get("format_strategy") != "inherit_target_anchor":
            errors.append(f"items[{index}] format_strategy must be inherit_target_anchor")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate fill-map.json.")
    parser.add_argument("fill_map", help="Path to fill-map.json.")
    args = parser.parse_args()

    path = Path(args.fill_map).expanduser().resolve()
    result = {"path": str(path), "exists": path.exists(), "ok": False}
    if not path.exists():
        result["error"] = "file does not exist"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result["error"] = f"invalid json: {exc}"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    errors = validate(data)
    result.update({"ok": not errors, "errors": errors})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
