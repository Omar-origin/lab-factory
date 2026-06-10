#!/usr/bin/env python3
"""Basic DOCX validation for generated lab reports."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def read_document_xml(path: Path) -> ET.Element:
    with zipfile.ZipFile(path) as archive:
        return ET.fromstring(archive.read("word/document.xml"))


def paragraph_text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(f"{W}t"))


def paragraph_style(paragraph: ET.Element) -> str | None:
    ppr = paragraph.find(f"{W}pPr")
    if ppr is None:
        return None
    style = ppr.find(f"{W}pStyle")
    if style is None:
        return None
    return style.attrib.get(f"{W}val")


def summarize_docx(path: Path) -> dict:
    root = read_document_xml(path)
    paragraphs = root.findall(f".//{W}p")
    tables = root.findall(f".//{W}tbl")
    images = root.findall(f".//{A}blip")
    texts = [paragraph_text(paragraph) for paragraph in paragraphs]
    full_text = "\n".join(texts)
    placeholders = re.findall(r"【[^】]{1,80}】", full_text)
    headings = []
    for paragraph, text in zip(paragraphs, texts, strict=False):
        style = paragraph_style(paragraph) or ""
        if text.strip() and ("heading" in style.lower() or style.startswith("标题")):
            headings.append({"style": style, "text": text.strip()[:120]})

    return {
        "path": str(path),
        "valid_docx": True,
        "paragraph_count": len(paragraphs),
        "non_empty_paragraph_count": sum(1 for text in texts if text.strip()),
        "table_count": len(tables),
        "image_count": len(images),
        "placeholder_count": len(placeholders),
        "placeholder_samples": list(dict.fromkeys(placeholders[:20])),
        "has_disclaimer": "免责声明" in full_text,
        "heading_samples": headings[:30],
    }


def check_path(path: Path) -> dict:
    item = {"path": str(path), "exists": path.exists(), "valid_docx": False}
    if not path.exists():
        item["error"] = "file does not exist"
        return item
    if path.suffix.lower() != ".docx":
        item["error"] = "file is not .docx"
        return item
    try:
        return summarize_docx(path)
    except Exception as exc:  # noqa: BLE001 - CLI should report all validation errors.
        item["error"] = f"{type(exc).__name__}: {exc}"
        return item


def main() -> int:
    parser = argparse.ArgumentParser(description="Run basic DOCX checks.")
    parser.add_argument("files", nargs="+", help=".docx files to inspect.")
    parser.add_argument("--require-disclaimer", action="store_true", help="Fail if disclaimer is missing.")
    args = parser.parse_args()

    results = [check_path(Path(file).expanduser().resolve()) for file in args.files]
    print(json.dumps({"files": results}, ensure_ascii=False, indent=2))

    for result in results:
        if not result.get("valid_docx"):
            return 2
        if args.require_disclaimer and not result.get("has_disclaimer"):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

