#!/usr/bin/env python3
"""Check Lab Skill Factory MCP runtime dependencies."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
VENDOR_DIR = SERVER_DIR / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))


CHECKS = [
    ("python-docx", "docx", "recommended_for_docx_write"),
    ("lxml", "lxml", "recommended_for_docx_write"),
    ("docxtpl", "docxtpl", "optional_controlled_template"),
    ("mammoth", "mammoth", "optional_read_only_extraction"),
    ("pywin32", "win32com", "windows_optional_word_automation"),
]


def available(import_name: str) -> bool:
    return importlib.util.find_spec(import_name) is not None


def main() -> int:
    results = [
        {
            "package": package,
            "import_name": import_name,
            "required_level": required_level,
            "available": available(import_name),
        }
        for package, import_name, required_level in CHECKS
    ]
    missing_recommended = [
        item["package"]
        for item in results
        if item["required_level"] == "recommended_for_docx_write" and not item["available"]
    ]
    print(
        json.dumps(
            {
                "ok": not missing_recommended,
                "python": sys.executable,
                "vendor_dir": str(VENDOR_DIR),
                "vendor_dir_exists": VENDOR_DIR.exists(),
                "checks": results,
                "missing_recommended": missing_recommended,
                "install_to_vendor": (
                    f"{sys.executable} -m pip install --target {VENDOR_DIR} "
                    f"-r {SERVER_DIR / 'runtime-requirements.txt'}"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not missing_recommended else 1


if __name__ == "__main__":
    raise SystemExit(main())
