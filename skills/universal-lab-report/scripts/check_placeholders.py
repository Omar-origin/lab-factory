#!/usr/bin/env python3
"""Check report files for placeholders, draft prompts, and reference markers."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

PATTERNS = {
    "placeholder_brackets": re.compile(r"【[^】]{1,80}】"),
    "draft_prompt": re.compile(r"(待用户|用户自行|请插入|此处插入|此处填写|补充截图|截图提示|操作指导)"),
    "reference_marker": re.compile(r"(参考示例|仅供参考|需结合个人|需自行核验|参考性质)"),
    "disclaimer": re.compile(r"免责声明"),
}


def text_from_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    parts = []
    for node in root.iter(f"{WORD_NS}t"):
        if node.text:
            parts.append(node.text)
    return "\n".join(parts)


def text_from_file(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return text_from_docx(path)
    return path.read_text(encoding="utf-8", errors="replace")


def summarize_matches(text: str) -> dict:
    result = {}
    for name, pattern in PATTERNS.items():
        matches = pattern.findall(text)
        result[name] = {
            "count": len(matches),
            "samples": list(dict.fromkeys(matches[:20])),
        }
    return result


def check_path(path: Path) -> dict:
    item = {"path": str(path), "exists": path.exists(), "readable": False}
    if not path.exists():
        item["error"] = "file does not exist"
        return item
    try:
        text = text_from_file(path)
    except Exception as exc:  # noqa: BLE001 - CLI should report all read errors.
        item["error"] = f"{type(exc).__name__}: {exc}"
        return item
    item["readable"] = True
    item["matches"] = summarize_matches(text)
    return item


def main() -> int:
    parser = argparse.ArgumentParser(description="Check report files for placeholders and markers.")
    parser.add_argument("files", nargs="+", help="Report files to inspect.")
    parser.add_argument(
        "--strict-final",
        action="store_true",
        help="Exit with status 1 if draft prompts or placeholder brackets remain.",
    )
    args = parser.parse_args()

    results = [check_path(Path(file).expanduser().resolve()) for file in args.files]
    print(json.dumps({"files": results}, ensure_ascii=False, indent=2))

    if any(not item.get("readable") for item in results):
        return 2

    if args.strict_final:
        for item in results:
            matches = item.get("matches", {})
            if matches.get("draft_prompt", {}).get("count", 0) or matches.get("placeholder_brackets", {}).get("count", 0):
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

