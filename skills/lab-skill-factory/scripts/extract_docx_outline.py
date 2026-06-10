#!/usr/bin/env python3
"""Extract a DOCX outline, table summaries, and likely anchors."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
ANCHOR_PATTERNS = [
    re.compile(r"<[^>]{1,80}>"),
    re.compile(r"【[^】]{1,80}】"),
    re.compile(r"(实验目的|实验环境|实验内容|实验步骤|实验结果|实验小结|心得体会|意见与建议|考核结果|教师评语)"),
    re.compile(r"(目录|文档变更历史|编写目的|参考资料|系统部署|系统维护|故障排查)"),
]
REQUIREMENT_PATTERNS = [
    re.compile(
        r"(提交|命名|文件名|压缩|压缩包|打包|附件|源代码|源码|代码|Notebook|notebook|Jupyter|jupyter|ipynb|"
        r"ex\d+\.ipynb|标红|自行修改|运行截图|截图|浏览地址|本地地址|GitHub|github|系统地址|数据集|环境)"
    ),
]


def text_of(element: ET.Element) -> str:
    return "".join(node.text or "" for node in element.iter(f"{W}t")).strip()


def paragraph_style(paragraph: ET.Element) -> str | None:
    ppr = paragraph.find(f"{W}pPr")
    if ppr is None:
        return None
    style = ppr.find(f"{W}pStyle")
    if style is None:
        return None
    return style.attrib.get(f"{W}val")


def extract(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))

    paragraphs = []
    anchors = []
    requirement_paragraphs = []
    for index, paragraph in enumerate(root.iter(f"{W}p")):
        text = text_of(paragraph)
        if not text:
            continue
        style = paragraph_style(paragraph)
        item = {
            "index": index,
            "text": text[:300],
            "style": style,
        }
        paragraphs.append(item)
        if any(pattern.search(text) for pattern in ANCHOR_PATTERNS):
            anchors.append(item)
        if any(pattern.search(text) for pattern in REQUIREMENT_PATTERNS):
            requirement_paragraphs.append(item)

    tables = []
    for table_index, table in enumerate(root.iter(f"{W}tbl")):
        rows = []
        for row in table.iter(f"{W}tr"):
            cells = [text_of(cell)[:120] for cell in row.iter(f"{W}tc")]
            if any(cells):
                rows.append(cells)
        tables.append(
            {
                "index": table_index,
                "row_count": len(rows),
                "sample_rows": rows[:5],
            }
        )

    return {
        "path": str(path),
        "paragraph_count": len(paragraphs),
        "table_count": len(tables),
        "paragraphs": paragraphs,
        "paragraphs_head": paragraphs[:80],
        "paragraphs_tail": paragraphs[-80:],
        "anchors": anchors[:100],
        "requirement_paragraphs": requirement_paragraphs[:200],
        "tables": tables,
        "truncated": False,
        "review_note": "paragraphs contains the full document text in order. Read it from start to end, then inspect paragraphs_tail and requirement_paragraphs before asking requirements; submission rules are often at the end.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract DOCX outline and likely anchors.")
    parser.add_argument("docx", help="DOCX file to inspect.")
    args = parser.parse_args()

    path = Path(args.docx).expanduser().resolve()
    if not path.exists():
        print(json.dumps({"path": str(path), "exists": False}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(extract(path), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
