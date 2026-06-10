#!/usr/bin/env python3
"""Summarize lab-report input paths and infer likely material roles.

This script is intentionally conservative. It does not modify files and does
not decide the report plan by itself; it gives the agent a structured inventory
to reason from.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable


STANDARD_ROLES = {
    "实验任务书": "task_book",
    "实验所需文件": "related_files",
    "实验报告模板": "template",
    "成品实验报告": "sample_report",
    "实验相关课件": "course_materials",
    "实验原始数据.md": "raw_data",
    "个人信息.md": "personal_info",
    "评分标准.md": "rubric",
    "输出文件要求.md": "output_requirements",
    "目标写作风格.md": "writing_style",
}

ROLE_KEYWORDS = [
    ("task_book", ["任务书", "实验要求", "实验指导", "实验说明", "assignment", "manual", "requirement"]),
    ("template", ["模板", "报告格式", "空白", "template"]),
    ("sample_report", ["成品", "样例", "参考报告", "sample", "example", "finished"]),
    ("course_materials", ["课件", "教材", "ppt", "lecture", "chapter"]),
    ("raw_data", ["原始数据", "测量", "结果", "日志", "截图", "data", "log", "result"]),
    ("personal_info", ["个人信息", "姓名", "学号", "班级", "profile"]),
    ("rubric", ["评分", "标准", "rubric", "checklist"]),
    ("output_requirements", ["输出", "命名", "提交", "format", "output", "submit"]),
    ("writing_style", ["风格", "语气", "style", "tone"]),
]

RELATED_EXTENSIONS = {
    ".py",
    ".ipynb",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".sql",
    ".csv",
    ".xlsx",
    ".xls",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".db",
    ".sqlite",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
DOC_EXTENSIONS = {".docx", ".doc", ".pdf", ".md", ".txt"}


def is_empty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size == 0
    except OSError:
        return False


def is_empty_dir(path: Path) -> bool:
    try:
        return path.is_dir() and not any(path.iterdir())
    except OSError:
        return False


def infer_role(path: Path) -> str:
    name = path.name.lower()
    ext = path.suffix.lower()

    if path.name in STANDARD_ROLES:
        return STANDARD_ROLES[path.name]

    for role, keywords in ROLE_KEYWORDS:
        if any(keyword.lower() in name for keyword in keywords):
            return role

    if ext in IMAGE_EXTENSIONS:
        return "raw_data"
    if ext in RELATED_EXTENSIONS:
        return "related_files"
    if ext in DOC_EXTENSIONS:
        return "unclassified_document"
    if path.is_dir():
        return "unclassified_folder"
    return "unclassified_file"


def iter_files(path: Path, max_files: int) -> Iterable[Path]:
    if path.is_file():
        yield path
        return

    count = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules", ".venv", "venv"}]
        for file_name in files:
            yield Path(root) / file_name
            count += 1
            if count >= max_files:
                return


def standard_folder_score(path: Path) -> dict:
    if not path.is_dir():
        return {"is_candidate": False, "matched_roles": []}
    try:
        names = {child.name for child in path.iterdir()}
    except OSError:
        names = set()
    matched = [name for name in STANDARD_ROLES if name in names]
    return {"is_candidate": len(matched) >= 3, "matched_roles": matched}


def summarize_path(path: Path, max_files: int) -> dict:
    exists = path.exists()
    summary = {
        "path": str(path),
        "exists": exists,
        "type": "missing",
        "role": infer_role(path),
        "standard_folder": standard_folder_score(path),
        "children": [],
    }

    if not exists:
        return summary

    if path.is_file():
        summary["type"] = "file"
        summary["size_bytes"] = path.stat().st_size
        summary["extension"] = path.suffix.lower()
        summary["is_empty"] = is_empty_file(path)
        return summary

    summary["type"] = "directory"
    summary["is_empty"] = is_empty_dir(path)
    for file_path in iter_files(path, max_files=max_files):
        try:
            stat = file_path.stat()
            size = stat.st_size
        except OSError:
            size = None
        summary["children"].append(
            {
                "path": str(file_path),
                "relative_path": str(file_path.relative_to(path)),
                "extension": file_path.suffix.lower(),
                "size_bytes": size,
                "is_empty": is_empty_file(file_path),
                "role": infer_role(file_path),
            }
        )
    summary["truncated"] = len(summary["children"]) >= max_files
    return summary


def build_role_index(summaries: list[dict]) -> dict[str, list[str]]:
    role_index: dict[str, list[str]] = {}

    def add(role: str, path: str) -> None:
        role_index.setdefault(role, []).append(path)

    for summary in summaries:
        if summary["exists"]:
            add(summary["role"], summary["path"])
        for child in summary.get("children", []):
            if child["is_empty"]:
                continue
            add(child["role"], child["path"])
    return role_index


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect lab-report input paths.")
    parser.add_argument("paths", nargs="+", help="Files or directories to inspect.")
    parser.add_argument("--max-files", type=int, default=300, help="Maximum files to list per directory.")
    args = parser.parse_args()

    summaries = [summarize_path(Path(path).expanduser().resolve(), args.max_files) for path in args.paths]
    result = {
        "inputs": summaries,
        "role_index": build_role_index(summaries),
        "notes": [
            "Empty files and empty folders should be skipped unless the user explicitly asks otherwise.",
            "Use task_book as the highest-priority source; use template for formatting; use sample_report only for completeness and style profile.",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

