#!/usr/bin/env python3
"""Check that a draft DOCX preserves important source-template text.

This is a guardrail for draft generation. It is intentionally conservative:
the script does not require every source text fragment to remain unchanged,
but it highlights likely accidental deletion of template pages, headings,
rubrics, and anchors such as the original experiment-summary heading.
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

DEFAULT_REQUIRED_PATTERNS = [
    "目录",
    "实验目的",
    "实验环境",
    "实验内容",
    "实验内容与结果",
    "实验小结",
    "考核结果",
    "报告成绩",
    "教师评语",
    "批改时间",
]


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def read_docx_texts(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))

    texts: list[str] = []
    for paragraph in root.iter(f"{W}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{W}t")).strip()
        if text:
            texts.append(text)

    return texts


def make_fragments(texts: list[str], min_chars: int) -> list[str]:
    fragments: list[str] = []
    seen: set[str] = set()
    for text in texts:
        cleaned = normalize(text)
        if len(cleaned) < min_chars:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        fragments.append(text)
    return fragments


def find_missing_fragments(source_texts: list[str], draft_text: str, min_chars: int, max_samples: int) -> list[str]:
    missing: list[str] = []
    normalized_draft = normalize(draft_text)
    for fragment in make_fragments(source_texts, min_chars=min_chars):
        if normalize(fragment) not in normalized_draft:
            missing.append(fragment)
            if len(missing) >= max_samples:
                break
    return missing


def check_required_patterns(source_text: str, draft_text: str, patterns: list[str]) -> list[str]:
    missing: list[str] = []
    normalized_source = normalize(source_text)
    normalized_draft = normalize(draft_text)
    for pattern in patterns:
        normalized_pattern = normalize(pattern)
        if normalized_pattern in normalized_source and normalized_pattern not in normalized_draft:
            missing.append(pattern)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare source and draft DOCX text preservation.")
    parser.add_argument("source_docx", help="Original template/report DOCX.")
    parser.add_argument("draft_docx", help="Generated draft DOCX.")
    parser.add_argument("--min-fragment-chars", type=int, default=8)
    parser.add_argument("--max-missing-samples", type=int, default=40)
    parser.add_argument(
        "--required",
        action="append",
        default=[],
        help="Required text pattern that must remain if present in the source. Can be repeated.",
    )
    parser.add_argument("--allow-missing-fragments", action="store_true")
    args = parser.parse_args()

    source_path = Path(args.source_docx).expanduser().resolve()
    draft_path = Path(args.draft_docx).expanduser().resolve()

    result = {
        "source": str(source_path),
        "draft": str(draft_path),
        "source_exists": source_path.exists(),
        "draft_exists": draft_path.exists(),
        "ok": False,
    }

    if not source_path.exists() or not draft_path.exists():
        result["error"] = "source or draft file does not exist"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    try:
        source_texts = read_docx_texts(source_path)
        draft_texts = read_docx_texts(draft_path)
    except Exception as exc:  # noqa: BLE001 - CLI should report any DOCX parsing issue.
        result["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    source_text = "\n".join(source_texts)
    draft_text = "\n".join(draft_texts)
    required_patterns = DEFAULT_REQUIRED_PATTERNS + args.required
    missing_required = check_required_patterns(source_text, draft_text, required_patterns)
    missing_fragments = find_missing_fragments(
        source_texts,
        draft_text,
        min_chars=args.min_fragment_chars,
        max_samples=args.max_missing_samples,
    )

    result.update(
        {
            "source_paragraph_count": len(source_texts),
            "draft_paragraph_count": len(draft_texts),
            "missing_required_patterns": missing_required,
            "missing_fragment_count_sampled": len(missing_fragments),
            "missing_fragment_samples": missing_fragments,
            "ok": not missing_required and (args.allow_missing_fragments or not missing_fragments),
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if missing_required:
        return 1
    if missing_fragments and not args.allow_missing_fragments:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

