#!/usr/bin/env python3
"""Validate that a skill-spec.md contains required sections."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


REQUIRED_HEADINGS = [
    "目标",
    "适配层级",
    "适配范围",
    "触发词",
    "输入材料",
    "文档理解与任务复述",
    "需求确认清单",
    "需要填写的区域",
    "不可触碰的区域",
    "写作规范",
    "内容粒度要求",
    "DOCX 工具策略",
    "工具环境与提交要求",
    "格式保全策略",
    "参考案例使用边界",
    "fill.md 结构",
    "fill-map.json 规则",
    "截图和绘图占位规则",
    "草稿流程",
    "Finalize 流程",
    "合规边界",
    "版本与迭代",
    "验收测试",
]


def normalize_heading(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().strip("#").strip())


def headings(markdown: str) -> set[str]:
    found = set()
    for line in markdown.splitlines():
        if line.startswith("#"):
            found.add(normalize_heading(line))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate lab skill-spec markdown.")
    parser.add_argument("skill_spec", help="Path to skill-spec.md.")
    args = parser.parse_args()

    path = Path(args.skill_spec).expanduser().resolve()
    result = {"path": str(path), "exists": path.exists(), "ok": False}
    if not path.exists():
        result["error"] = "file does not exist"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    markdown = path.read_text(encoding="utf-8", errors="replace")
    found = headings(markdown)
    missing = [heading for heading in REQUIRED_HEADINGS if heading not in found]
    result.update(
        {
            "ok": not missing,
            "missing_headings": missing,
            "found_headings": sorted(found),
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
