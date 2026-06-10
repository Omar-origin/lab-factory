#!/usr/bin/env python3
"""Detect raw LaTeX markers that should not remain in final reports."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

LATEX_PATTERNS = {
    "display_math_dollars": re.compile(r"\$\$.*?\$\$", re.S),
    "inline_math_dollars": re.compile(r"(?<!\$)\$[^$\n]{2,120}\$(?!\$)"),
    "bracket_math": re.compile(r"\\\[.*?\\\]", re.S),
    "paren_math": re.compile(r"\\\(.+?\\\)", re.S),
    "latex_command": re.compile(r"\\(?:frac|theta|lambda|alpha|beta|gamma|sum|int|left|right|sqrt|cdot|times)\b"),
}


def text_from_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    return "\n".join(node.text for node in root.iter(f"{WORD_NS}t") if node.text)


def text_from_file(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return text_from_docx(path)
    return path.read_text(encoding="utf-8", errors="replace")


def check_text(text: str) -> dict:
    matches = {}
    for name, pattern in LATEX_PATTERNS.items():
        found = pattern.findall(text)
        matches[name] = {
            "count": len(found),
            "samples": [sample[:160].replace("\n", " ") for sample in found[:10]],
        }
    return matches


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
    item["matches"] = check_text(text)
    item["latex_literal_count"] = sum(value["count"] for value in item["matches"].values())
    return item


def main() -> int:
    parser = argparse.ArgumentParser(description="Check files for raw LaTeX literals.")
    parser.add_argument("files", nargs="+", help="Markdown, text, or DOCX files to inspect.")
    parser.add_argument("--allow-found", action="store_true", help="Exit 0 even when LaTeX literals are found.")
    args = parser.parse_args()

    results = [check_path(Path(file).expanduser().resolve()) for file in args.files]
    print(json.dumps({"files": results}, ensure_ascii=False, indent=2))

    if any(not item.get("readable") for item in results):
        return 2

    found = any(item.get("latex_literal_count", 0) > 0 for item in results)
    if found and not args.allow_found:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

