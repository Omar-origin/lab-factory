#!/usr/bin/env python3
"""Inspect lab-report materials and infer roles for skill-spec generation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


ROLE_KEYWORDS = [
    ("task_book", ["任务书", "实验要求", "实验指导", "实验说明", "assignment", "manual", "requirement"]),
    ("report_template", ["模板", "报告格式", "空白", "课程实验报告", "template"]),
    ("reference_case", ["参考案例", "成品", "样例", "往期", "参考报告", "sample", "example"]),
    ("rubric", ["评分", "考核", "标准", "rubric"]),
    ("personal_info", ["个人信息", "姓名", "学号", "班级"]),
    ("output_requirement", ["输出", "命名", "提交", "文件名", "压缩包", "打包", "rar", "zip"]),
    ("tool_requirement", ["jupyter", "notebook", "ipynb", "anaconda", "vscode", "matlab", "logisim", "packet", "dosbox", "github", "浏览地址", "本地地址"]),
    ("source_or_data", ["源码", "源代码", "代码", "数据", "dataset", "data", "src", "log", "日志"]),
    ("course_material", ["课件", "教材", "PPT", "lecture", "chapter"]),
]

TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".xml", ".yaml", ".yml", ".sql"}
DOC_EXTENSIONS = {".docx", ".doc", ".pdf"}
CODE_EXTENSIONS = {".py", ".ipynb", ".java", ".c", ".cpp", ".js", ".ts", ".html", ".css"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def infer_role(path: Path) -> str:
    name = path.name.lower()
    suffix = path.suffix.lower()
    for role, keywords in ROLE_KEYWORDS:
        if any(keyword.lower() in name for keyword in keywords):
            return role
    if suffix in IMAGE_EXTENSIONS:
        return "evidence_image"
    if suffix in CODE_EXTENSIONS:
        return "source_or_data"
    if suffix in TEXT_EXTENSIONS:
        return "source_or_data"
    if suffix in DOC_EXTENSIONS:
        return "document_unknown"
    if path.is_dir():
        return "folder_unknown"
    return "file_unknown"


def iter_children(path: Path, max_files: int) -> list[dict]:
    if path.is_file():
        return []
    children: list[dict] = []
    count = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules", ".venv", "venv"}]
        for file_name in files:
            file_path = Path(root) / file_name
            try:
                size = file_path.stat().st_size
            except OSError:
                size = None
            children.append(
                {
                    "path": str(file_path),
                    "relative_path": str(file_path.relative_to(path)),
                    "extension": file_path.suffix.lower(),
                    "role": infer_role(file_path),
                    "size_bytes": size,
                }
            )
            count += 1
            if count >= max_files:
                return children
    return children


def summarize(path_string: str, max_files: int) -> dict:
    path = Path(path_string).expanduser().resolve()
    item = {
        "path": str(path),
        "exists": path.exists(),
        "role": infer_role(path),
        "type": "missing",
    }
    if not path.exists():
        return item
    if path.is_file():
        item.update(
            {
                "type": "file",
                "extension": path.suffix.lower(),
                "size_bytes": path.stat().st_size,
            }
        )
    else:
        item.update(
            {
                "type": "directory",
                "children": iter_children(path, max_files),
            }
        )
    return item


def build_role_index(items: list[dict]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}

    def add(role: str, path: str) -> None:
        index.setdefault(role, []).append(path)

    for item in items:
        if item["exists"]:
            add(item["role"], item["path"])
        for child in item.get("children", []):
            add(child["role"], child["path"])
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect lab-report materials for skill factory workflows.")
    parser.add_argument("paths", nargs="+", help="Input files or folders.")
    parser.add_argument("--max-files", type=int, default=300)
    args = parser.parse_args()

    items = [summarize(path, args.max_files) for path in args.paths]
    result = {
        "inputs": items,
        "role_index": build_role_index(items),
        "next_step": "Fully read task/template materials including tail submission notes, then create skill-spec.md; confirm tools, source artifacts, screenshots, packaging, and naming before drafting a subject skill.",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
