#!/usr/bin/env python3
"""Lab Factory v2 deterministic engine.

The host agent understands requirements and writes content.  This module owns
the fragile parts: OOXML inventory, placement confidence, minimal writeback,
workflow state, local writing profiles, similarity gates, and v1 migration.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import os
import re
import secrets
import shutil
import statistics
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from lxml import etree


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "v": "urn:schemas-microsoft-com:vml",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}
DISCLAIMER_TEXT = (
    "AI 辅助生成声明：本文档由 Lab Factory 辅助生成，仅供学习与实验报告草稿参考。"
    "本工具不以实施学术欺诈为目的，不生成或认可伪造的实验数据、截图、运行结果或完成事实。"
    "使用者应核验全部内容、补充真实证据，并遵守所在学校、课程和教师关于 AI 使用及学术诚信的规定。"
    "最终提交与使用责任由使用者承担。"
)
W = f"{{{NS['w']}}}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
PROFILE_VERSION = "2.0"
AUTO_THRESHOLD = 0.90
CONFIRM_THRESHOLD = 0.65
AUTO_MARGIN = 0.15
FAMILY_COMPATIBILITY_THRESHOLD = 0.72
PERSONAL_PROFILE_VERSION = "1.0"
WRITER_GENOME_VERSION = "3.0"

AI_PROSE_PATTERNS: dict[str, re.Pattern[str]] = {
    "significance_inflation": re.compile(
        r"(?:标志着|彰显(?:了)?|凸显(?:了)?|体现(?:了)?|奠定(?:了)?基础|不可磨灭|关键转折点|不断演变的格局)"
    ),
    "promotional_language": re.compile(
        r"(?:令人叹为观止|充满活力|丰富的文化|开创性的|无缝(?:的)?|卓越(?:的)?|迷人(?:的)?|必游之地)"
    ),
    "vague_attribution": re.compile(r"(?:行业报告显示|观察者指出|专家认为|一些批评者认为|多项研究表明)"),
    "negative_parallelism": re.compile(r"(?:不仅仅?是|不只是).{0,32}(?:而且|更是|而是)"),
    "formulaic_connectors": re.compile(r"(?:首先|其次|再次|此外|最后|综上所述|总而言之)"),
    "generic_conclusion": re.compile(
        r"(?:未来(?:发展)?前景(?:十分)?广阔|迈出了重要一步|具有十分重要的意义|为后续.{0,20}奠定了基础)"
    ),
    "chatbot_trace": re.compile(r"(?:希望这对你|希望这对您|如果您想|如果你想|请告诉我|当然[！!]|好问题[！!])"),
    "empty_emphasis": re.compile(r"(?:至关重要|深入探讨|值得注意的是|毋庸置疑|不难发现)"),
}

TEMPLATE_OR_METADATA = re.compile(
    r"^(?:实验(?:名称|题目|目的|要求|内容|步骤|环境|日期)|课程名称|指导教师|教师|姓名|学号|班级|学院|专业|成绩|评语|提交要求)\s*[:：]?\s*$"
)
CODE_LINE = re.compile(
    r"^\s*(?:#include\b|import\s+[A-Za-z_]|from\s+[A-Za-z_.]+\s+import\b|def\s+\w+\s*\(|class\s+\w+|public\s+static\b|function\s+\w+|const\s+\w+\s*=|let\s+\w+\s*=|\w+\s*\([^)]*\)\s*\{)"
)
STATES = [
    "materials_scanned",
    "requirements_confirmed",
    "sections_resolved",
    "placements_resolved",
    "content_ready",
    "draft_generated",
    "draft_reviewed",
    "finalized",
    "iteration_decided",
]


class V2Error(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_docx_disclaimer(path: Path) -> dict[str, Any]:
    """Append the fixed disclosure once, without changing any source document."""
    fd, temporary_name = tempfile.mkstemp(prefix=".lab-factory-disclaimer-", suffix=".docx", dir=str(path.parent))
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, "w") as destination:
            for info in source.infolist():
                raw = source.read(info.filename)
                if info.filename == "word/document.xml":
                    root = etree.fromstring(raw)
                    body_matches = root.xpath("/w:document/w:body", namespaces=NS)
                    if len(body_matches) != 1:
                        raise V2Error("DOCX has no unique word/document.xml body; disclaimer cannot be appended safely")
                    body = body_matches[0]
                    matches = [
                        paragraph for paragraph in body.xpath(".//w:p", namespaces=NS)
                        if element_text(paragraph) == DISCLAIMER_TEXT
                    ]
                    for duplicate in matches[1:]:
                        parent = duplicate.getparent()
                        if parent is not None:
                            parent.remove(duplicate)
                    if not matches:
                        paragraph = etree.Element(W + "p")
                        run = etree.SubElement(paragraph, W + "r")
                        text_node = etree.SubElement(run, W + "t")
                        text_node.set(XML_SPACE, "preserve")
                        text_node.text = DISCLAIMER_TEXT
                        section_properties = body.find(W + "sectPr")
                        if section_properties is None:
                            body.append(paragraph)
                        else:
                            body.insert(body.index(section_properties), paragraph)
                    raw = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                destination.writestr(info, raw)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    with zipfile.ZipFile(path) as package:
        root = etree.fromstring(package.read("word/document.xml"))
    count = sum(
        1 for paragraph in root.xpath("/w:document/w:body//w:p", namespaces=NS)
        if element_text(paragraph) == DISCLAIMER_TEXT
    )
    if count != 1:
        raise V2Error(f"Disclaimer verification failed: expected 1 paragraph, found {count}")
    return {"ok": True, "document": str(path), "disclaimer_count": count}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).lower()


def compact_text(value: str) -> str:
    return re.sub(r"[^\w\u3400-\u9fff]+", "", value.lower())


def element_text(element: etree._Element) -> str:
    return "".join(element.xpath(".//w:t/text()", namespaces=NS)).strip()


def child_value(element: etree._Element, xpath: str) -> str | None:
    values = element.xpath(xpath, namespaces=NS)
    if not values:
        return None
    value = values[0]
    if isinstance(value, etree._Element):
        return value.get(f"{W}val")
    return str(value)


def heading_metadata(
    paragraph: etree._Element,
    text: str | None = None,
    style_headings: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Infer a visible heading level without trusting a single Word convention."""
    value = (text if text is not None else element_text(paragraph)).strip()
    style_id = child_value(paragraph, "./w:pPr/w:pStyle") or ""
    outline = child_value(paragraph, "./w:pPr/w:outlineLvl")
    level: int | None = None
    style_match = re.search(r"(?:heading|标题)[ _-]*([1-9])", style_id, re.IGNORECASE)
    style_metadata = (style_headings or {}).get(style_id) or {}
    if style_metadata.get("level"):
        level = int(style_metadata["level"])
    elif style_match:
        level = int(style_match.group(1))
    elif outline is not None and outline.isdigit():
        level = int(outline) + 1
    number_match = re.match(
        r"^\s*(?:(\d+(?:\.\d+)+)[、.．]?\s*|(\d{1,2})[、.．]\s*|(\d{1,2})\s+)(?=\D)",
        value,
    )
    number_text = next((group for group in number_match.groups() if group), None) if number_match else None
    if level is None and number_text:
        level = len(number_text.split("."))
    title = value[number_match.end():].strip() if number_match else value
    return {
        "level": level,
        "number_text": number_text,
        "title": title,
        "style_name": style_metadata.get("name"),
    }


def paragraph_style_headings(archive: zipfile.ZipFile) -> dict[str, dict[str, Any]]:
    if "word/styles.xml" not in archive.namelist():
        return {}
    root = etree.fromstring(archive.read("word/styles.xml"))
    result: dict[str, dict[str, Any]] = {}
    for style in root.xpath("./w:style[@w:type='paragraph']", namespaces=NS):
        style_id = style.get(f"{W}styleId")
        if not style_id:
            continue
        name = child_value(style, "./w:name") or ""
        outline = child_value(style, "./w:pPr/w:outlineLvl")
        level: int | None = None
        name_match = re.search(r"(?:heading|标题)[ _-]*([1-9])", name, re.IGNORECASE)
        if name_match:
            level = int(name_match.group(1))
        elif outline is not None and outline.isdigit() and int(outline) <= 8:
            level = int(outline) + 1
        result[style_id] = {"name": name or None, "level": level}
    return result


def story_parts(names: Iterable[str]) -> list[tuple[str, str]]:
    result = [("document", "word/document.xml")]
    for name in sorted(names):
        if re.fullmatch(r"word/header\d+\.xml", name):
            result.append((Path(name).stem, name))
        elif re.fullmatch(r"word/footer\d+\.xml", name):
            result.append((Path(name).stem, name))
    return result


def ancestor(element: etree._Element, local_name: str) -> etree._Element | None:
    current = element.getparent()
    while current is not None:
        if etree.QName(current).localname == local_name:
            return current
        current = current.getparent()
    return None


def has_ancestor(element: etree._Element, local_name: str) -> bool:
    return ancestor(element, local_name) is not None


def is_alternate_content_fallback(element: etree._Element) -> bool:
    """Ignore duplicate fallback markup when a modern Choice is present."""
    fallback = ancestor(element, "Fallback")
    if fallback is None:
        return False
    alternate = fallback.getparent()
    if alternate is None or etree.QName(alternate).localname != "AlternateContent":
        return False
    return any(etree.QName(child).localname == "Choice" for child in alternate)


def direct_index(element: etree._Element, local_name: str) -> int:
    parent = element.getparent()
    if parent is None:
        return 0
    matches = [child for child in parent if etree.QName(child).localname == local_name]
    return matches.index(element)


def table_coordinates(paragraph: etree._Element, root: etree._Element) -> dict[str, int] | None:
    cell = ancestor(paragraph, "tc")
    row = ancestor(paragraph, "tr")
    table = ancestor(paragraph, "tbl")
    if cell is None or row is None or table is None:
        return None
    tables = root.xpath(".//w:tbl", namespaces=NS)
    return {
        "table": tables.index(table),
        "row": direct_index(row, "tr"),
        "cell": direct_index(cell, "tc"),
        "paragraph": direct_index(paragraph, "p"),
    }


def unsupported_reasons(paragraph: etree._Element) -> list[str]:
    reasons: list[str] = []
    if has_ancestor(paragraph, "txbxContent"):
        reasons.append("text_box")
    checks = {
        "formula": ".//m:oMath | .//m:oMathPara",
        "field": ".//w:fldChar | .//w:instrText",
        "revision": ".//w:ins | .//w:del | ancestor::w:ins | ancestor::w:del",
    }
    for label, xpath in checks.items():
        if paragraph.xpath(xpath, namespaces=NS):
            reasons.append(label)
    return reasons


FAMILY_LABEL_KEYWORDS = (
    "实验", "报告", "课程", "目的", "原理", "内容", "步骤", "结果", "分析", "小结", "总结",
    "要求", "环境", "工具", "任务", "项目", "题目", "代码", "截图", "附录", "学号", "姓名",
    "班级", "专业", "日期", "时间", "成绩", "等级", "教师", "指导",
)


def stable_family_label(value: str) -> str | None:
    value = normalize_text(value)
    if not value or len(value) > 80 or not any(keyword in value for keyword in FAMILY_LABEL_KEYWORDS):
        return None
    value = re.sub(r"\d{3,}", "#", value)
    value = re.sub(r"(姓名|学号|班级|专业)[：:].*$", r"\1", value)
    return value[:80]


def build_family_signature(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    labels = sorted({label for node in nodes if (label := stable_family_label(node.get("normalized_text", "")))})
    header_footer_labels = sorted({
        re.sub(r"\d{3,}", "#", node.get("normalized_text", ""))[:120]
        for node in nodes
        if node.get("story") != "document" and node.get("normalized_text")
    })
    table_cells: dict[int, set[tuple[int, int]]] = {}
    for node in nodes:
        coordinates = node.get("coordinates")
        if not coordinates:
            continue
        table_cells.setdefault(coordinates["table"], set()).add((coordinates["row"], coordinates["cell"]))
    table_shapes = []
    for table_index in sorted(table_cells):
        cells = table_cells[table_index]
        row_count = max(row for row, _ in cells) + 1
        max_cell_count = max(sum(1 for item_row, _ in cells if item_row == row) for row in range(row_count))
        table_shapes.append(f"{row_count}x{max_cell_count}")
    container_counts = {
        container: sum(1 for node in nodes if node.get("container") == container)
        for container in ("paragraph", "table_cell")
    }
    return {
        "version": 1,
        "stories": sorted({node.get("story", "") for node in nodes}),
        "labels": labels,
        "header_footer_labels": header_footer_labels,
        "table_shapes": table_shapes,
        "container_counts": container_counts,
        "unsupported_types": sorted({reason for node in nodes for reason in node.get("unsupported", [])}),
    }


def overlap_coefficient(left: Iterable[str], right: Iterable[str]) -> tuple[float, int]:
    left_set, right_set = set(left), set(right)
    if not left_set and not right_set:
        return 1.0, 0
    if not left_set or not right_set:
        return 0.0, 0
    intersection = len(left_set & right_set)
    return intersection / min(len(left_set), len(right_set)), intersection


def family_signature_similarity(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    story_score, story_matches = overlap_coefficient(left.get("stories", []), right.get("stories", []))
    label_score, label_matches = overlap_coefficient(left.get("labels", []), right.get("labels", []))
    header_score, header_matches = overlap_coefficient(
        left.get("header_footer_labels", []), right.get("header_footer_labels", [])
    )
    table_score, table_matches = overlap_coefficient(left.get("table_shapes", []), right.get("table_shapes", []))
    left_counts = left.get("container_counts") or {}
    right_counts = right.get("container_counts") or {}
    left_total = max(1, sum(int(value) for value in left_counts.values()))
    right_total = max(1, sum(int(value) for value in right_counts.values()))
    proportions = []
    for key in ("paragraph", "table_cell"):
        proportions.append(1.0 - abs(int(left_counts.get(key, 0)) / left_total - int(right_counts.get(key, 0)) / right_total))
    container_score = sum(proportions) / len(proportions)
    score = round(
        0.10 * story_score
        + 0.35 * label_score
        + 0.25 * header_score
        + 0.15 * table_score
        + 0.15 * container_score,
        4,
    )
    evidence = int(label_matches >= 3) + int(header_matches >= 1) + int(table_matches >= 1)
    compatible = score >= FAMILY_COMPATIBILITY_THRESHOLD and evidence >= 2
    return {
        "score": score,
        "compatible": compatible,
        "threshold": FAMILY_COMPATIBILITY_THRESHOLD,
        "evidence": evidence,
        "matches": {
            "stories": story_matches,
            "labels": label_matches,
            "header_footer_labels": header_matches,
            "table_shapes": table_matches,
        },
        "features": {
            "stories": round(story_score, 4),
            "labels": round(label_score, 4),
            "header_footer_labels": round(header_score, 4),
            "table_shapes": round(table_score, 4),
            "container_distribution": round(container_score, 4),
        },
    }


def inventory_docx(path: Path) -> dict[str, Any]:
    if not path.exists() or path.suffix.lower() != ".docx":
        raise V2Error(f"DOCX does not exist or has wrong extension: {path}")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        style_headings = paragraph_style_headings(archive)
        nodes: list[dict[str, Any]] = []
        parts: dict[str, str] = {}
        story_counts: dict[str, int] = {}
        image_relationships = 0
        for story, part_name in story_parts(names):
            raw = archive.read(part_name)
            parts[part_name] = sha256(raw)
            root = etree.fromstring(raw)
            tree = root.getroottree()
            paragraphs = [
                paragraph for paragraph in root.xpath(".//w:p", namespaces=NS)
                if not is_alternate_content_fallback(paragraph)
            ]
            story_counts[story] = len(paragraphs)
            provisional: list[dict[str, Any]] = []
            for order, paragraph in enumerate(paragraphs):
                text = element_text(paragraph)
                coordinates = table_coordinates(paragraph, root)
                container = "table_cell" if coordinates else "paragraph"
                path_value = tree.getpath(paragraph)
                style_id = child_value(paragraph, "./w:pPr/w:pStyle")
                numbering = {
                    "num_id": child_value(paragraph, "./w:pPr/w:numPr/w:numId"),
                    "level": child_value(paragraph, "./w:pPr/w:numPr/w:ilvl"),
                }
                heading = heading_metadata(paragraph, text, style_headings)
                ppr = paragraph.find(f"{W}pPr")
                rpr = paragraph.find(f".//{W}rPr")
                signature = {
                    "story": story,
                    "path": path_value,
                    "container": container,
                    "coordinates": coordinates,
                    "style_id": style_id,
                }
                provisional.append(
                    {
                        "node_id": "n_" + sha256(json.dumps(signature, sort_keys=True).encode())[:16],
                        "story": story,
                        "part_name": part_name,
                        "order": order,
                        "path": path_value,
                        "container": container,
                        "coordinates": coordinates,
                        "text": text[:1000],
                        "normalized_text": normalize_text(text)[:1000],
                        "style_id": style_id,
                        "numbering": numbering,
                        "heading_level": heading["level"],
                        "heading_number": heading["number_text"],
                        "heading_title": heading["title"] if heading["level"] else None,
                        "style_name": heading["style_name"],
                        "paragraph_properties_hash": sha256(etree.tostring(ppr)) if ppr is not None else None,
                        "run_properties_hash": sha256(etree.tostring(rpr)) if rpr is not None else None,
                        "unsupported": unsupported_reasons(paragraph),
                    }
                )
            for index, item in enumerate(provisional):
                previous_text = provisional[index - 1]["normalized_text"] if index else ""
                next_text = provisional[index + 1]["normalized_text"] if index + 1 < len(provisional) else ""
                item["context"] = {"previous": previous_text[:240], "next": next_text[:240]}
                item["context_hash"] = sha256(
                    f"{previous_text}|{item['normalized_text']}|{next_text}".encode("utf-8")
                )[:20]
                nodes.append(item)
        if "word/_rels/document.xml.rels" in names:
            rel_root = etree.fromstring(archive.read("word/_rels/document.xml.rels"))
            image_relationships = len(
                rel_root.xpath("//*[contains(@Type, '/image')]")
            )
        for name in names:
            if name.startswith("word/") and name.endswith(".xml") and name not in parts:
                parts[name] = sha256(archive.read(name))

    structure_tokens = [
        f"{node['story']}:{node['container']}:{node['style_id'] or ''}:{bool(node['unsupported'])}"
        for node in nodes
    ]
    label_tokens = [node["normalized_text"][:80] for node in nodes if 0 < len(node["normalized_text"]) <= 80]
    family_fingerprint = sha256("\n".join(structure_tokens).encode("utf-8"))
    family_signature = build_family_signature(nodes)
    heading_tree = [
        {
            "node_id": node["node_id"],
            "story": node["story"],
            "container": node["container"],
            "coordinates": node["coordinates"],
            "level": node["heading_level"],
            "number_text": node["heading_number"],
            "title": node["heading_title"],
            "text": node["text"],
            "style_id": node["style_id"],
            "style_name": node["style_name"],
            "numbering": node["numbering"],
            "unsupported": node["unsupported"],
        }
        for node in nodes
        if node.get("heading_level") in {1, 2, 3}
    ]
    return {
        "ok": True,
        "version": PROFILE_VERSION,
        "document": str(path.resolve()),
        "document_sha256": file_sha256(path),
        "family_fingerprint": family_fingerprint,
        "family_signature": family_signature,
        "content_fingerprint": sha256("\n".join(label_tokens).encode("utf-8")),
        "node_count": len(nodes),
        "story_counts": story_counts,
        "image_relationships": image_relationships,
        "nodes": nodes,
        "heading_tree": heading_tree,
        "part_hashes": parts,
        "limitations": [
            "Text boxes, formulas, fields, and tracked revisions are inventoried as unsupported and are never auto-written.",
            "Visual fidelity must still be reviewed in the user's final editor, commonly WPS.",
        ],
    }


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V2Error(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise V2Error(f"JSON top level must be an object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def validate_field_id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", value):
        raise V2Error(f"Invalid field id: {value!r}")
    return value


def create_template_profile(inventory: dict[str, Any], fields: list[dict[str, Any]], subject: str) -> dict[str, Any]:
    by_id = {node["node_id"]: node for node in inventory.get("nodes", [])}
    output_fields = []
    seen = set()
    for raw in fields:
        field_id = validate_field_id(raw.get("id"))
        if field_id in seen:
            raise V2Error(f"Duplicate field id: {field_id}")
        seen.add(field_id)
        node_id = raw.get("node_id")
        node = by_id.get(node_id)
        if node is None:
            raise V2Error(f"Unknown node_id for {field_id}: {node_id}")
        if node.get("unsupported"):
            raise V2Error(f"Cannot compile unsupported node for {field_id}: {node['unsupported']}")
        output_fields.append(
            {
                "id": field_id,
                "semantic_role": raw.get("semantic_role", field_id),
                "required": bool(raw.get("required", True)),
                "content_type": raw.get("content_type", "text"),
                "requires_real_evidence": bool(raw.get("requires_real_evidence", False)),
                "operation": raw.get("operation", "insert_after"),
                "locator": {
                    key: copy.deepcopy(node.get(key))
                    for key in (
                        "node_id", "story", "part_name", "path", "container", "coordinates", "text",
                        "normalized_text", "style_id", "numbering", "context", "context_hash",
                        "paragraph_properties_hash", "run_properties_hash",
                    )
                },
            }
        )
    return {
        "version": PROFILE_VERSION,
        "profile_id": "tp_" + uuid.uuid4().hex[:16],
        "subject": subject.strip() or "未命名课程",
        "created_at": now_iso(),
        "source_document_sha256": inventory.get("document_sha256"),
        "family_fingerprint": inventory.get("family_fingerprint"),
        "family_signature": copy.deepcopy(inventory.get("family_signature")),
        "thresholds": {
            "auto": AUTO_THRESHOLD,
            "confirm": CONFIRM_THRESHOLD,
            "margin": AUTO_MARGIN,
        },
        "fields": output_fields,
        "drift_history": [],
    }


def validate_template_profile(profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if profile.get("version") != PROFILE_VERSION:
        errors.append("version must be 2.0")
    if not isinstance(profile.get("family_fingerprint"), str):
        errors.append("family_fingerprint is required")
    fields = profile.get("fields")
    if not isinstance(fields, list) or not fields:
        errors.append("fields must be a non-empty array")
        return errors
    seen = set()
    for index, field in enumerate(fields):
        if not isinstance(field, dict):
            errors.append(f"fields[{index}] must be an object")
            continue
        try:
            field_id = validate_field_id(field.get("id"))
        except V2Error as exc:
            errors.append(str(exc))
            continue
        if field_id in seen:
            errors.append(f"duplicate field id: {field_id}")
        seen.add(field_id)
        locator = field.get("locator")
        if not isinstance(locator, dict) or not locator.get("path") or not locator.get("container"):
            errors.append(f"{field_id}: locator path and container are required")
        if field.get("operation") not in {"insert_after", "replace_placeholder", "fill_cell"}:
            errors.append(f"{field_id}: unsupported operation")
    return errors


def ratio(left: str | None, right: str | None) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def score_candidate(locator: dict[str, Any], node: dict[str, Any]) -> tuple[float, dict[str, float]]:
    if locator.get("story") != node.get("story"):
        return 0.0, {"story": 0.0}
    if locator.get("container") != node.get("container"):
        return 0.0, {"container": 0.0}
    features = {
        "path": 1.0 if locator.get("path") == node.get("path") else 0.0,
        "container": 1.0,
        "style": 1.0 if locator.get("style_id") == node.get("style_id") else 0.0,
        "text": ratio(locator.get("normalized_text"), node.get("normalized_text")),
        "previous": ratio((locator.get("context") or {}).get("previous"), (node.get("context") or {}).get("previous")),
        "next": ratio((locator.get("context") or {}).get("next"), (node.get("context") or {}).get("next")),
        "coordinates": 1.0 if locator.get("coordinates") == node.get("coordinates") else 0.0,
    }
    score = (
        0.35 * features["path"]
        + 0.15 * features["container"]
        + 0.10 * features["style"]
        + 0.18 * features["text"]
        + 0.07 * features["previous"]
        + 0.07 * features["next"]
        + 0.08 * features["coordinates"]
    )
    if node.get("unsupported"):
        score = 0.0
    return round(score, 4), features


def propose_placements(profile: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    errors = validate_template_profile(profile)
    if errors:
        raise V2Error("Invalid template profile: " + "; ".join(errors))
    thresholds = profile.get("thresholds") or {}
    auto = float(thresholds.get("auto", AUTO_THRESHOLD))
    confirm = float(thresholds.get("confirm", CONFIRM_THRESHOLD))
    required_margin = float(thresholds.get("margin", AUTO_MARGIN))
    family_exact_match = profile.get("family_fingerprint") == inventory.get("family_fingerprint")
    if family_exact_match:
        family_compatibility = {
            "score": 1.0,
            "compatible": True,
            "threshold": FAMILY_COMPATIBILITY_THRESHOLD,
            "evidence": 3,
            "matches": {},
            "features": {"exact_fingerprint": 1.0},
        }
    elif isinstance(profile.get("family_signature"), dict) and isinstance(inventory.get("family_signature"), dict):
        family_compatibility = family_signature_similarity(profile["family_signature"], inventory["family_signature"])
    else:
        family_compatibility = {
            "score": 0.0,
            "compatible": False,
            "threshold": FAMILY_COMPATIBILITY_THRESHOLD,
            "evidence": 0,
            "matches": {},
            "features": {"legacy_profile_without_signature": 1.0},
        }
    family_compatible = bool(family_compatibility["compatible"])
    proposals = []
    for field in profile["fields"]:
        scored = []
        for node in inventory.get("nodes", []):
            score, features = score_candidate(field["locator"], node)
            if not family_compatible:
                score = min(score, 0.89)
            if score > 0:
                scored.append(
                    {
                        "node_id": node["node_id"],
                        "score": score,
                        "features": features,
                        "story": node["story"],
                        "container": node["container"],
                        "coordinates": node.get("coordinates"),
                        "text": node.get("text", "")[:240],
                        "context": node.get("context"),
                        "path": node.get("path"),
                    }
                )
        scored.sort(key=lambda item: item["score"], reverse=True)
        best = scored[0] if scored else None
        second_score = scored[1]["score"] if len(scored) > 1 else 0.0
        margin = round((best["score"] if best else 0.0) - second_score, 4)
        if best and best["score"] >= auto and margin >= required_margin:
            decision = "auto"
        elif best and best["score"] >= confirm:
            decision = "confirm"
        else:
            decision = "blocked"
        proposals.append(
            {
                "field_id": field["id"],
                "decision": decision,
                "recommended_node_id": best["node_id"] if best else None,
                "score": best["score"] if best else 0.0,
                "margin": margin,
                "candidates": scored[:5],
            }
        )
    return {
        "ok": True,
        "version": PROFILE_VERSION,
        "profile_id": profile.get("profile_id"),
        "document_sha256": inventory.get("document_sha256"),
        "family_fingerprint_match": family_exact_match,
        "family_compatible": family_compatible,
        "family_compatibility": family_compatibility,
        "proposals": proposals,
        "summary": {
            key: sum(1 for item in proposals if item["decision"] == key)
            for key in ("auto", "confirm", "blocked")
        },
    }


def confirmed_profile(
    profile: dict[str, Any], inventory: dict[str, Any], plan: dict[str, Any], selections: list[dict[str, Any]], summary: str
) -> dict[str, Any]:
    selected = {
        item.get("field_id"): item.get("node_id")
        for item in selections if isinstance(item, dict)
    }
    node_by_id = {node["node_id"]: node for node in inventory.get("nodes", [])}
    proposal_by_field = {item["field_id"]: item for item in plan.get("proposals", [])}
    updated = copy.deepcopy(profile)
    changed_fields = []
    for field in updated.get("fields", []):
        proposal = proposal_by_field.get(field["id"])
        if proposal is None:
            raise V2Error(f"Placement plan is missing field: {field['id']}")
        if proposal.get("decision") == "blocked":
            raise V2Error(f"Blocked field cannot be confirmed: {field['id']}")
        node_id = selected.get(field["id"])
        if proposal.get("decision") == "confirm" and not node_id:
            raise V2Error(f"Field requires user selection: {field['id']}")
        node_id = node_id or proposal.get("recommended_node_id")
        allowed = {candidate["node_id"] for candidate in proposal.get("candidates", [])}
        if node_id not in allowed:
            raise V2Error(f"Selection is not an allowed candidate for {field['id']}")
        node = node_by_id.get(node_id)
        if node is None or node.get("unsupported"):
            raise V2Error(f"Selected node is missing or unsupported for {field['id']}")
        if node_id != field["locator"].get("node_id"):
            changed_fields.append(field["id"])
        field["locator"] = {
            key: copy.deepcopy(node.get(key))
            for key in (
                "node_id", "story", "part_name", "path", "container", "coordinates", "text",
                "normalized_text", "style_id", "numbering", "context", "context_hash",
                "paragraph_properties_hash", "run_properties_hash",
            )
        }
    updated["family_fingerprint"] = inventory.get("family_fingerprint")
    updated["family_signature"] = copy.deepcopy(inventory.get("family_signature"))
    updated["source_document_sha256"] = inventory.get("document_sha256")
    updated.setdefault("drift_history", []).append(
        {
            "at": now_iso(),
            "document_sha256": inventory.get("document_sha256"),
            "family_fingerprint": inventory.get("family_fingerprint"),
            "family_compatibility": copy.deepcopy(plan.get("family_compatibility")),
            "changed_fields": changed_fields,
            "user_confirmation_summary": summary,
        }
    )
    return updated


def active_numbering(paragraph: etree._Element) -> bool:
    num_id = child_value(paragraph, "./w:pPr/w:numPr/w:numId")
    return num_id not in {None, "0"}


def prompt_colored(paragraph: etree._Element) -> bool:
    colors = paragraph.xpath(
        "./w:pPr/w:rPr/w:color/@w:val | ./w:r/w:rPr/w:color/@w:val",
        namespaces=NS,
    )
    return any(str(value).lower() not in {"auto", "000000", "00000000"} for value in colors)


def normalize_content_run_color(run: etree._Element) -> None:
    """Turn explicit prompt colors into black while preserving font and size."""
    rpr = run.find(f"{W}rPr")
    if rpr is None:
        return
    color = rpr.find(f"{W}color")
    if color is None:
        return
    value = (color.get(f"{W}val") or "").lower()
    if value not in {"", "auto", "000000", "00000000"}:
        color.set(f"{W}val", "000000")


def looks_like_heading(paragraph: etree._Element) -> bool:
    text = element_text(paragraph)
    style_id = (child_value(paragraph, "./w:pPr/w:pStyle") or "").lower()
    if active_numbering(paragraph) or paragraph.find(f"./{W}pPr/{W}outlineLvl") is not None:
        return True
    if style_id.startswith("heading") or "标题" in style_id:
        return True
    if text and len(text) <= 40 and re.match(r"^\d+(?:\.\d+)*\s+\S+", text):
        return True
    sizes = paragraph.xpath("./w:pPr/w:rPr/w:sz/@w:val | ./w:r/w:rPr/w:sz/@w:val", namespaces=NS)
    return bool(text and len(text) <= 40 and any(str(value).isdigit() and int(value) > 28 for value in sizes))


def insert_style_reference(source: etree._Element) -> etree._Element:
    """Find nearby body formatting instead of copying a numbered heading."""
    candidates: list[tuple[int, etree._Element]] = []
    directions = ((source.itersiblings(), 2), (source.itersiblings(preceding=True), 0))
    for siblings, direction_bonus in directions:
        for distance, candidate in enumerate(siblings, start=1):
            if distance > 10:
                break
            if candidate.tag != f"{W}p":
                continue
            if unsupported_reasons(candidate) or looks_like_heading(candidate) or prompt_colored(candidate):
                continue
            text = element_text(candidate)
            score = direction_bonus - distance
            if not text:
                score += 100
            elif len(text) >= 30:
                score += 40
            sizes = candidate.xpath(
                "./w:pPr/w:rPr/w:sz/@w:val | ./w:r/w:rPr/w:sz/@w:val",
                namespaces=NS,
            )
            if any(str(value).isdigit() and int(value) <= 24 for value in sizes):
                score += 10
            candidates.append((score, candidate))
    return max(candidates, key=lambda item: item[0])[1] if candidates else source


def paragraph_with_text(
    source: etree._Element,
    text: str,
    *,
    strip_numbering: bool = False,
    normalize_color: bool = False,
) -> etree._Element:
    paragraph = copy.deepcopy(source)
    for attribute in list(paragraph.attrib):
        if etree.QName(attribute).localname in {"paraId", "textId"}:
            del paragraph.attrib[attribute]
    ppr = paragraph.find(f"{W}pPr")
    reference_rpr = paragraph.find(f".//{W}rPr")
    if strip_numbering and ppr is not None:
        num_pr = ppr.find(f"{W}numPr")
        if num_pr is not None:
            ppr.remove(num_pr)
        outline = ppr.find(f"{W}outlineLvl")
        if outline is not None:
            ppr.remove(outline)
    for child in list(paragraph):
        if child is not ppr:
            paragraph.remove(child)
    run = etree.SubElement(paragraph, f"{W}r")
    if reference_rpr is not None:
        run.append(copy.deepcopy(reference_rpr))
    if normalize_color:
        normalize_content_run_color(run)
    text_node = etree.SubElement(run, f"{W}t")
    if text.startswith(" ") or text.endswith(" "):
        text_node.set(XML_SPACE, "preserve")
    text_node.text = text
    return paragraph


def same_heading_scope(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("story") != "document" or right.get("story") != "document":
        return False
    if left.get("part_name") != right.get("part_name") or left.get("container") != right.get("container"):
        return False
    if left.get("container") != "table_cell":
        return True
    left_coordinates = left.get("coordinates") or {}
    right_coordinates = right.get("coordinates") or {}
    return all(
        left_coordinates.get(key) == right_coordinates.get(key)
        for key in ("table", "row", "cell")
    )


def create_section_plan(inventory: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    """Compile an AI-proposed heading expansion into a deterministic review plan."""
    requirements_summary = proposal.get("requirements_summary")
    user_request_summary = proposal.get("user_request_summary")
    material_sources = proposal.get("material_sources")
    requested = proposal.get("sections")
    if not isinstance(requirements_summary, str) or not requirements_summary.strip():
        raise V2Error("section plan requires requirements_summary after reading all materials")
    if not isinstance(user_request_summary, str) or not user_request_summary.strip():
        raise V2Error("section plan requires user_request_summary")
    if not isinstance(material_sources, list) or not material_sources or not all(
        isinstance(item, str) and item.strip() for item in material_sources
    ):
        raise V2Error("section plan requires a non-empty material_sources array")
    if not isinstance(requested, list) or not requested:
        raise V2Error("section plan sections must be a non-empty array")

    node_by_id = {node["node_id"]: node for node in inventory.get("nodes", [])}
    used_literal_numbers = {
        node["heading_number"] for node in inventory.get("nodes", []) if node.get("heading_number")
    }
    planned: dict[str, dict[str, Any]] = {}
    sections: list[dict[str, Any]] = []

    def resolve_reference(item: dict[str, Any], node_key: str, section_key: str) -> tuple[str, dict[str, Any]]:
        node_id = item.get(node_key)
        section_id = item.get(section_key)
        if bool(node_id) == bool(section_id):
            raise V2Error(f"{item.get('id')}: exactly one of {node_key} or {section_key} is required")
        if node_id:
            node = node_by_id.get(node_id)
            if node is None:
                raise V2Error(f"{item.get('id')}: unknown {node_key} {node_id}")
            return "node", node
        section = planned.get(section_id)
        if section is None:
            raise V2Error(f"{item.get('id')}: {section_key} must refer to an earlier planned section")
        return "section", section

    for raw in requested:
        if not isinstance(raw, dict):
            raise V2Error("section plan entries must be objects")
        section_id = validate_field_id(raw.get("id"))
        if section_id in planned:
            raise V2Error(f"Duplicate section id: {section_id}")
        title = raw.get("title")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 100 or "\n" in title:
            raise V2Error(f"{section_id}: title must be 1-100 characters on one line")
        title = title.strip()
        if re.match(r"^\s*\d+(?:\.\d+)*[、.．]?\s+", title):
            raise V2Error(f"{section_id}: title must not repeat the number prefix")
        level = raw.get("level")
        if level not in {2, 3}:
            raise V2Error(f"{section_id}: only level 2 or 3 headings are supported")
        style_source = node_by_id.get(raw.get("style_source_node_id"))
        if style_source is None:
            raise V2Error(f"{section_id}: unknown style_source_node_id")
        if style_source.get("unsupported"):
            raise V2Error(f"{section_id}: style source is unsupported: {style_source['unsupported']}")
        if style_source.get("heading_level") != level:
            raise V2Error(f"{section_id}: style source must be an existing level {level} heading")

        after_kind, after = resolve_reference(raw, "after_node_id", "after_section_id")
        parent_kind, parent = resolve_reference(raw, "parent_node_id", "parent_section_id")
        after_scope = after["scope_node"] if after_kind == "section" else after
        parent_scope = parent["scope_node"] if parent_kind == "section" else parent
        if after_scope.get("unsupported") or parent_scope.get("unsupported"):
            raise V2Error(f"{section_id}: anchor or parent is unsupported")
        if not same_heading_scope(style_source, after_scope) or not same_heading_scope(style_source, parent_scope):
            raise V2Error(f"{section_id}: style source, insertion anchor and parent must share one body container")
        parent_level = parent.get("level") if parent_kind == "section" else parent.get("heading_level")
        if parent_level != level - 1:
            raise V2Error(f"{section_id}: parent must be a level {level - 1} heading")
        if parent_kind == "node" and after_kind == "node":
            if int(after.get("order", -1)) <= int(parent.get("order", -1)):
                raise V2Error(f"{section_id}: insertion anchor must appear after its parent heading")
            for candidate in inventory.get("nodes", []):
                if not same_heading_scope(parent, candidate):
                    continue
                if int(parent.get("order", -1)) < int(candidate.get("order", -1)) <= int(after.get("order", -1)):
                    candidate_level = candidate.get("heading_level")
                    if candidate_level is not None and candidate_level <= parent_level:
                        raise V2Error(f"{section_id}: insertion anchor is outside the selected parent heading")
        elif parent_kind == "section" and after_kind == "section":
            if after["id"] != parent["id"] and (after.get("parent") or {}).get("id") != parent["id"]:
                raise V2Error(f"{section_id}: planned insertion anchor is outside the selected parent heading")

        numbering_mode = raw.get("numbering_mode", "literal")
        if numbering_mode not in {"literal", "automatic"}:
            raise V2Error(f"{section_id}: numbering_mode must be literal or automatic")
        number_text = raw.get("number_text")
        if numbering_mode == "literal":
            if not isinstance(number_text, str) or not re.fullmatch(r"\d+(?:\.\d+)+", number_text.strip()):
                raise V2Error(f"{section_id}: literal numbering requires number_text such as 2.2 or 2.2.1")
            number_text = number_text.strip()
            if len(number_text.split(".")) != level:
                raise V2Error(f"{section_id}: number_text does not match heading level {level}")
            if number_text in used_literal_numbers:
                raise V2Error(f"{section_id}: duplicate heading number {number_text}")
            parent_number = parent.get("number_text") if parent_kind == "section" else parent.get("heading_number")
            if parent_number and not number_text.startswith(f"{parent_number}."):
                raise V2Error(f"{section_id}: number_text must be a child of parent number {parent_number}")
            used_literal_numbers.add(number_text)
        else:
            number_text = None
            source_numbering = style_source.get("numbering") or {}
            if not source_numbering.get("num_id") and not style_source.get("style_id"):
                raise V2Error(f"{section_id}: automatic numbering requires a numbered or styled heading source")

        display_text = f"{number_text} {title}" if number_text else title
        compiled = {
            "id": section_id,
            "action": "insert_heading_after",
            "title": title,
            "display_text": display_text,
            "level": level,
            "numbering_mode": numbering_mode,
            "number_text": number_text,
            "style_source_node_id": style_source["node_id"],
            "after": {"kind": after_kind, "id": after["node_id"] if after_kind == "node" else after["id"]},
            "parent": {"kind": parent_kind, "id": parent["node_id"] if parent_kind == "node" else parent["id"]},
            "scope_node": style_source,
            "preview": f"新增 {level} 级标题：{display_text}",
        }
        sections.append({key: value for key, value in compiled.items() if key != "scope_node"})
        planned[section_id] = compiled

    return {
        "version": PROFILE_VERSION,
        "plan_id": "sp_" + uuid.uuid4().hex[:16],
        "status": "proposed",
        "created_at": now_iso(),
        "source_document": inventory.get("document"),
        "source_document_sha256": inventory.get("document_sha256"),
        "requirements_summary": requirements_summary.strip(),
        "user_request_summary": user_request_summary.strip(),
        "material_sources": [item.strip() for item in material_sources],
        "confirmation_required": True,
        "sections": sections,
        "preview": [item["preview"] for item in sections],
        "next_step": "Show this preview to the user and apply only after explicit confirmation.",
    }


def validate_section_plan(plan: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if plan.get("version") != PROFILE_VERSION:
        errors.append("version must be 2.0")
    if plan.get("status") != "proposed" or plan.get("confirmation_required") is not True:
        errors.append("section plan must remain proposed until the apply call records user confirmation")
    if plan.get("source_document_sha256") != inventory.get("document_sha256"):
        errors.append("section plan source hash does not match the target document")
    try:
        recreated = create_section_plan(
            inventory,
            {
                "requirements_summary": plan.get("requirements_summary"),
                "user_request_summary": plan.get("user_request_summary"),
                "material_sources": plan.get("material_sources"),
                "sections": [
                    {
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "level": item.get("level"),
                        "numbering_mode": item.get("numbering_mode"),
                        "number_text": item.get("number_text"),
                        "style_source_node_id": item.get("style_source_node_id"),
                        ("after_node_id" if (item.get("after") or {}).get("kind") == "node" else "after_section_id"): (item.get("after") or {}).get("id"),
                        ("parent_node_id" if (item.get("parent") or {}).get("kind") == "node" else "parent_section_id"): (item.get("parent") or {}).get("id"),
                    }
                    for item in plan.get("sections", [])
                    if isinstance(item, dict)
                ],
            },
        )
        if recreated["sections"] != plan.get("sections"):
            errors.append("section plan operations were modified after compilation")
    except V2Error as exc:
        errors.append(str(exc))
    return errors


def apply_section_plan(
    plan: dict[str, Any], target: Path, output: Path, user_confirmation_summary: str, overwrite: bool = False
) -> dict[str, Any]:
    if not user_confirmation_summary.strip():
        raise V2Error("section expansion requires a user confirmation summary")
    if target.resolve() == output.resolve():
        raise V2Error("Section expansion output must not overwrite the source document")
    if output.exists() and not overwrite:
        raise V2Error(f"Output already exists: {output}")
    inventory = inventory_docx(target)
    errors = validate_section_plan(plan, inventory)
    if errors:
        raise V2Error("Invalid section plan: " + "; ".join(errors))
    node_by_id = {node["node_id"]: node for node in inventory["nodes"]}
    source_hash = file_sha256(target)
    before_entries = zip_entry_hashes(target)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".lab-factory-sections-", suffix=".docx", dir=str(output.parent))
    os.close(fd)
    temporary = Path(temporary_name)
    audit: list[dict[str, Any]] = []
    try:
        by_part: dict[str, list[dict[str, Any]]] = {}
        for item in plan["sections"]:
            style_source = node_by_id[item["style_source_node_id"]]
            by_part.setdefault(style_source["part_name"], []).append(item)
        with zipfile.ZipFile(target) as source, zipfile.ZipFile(temporary, "w") as destination:
            for info in source.infolist():
                raw = source.read(info.filename)
                if info.filename in by_part:
                    root = etree.fromstring(raw)
                    existing_elements: dict[str, etree._Element] = {}
                    needed_node_ids = {
                        item["style_source_node_id"] for item in by_part[info.filename]
                    } | {
                        ref["id"]
                        for item in by_part[info.filename]
                        for ref in (item["after"], item["parent"])
                        if ref["kind"] == "node"
                    }
                    for node_id in needed_node_ids:
                        node = node_by_id[node_id]
                        matches = root.xpath(node["path"], namespaces=NS)
                        if len(matches) != 1:
                            raise V2Error(f"section plan node {node_id} resolved to {len(matches)} elements")
                        existing_elements[node_id] = matches[0]
                    inserted: dict[str, etree._Element] = {}
                    insertion_tails: dict[str, etree._Element] = {}
                    for item in by_part[info.filename]:
                        style_source = existing_elements[item["style_source_node_id"]]
                        after = item["after"]
                        if after["kind"] == "section":
                            anchor = inserted.get(after["id"])
                            if anchor is None:
                                raise V2Error(f"{item['id']}: planned insertion anchor is not available")
                        else:
                            anchor = insertion_tails.get(after["id"], existing_elements[after["id"]])
                        paragraph = paragraph_with_text(style_source, item["display_text"])
                        anchor.addnext(paragraph)
                        if after["kind"] == "node":
                            insertion_tails[after["id"]] = paragraph
                        inserted[item["id"]] = paragraph
                        audit.append(
                            {
                                "section_id": item["id"],
                                "action": "insert_heading_after",
                                "display_text": item["display_text"],
                                "level": item["level"],
                                "style_source_node_id": item["style_source_node_id"],
                                "after": item["after"],
                                "parent": item["parent"],
                            }
                        )
                    raw = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                destination.writestr(info, raw)
        if file_sha256(target) != source_hash:
            raise V2Error("Source document changed during section expansion")
        temporary_inventory = inventory_docx(temporary)
        temporary_texts = {node["text"] for node in temporary_inventory["nodes"]}
        missing = [item["display_text"] for item in plan["sections"] if item["display_text"] not in temporary_texts]
        if missing:
            raise V2Error(f"Inserted headings failed post-write verification: {missing}")
        ensure_docx_disclaimer(temporary)
        after_entries = zip_entry_hashes(temporary)
        changed_parts = sorted(name for name in before_entries if before_entries[name] != after_entries.get(name))
        expected_parts = set(by_part) | {"word/document.xml"}
        unexpected = sorted(set(changed_parts) - expected_parts)
        if unexpected:
            raise V2Error(f"Unexpected DOCX package parts changed: {unexpected}")
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    output_inventory = inventory_docx(output)
    return {
        "ok": True,
        "version": PROFILE_VERSION,
        "plan_id": plan.get("plan_id"),
        "source_document": str(target),
        "source_sha256": source_hash,
        "output_document": str(output),
        "output_sha256": file_sha256(output),
        "changed_parts": changed_parts,
        "untouched_part_count": len(before_entries) - len(changed_parts),
        "user_confirmation_summary": user_confirmation_summary.strip(),
        "audit": audit,
        "heading_tree": output_inventory["heading_tree"],
        "wps_review_required": True,
        "wps_review_checklist": ["新增标题层级", "标题编号连续性", "标题样式", "更新目录"],
        "mcp_next_step": "Re-inventory this expanded template before compiling placements and remind the user to update the TOC in WPS.",
    }


def replace_placeholder(paragraph: etree._Element, placeholder: str, content: str) -> bool:
    text_nodes = paragraph.xpath(".//w:t", namespaces=NS)
    full_text = "".join(node.text or "" for node in text_nodes)
    if placeholder not in full_text:
        return False
    start = full_text.index(placeholder)
    end = start + len(placeholder)
    offsets = []
    cursor = 0
    for node in text_nodes:
        value = node.text or ""
        offsets.append((node, cursor, cursor + len(value)))
        cursor += len(value)
    touched = [(node, left, right) for node, left, right in offsets if right > start and left < end]
    if not touched:
        return False
    first, first_left, first_right = touched[0]
    last, last_left, last_right = touched[-1]
    first_value = first.text or ""
    prefix = first_value[: max(0, start - first_left)]
    suffix = (last.text or "")[max(0, end - last_left) :]
    first.text = prefix + content + suffix
    first_run = ancestor(first, "r")
    if first_run is not None:
        normalize_content_run_color(first_run)
    for node, _, _ in touched[1:]:
        node.text = ""
    return True


def content_character_count(value: str) -> int:
    return len(re.sub(r"\s+", "", value))


def validate_content_quality(field_id: str, item: dict[str, Any], value: str) -> None:
    quality = item.get("quality")
    if quality is None:
        return
    if not isinstance(quality, dict):
        raise V2Error(f"{field_id}: quality must be an object")
    unit = quality.get("unit", "whole")
    minimum = quality.get("min_chars")
    maximum = quality.get("max_chars")
    if unit not in {"whole", "per_paragraph"}:
        raise V2Error(f"{field_id}: quality.unit must be whole or per_paragraph")
    if not isinstance(minimum, int) or minimum < 1:
        raise V2Error(f"{field_id}: quality.min_chars must be a positive integer")
    if not isinstance(maximum, int) or maximum < minimum:
        raise V2Error(f"{field_id}: quality.max_chars must be >= min_chars")
    segments = [value]
    if unit == "per_paragraph":
        segments = [line.strip() for line in value.splitlines() if line.strip()]
    for index, segment in enumerate(segments, start=1):
        length = content_character_count(segment)
        if length < minimum or length > maximum:
            label = f"paragraph {index}" if unit == "per_paragraph" else "content"
            raise V2Error(
                f"{field_id}: {label} has {length} characters; expected {minimum}-{maximum}"
            )


def template_cue_reasons(value: str) -> list[str]:
    reasons = []
    if re.search(r"(?i)(?:\b|_)x{2,}(?:\b|_)", value) or "XXX" in value.upper():
        reasons.append("xxx_placeholder")
    if re.search(r"<[^<>]{1,120}>", value):
        reasons.append("angle_placeholder")
    if any(token in value for token in ("待填写", "请在此处填写", "示例如下")):
        reasons.append("fill_prompt")
    return reasons


def remaining_template_cues(
    path: Path,
    limit: int = 50,
    ignored_texts: set[str] | None = None,
) -> list[dict[str, Any]]:
    cues = []
    seen = set()
    ignored_texts = ignored_texts or set()
    for node in inventory_docx(path).get("nodes", []):
        text = node.get("text", "")
        if text in ignored_texts:
            continue
        reasons = template_cue_reasons(text)
        unsupported = node.get("unsupported") or []
        key = (text, tuple(reasons), tuple(unsupported))
        if not reasons or key in seen:
            continue
        seen.add(key)
        cues.append(
            {
                "node_id": node.get("node_id"),
                "text": text[:200],
                "reasons": reasons,
                "manual_only": bool(unsupported),
                "unsupported": unsupported,
            }
        )
        if len(cues) >= limit:
            break
    return cues


def zip_entry_hashes(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        return {name: sha256(archive.read(name)) for name in archive.namelist()}


def resolve_content_items(
    profile: dict[str, Any], inventory: dict[str, Any], placement_plan: dict[str, Any], content: dict[str, Any]
) -> list[dict[str, Any]]:
    proposal_by_field = {item["field_id"]: item for item in placement_plan.get("proposals", [])}
    node_by_id = {node["node_id"]: node for node in inventory.get("nodes", [])}
    field_by_id = {field["id"]: field for field in profile.get("fields", [])}
    items = content.get("items")
    if not isinstance(items, list) or not items:
        raise V2Error("content package items must be a non-empty array")
    resolved = []
    for item in items:
        field_id = item.get("field_id")
        field = field_by_id.get(field_id)
        proposal = proposal_by_field.get(field_id)
        if field is None or proposal is None:
            raise V2Error(f"Unknown field in content package: {field_id}")
        selected = item.get("selected_node_id")
        if not selected:
            if proposal["decision"] != "auto":
                raise V2Error(f"{field_id} requires explicit placement confirmation")
            selected = proposal["recommended_node_id"]
        allowed = {candidate["node_id"] for candidate in proposal.get("candidates", [])}
        if selected not in allowed:
            raise V2Error(f"{field_id}: selected_node_id is not a proposed candidate")
        node = node_by_id.get(selected)
        if node is None or node.get("unsupported"):
            raise V2Error(f"{field_id}: selected node is missing or unsupported")
        value = item.get("content")
        if not isinstance(value, str) or not value.strip():
            raise V2Error(f"{field_id}: content must be a non-empty string")
        validate_content_quality(field_id, item, value)
        resolved.append({"field": field, "node": node, "content": value})
    return resolved


def apply_v2(
    profile: dict[str, Any], target: Path, content: dict[str, Any], output: Path, overwrite: bool = False
) -> dict[str, Any]:
    if target.resolve() == output.resolve():
        raise V2Error("Output must not overwrite the source document")
    if output.exists() and not overwrite:
        raise V2Error(f"Output already exists: {output}")
    source_hash = file_sha256(target)
    inventory = inventory_docx(target)
    placements = propose_placements(profile, inventory)
    resolved = resolve_content_items(profile, inventory, placements, content)
    part_changes: dict[str, list[dict[str, Any]]] = {}
    for item in resolved:
        part_changes.setdefault(item["node"]["part_name"], []).append(item)

    before_entries = zip_entry_hashes(target)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".lab-factory-v2-", suffix=".docx", dir=str(output.parent))
    os.close(fd)
    temporary = Path(temporary_name)
    audit = []
    try:
        with zipfile.ZipFile(target) as source, zipfile.ZipFile(temporary, "w") as destination:
            for info in source.infolist():
                raw = source.read(info.filename)
                if info.filename in part_changes:
                    root = etree.fromstring(raw)
                    resolved_targets = []
                    for index, change in enumerate(part_changes[info.filename]):
                        matches = root.xpath(change["node"]["path"], namespaces=NS)
                        if len(matches) != 1:
                            raise V2Error(
                                f"{change['field']['id']}: structural path resolved to {len(matches)} nodes"
                            )
                        resolved_targets.append((index, change, matches[0]))
                    # Insertions run first so a title replacement and body insertion may safely
                    # share one anchor.  All XPath lookups are completed before any mutation, so
                    # inserting an earlier paragraph cannot shift later structural paths.
                    ordered_targets = sorted(
                        resolved_targets,
                        key=lambda item: (0 if item[1]["field"]["operation"] == "insert_after" else 1, item[0]),
                    )
                    insertion_tails: dict[int, etree._Element] = {}
                    for _, change, paragraph in ordered_targets:
                        operation = change["field"]["operation"]
                        content_lines = [line for line in change["content"].splitlines() if line.strip()] or [change["content"]]
                        if operation == "insert_after":
                            current = insertion_tails.get(id(paragraph), paragraph)
                            style_reference = insert_style_reference(paragraph)
                            for line in content_lines:
                                new_paragraph = paragraph_with_text(
                                    style_reference,
                                    line,
                                    strip_numbering=True,
                                    normalize_color=True,
                                )
                                current.addnext(new_paragraph)
                                current = new_paragraph
                            insertion_tails[id(paragraph)] = current
                        elif operation == "replace_placeholder":
                            anchor = change["field"]["locator"].get("text") or ""
                            if not anchor or not replace_placeholder(paragraph, anchor, change["content"]):
                                raise V2Error(f"{change['field']['id']}: placeholder no longer matches")
                        elif operation == "fill_cell":
                            if change["node"]["container"] != "table_cell":
                                raise V2Error(f"{change['field']['id']}: fill_cell target is outside a table")
                            replacement = paragraph_with_text(paragraph, change["content"], normalize_color=True)
                            paragraph.getparent().replace(paragraph, replacement)
                        else:
                            raise V2Error(f"Unsupported operation: {operation}")
                        audit.append(
                            {
                                "field_id": change["field"]["id"],
                                "node_id": change["node"]["node_id"],
                                "part_name": info.filename,
                                "path": change["node"]["path"],
                                "container": change["node"]["container"],
                                "coordinates": change["node"].get("coordinates"),
                                "operation": operation,
                                "style_source": {
                                    "style_id": change["node"].get("style_id"),
                                    "paragraph_properties_hash": change["node"].get("paragraph_properties_hash"),
                                    "run_properties_hash": change["node"].get("run_properties_hash"),
                                },
                            }
                        )
                    raw = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                destination.writestr(info, raw)
        if file_sha256(target) != source_hash:
            raise V2Error("Source document changed during writeback")
        ensure_docx_disclaimer(temporary)
        after_entries = zip_entry_hashes(temporary)
        changed_parts = sorted(name for name in before_entries if before_entries[name] != after_entries.get(name))
        expected_parts = sorted(set(part_changes) | {"word/document.xml"})
        unexpected = sorted(set(changed_parts) - set(expected_parts))
        if unexpected:
            raise V2Error(f"Unexpected DOCX package parts changed: {unexpected}")
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    generated_lines = {
        line.strip()
        for item in resolved
        for line in item["content"].splitlines()
        if line.strip()
    }
    unresolved_cues = remaining_template_cues(output, ignored_texts=generated_lines)
    review_checklist = ["写入位置", "表格边框与合并单元格", "分页与行距", "图片和公式位置"]
    if unresolved_cues:
        review_checklist.append("剩余 XXX、尖括号占位符、目录字段和模板填写提示")
    return {
        "ok": True,
        "version": PROFILE_VERSION,
        "source_document": str(target),
        "source_sha256": source_hash,
        "output_document": str(output),
        "output_sha256": file_sha256(output),
        "changed_parts": changed_parts,
        "untouched_part_count": len(before_entries) - len(changed_parts),
        "audit": audit,
        "remaining_template_cues": unresolved_cues,
        "wps_review_required": True,
        "wps_review_checklist": review_checklist,
    }


def session_paths(workspace: Path) -> tuple[Path, Path]:
    root = workspace / "lab-factory"
    return root / "session-state.json", root / "audit.jsonl"


def append_audit(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def create_session(workspace: Path, subject: str, report_id: str | None = None) -> dict[str, Any]:
    state_path, audit_path = session_paths(workspace)
    if state_path.exists():
        raise V2Error(f"Session already exists: {state_path}")
    state = {
        "version": PROFILE_VERSION,
        "session_id": "s_" + uuid.uuid4().hex[:16],
        "report_id": report_id or "r_" + uuid.uuid4().hex[:12],
        "subject": subject.strip() or "未命名课程",
        "state": "materials_scanned",
        "variation_seed": secrets.token_hex(8),
        "review_id": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    write_json(state_path, state)
    append_audit(audit_path, {"at": now_iso(), "event": "session_created", "state": state["state"]})
    return {"ok": True, "state_path": str(state_path), "audit_path": str(audit_path), "session": state}


EVENTS: dict[str, tuple[set[str], str]] = {
    "confirm_requirements": ({"materials_scanned"}, "requirements_confirmed"),
    "resolve_sections": ({"requirements_confirmed"}, "sections_resolved"),
    "resolve_placements": ({"requirements_confirmed", "sections_resolved"}, "placements_resolved"),
    "mark_content_ready": ({"placements_resolved", "draft_reviewed"}, "content_ready"),
    "record_draft": ({"content_ready"}, "draft_generated"),
    "approve_draft": ({"draft_generated"}, "draft_reviewed"),
    "revise_draft": ({"draft_generated", "draft_reviewed", "finalized"}, "content_ready"),
    "finalize": ({"draft_reviewed"}, "finalized"),
    "update_skill": ({"finalized"}, "iteration_decided"),
    "finish_without_update": ({"finalized"}, "iteration_decided"),
}


def advance_session(workspace: Path, event_name: str, review_id: str | None, feedback: str | None) -> dict[str, Any]:
    state_path, audit_path = session_paths(workspace)
    state = load_json(state_path)
    transition = EVENTS.get(event_name)
    if transition is None:
        raise V2Error(f"Unknown session event: {event_name}")
    allowed, destination = transition
    if state.get("state") not in allowed:
        raise V2Error(f"Event {event_name} is not allowed from state {state.get('state')}")
    if event_name in {"approve_draft", "revise_draft", "finalize", "update_skill", "finish_without_update"}:
        if not review_id or not feedback:
            raise V2Error(f"{event_name} requires review_id and user feedback summary")
    if event_name == "record_draft":
        state["review_id"] = "review_" + uuid.uuid4().hex[:12]
    elif review_id and state.get("review_id") and review_id != state.get("review_id"):
        raise V2Error("review_id does not match the active draft review")
    previous = state["state"]
    state["state"] = destination
    state["updated_at"] = now_iso()
    write_json(state_path, state)
    append_audit(
        audit_path,
        {
            "at": now_iso(),
            "event": event_name,
            "from": previous,
            "to": destination,
            "review_id": review_id or state.get("review_id"),
            "user_feedback_summary": feedback,
        },
    )
    return {"ok": True, "state_path": str(state_path), "session": state}


PRESETS = {
    "balanced": {"level": "自然本科", "detail": "均衡", "reflection": "问题解决", "tone": "规范"},
    "concise": {"level": "基础", "detail": "精简", "reflection": "学习过程", "tone": "朴素"},
    "technical": {"level": "较成熟", "detail": "详细", "reflection": "工程实践", "tone": "技术型"},
    "personal": {"level": "自然本科", "detail": "均衡", "reflection": "批判改进", "tone": "个人化"},
}
DIMENSIONS = {
    "level": {"基础", "自然本科", "较成熟"},
    "detail": {"精简", "均衡", "详细"},
    "reflection": {"问题解决", "学习过程", "工程实践", "批判改进"},
    "tone": {"朴素", "规范", "技术型", "个人化"},
}


def create_writing_profile(subject: str, preset: str, overrides: dict[str, Any]) -> dict[str, Any]:
    if preset not in PRESETS:
        raise V2Error(f"Unknown preset: {preset}")
    dimensions = dict(PRESETS[preset])
    dimensions.update({key: value for key, value in overrides.items() if value is not None})
    for key, allowed in DIMENSIONS.items():
        if dimensions.get(key) not in allowed:
            raise V2Error(f"Invalid {key}: {dimensions.get(key)}")
    return {
        "version": PROFILE_VERSION,
        "subject": subject.strip() or "未命名课程",
        "preset": preset,
        "dimensions": dimensions,
        "derived_features": {
            "sentence_length": "由宿主模型根据 dimensions 和 style card 派生",
            "paragraph_length": "由宿主模型根据 detail 派生",
            "terminology_density": "由 level 与课程材料共同决定",
            "variation_policy": "stable_course_profile_per_report_seed",
        },
        "updated_at": now_iso(),
    }


STYLE_CARD_KEYS = {
    "section_organization", "sentence_length", "paragraph_length", "terminology_ratio",
    "analysis_order", "person_voice", "reflection_pattern", "forbidden_phrases",
}

REQUIREMENT_KEYS = {
    "experiment", "tools", "formatting", "evidence", "submission",
    "writable_regions", "protected_regions", "missing", "conflicts",
}


def validate_requirements(summary: dict[str, Any]) -> list[str]:
    errors = []
    if summary.get("version") != PROFILE_VERSION:
        errors.append("version must be 2.0")
    missing_keys = sorted(REQUIREMENT_KEYS - set(summary))
    if missing_keys:
        errors.append("missing requirement sections: " + ", ".join(missing_keys))
    for key in REQUIREMENT_KEYS:
        if key in summary and not isinstance(summary[key], (dict, list)):
            errors.append(f"{key} must be an object or array")
    if summary.get("conflicts"):
        errors.append("requirement conflicts must be resolved before confirmation")
    return errors


def validate_style_card(card: dict[str, Any]) -> list[str]:
    errors = []
    if card.get("version") != PROFILE_VERSION:
        errors.append("version must be 2.0")
    features = card.get("features")
    if not isinstance(features, dict):
        return errors + ["features must be an object"]
    missing = sorted(STYLE_CARD_KEYS - set(features))
    if missing:
        errors.append("missing style features: " + ", ".join(missing))
    if not isinstance(features.get("forbidden_phrases"), list):
        errors.append("forbidden_phrases must be an array")
    if any(key in card for key in ("sample_text", "full_text", "report_body")):
        errors.append("style card must not store sample report text")
    return errors


def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        with zipfile.ZipFile(path) as archive:
            parts = [name for story, name in story_parts(archive.namelist())]
            return "\n".join(element_text(etree.fromstring(archive.read(name))) for name in parts)
    return path.read_text(encoding="utf-8", errors="replace")


def extract_paragraph_texts(path: Path) -> list[str]:
    """Read paragraph-sized text units without returning them from privacy-safe analyzers."""
    if path.suffix.lower() == ".docx":
        paragraphs: list[str] = []
        with zipfile.ZipFile(path) as archive:
            for _, name in story_parts(archive.namelist()):
                root = etree.fromstring(archive.read(name))
                paragraphs.extend(
                    element_text(paragraph)
                    for paragraph in root.xpath(".//w:p", namespaces=NS)
                    if element_text(paragraph)
                )
        return paragraphs
    raw = path.read_text(encoding="utf-8", errors="replace")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def authored_paragraphs(path: Path) -> list[str]:
    allowed = {".docx", ".md", ".txt"}
    if path.suffix.lower() not in allowed:
        raise V2Error(f"Writing sample must be DOCX, Markdown, or text: {path.name}")
    if not path.exists() or not path.is_file():
        raise V2Error(f"Writing sample does not exist: {path}")
    result: list[str] = []
    in_code_fence = False
    for raw in extract_paragraph_texts(path):
        value = raw.strip()
        if value.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence or CODE_LINE.match(value):
            continue
        value = re.sub(r"^#{1,6}\s+", "", value)
        list_marker = bool(re.match(r"^(?:[-*+]\s+|\d+[.)、]\s*)", value))
        value = re.sub(r"^(?:[-*+]\s+|\d+[.)、]\s*)", "", value).strip()
        compact = compact_text(value)
        if not compact or len(compact) < 12:
            continue
        if TEMPLATE_OR_METADATA.match(value) or value == DISCLAIMER_TEXT:
            continue
        if re.match(r"^\d+(?:\.\d+){0,4}\s+[^。！？!?]{1,30}$", value):
            continue
        if value.count("|") >= 2 or re.fullmatch(r"[-=_*`~|\s]+", value):
            continue
        ascii_symbols = sum(1 for char in value if ord(char) < 128 and not char.isalnum() and not char.isspace())
        if ascii_symbols / max(1, len(value)) > 0.28:
            continue
        result.append(("• " if list_marker else "") + value)
    return result


def numeric_summary(values: list[int]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "mean": 0.0, "median": 0.0, "stdev": 0.0, "cv": 0.0}
    mean = statistics.fmean(values)
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    return {
        "count": len(values),
        "mean": round(mean, 3),
        "median": round(float(statistics.median(values)), 3),
        "stdev": round(stdev, 3),
        "cv": round(stdev / mean, 4) if mean else 0.0,
    }


def pattern_findings(text: str) -> list[dict[str, Any]]:
    findings = []
    for pattern_id, pattern in AI_PROSE_PATTERNS.items():
        count = len(pattern.findall(text))
        if count:
            findings.append({"id": pattern_id, "count": count})
    return findings


def first_keyword_position(paragraphs: list[str], keywords: tuple[str, ...]) -> int:
    return next(
        (index for index, paragraph in enumerate(paragraphs) if any(keyword in paragraph for keyword in keywords)),
        len(paragraphs) + 1,
    )


def style_fingerprint_from_paragraphs(paragraphs: list[str]) -> dict[str, Any]:
    plain = [re.sub(r"^•\s+", "", item) for item in paragraphs]
    text = "\n".join(plain)
    sentences = [compact_text(item) for item in sentence_units(text) if len(compact_text(item)) >= 4]
    sentence_lengths = [len(item) for item in sentences]
    paragraph_lengths = [len(compact_text(item)) for item in plain]
    connectors = re.findall(r"(?:首先|其次|再次|此外|然后|随后|因此|但是|不过|最后|综上所述)", text)
    first_person = re.findall(r"(?:我|我们|本人)", text)
    total_chars = max(1, len(compact_text(text)))
    return {
        "sentence_length": numeric_summary(sentence_lengths),
        "paragraph_length": numeric_summary(paragraph_lengths),
        "connector_rate_per_1000_chars": round(len(connectors) * 1000 / total_chars, 4),
        "first_person_rate_per_1000_chars": round(len(first_person) * 1000 / total_chars, 4),
        "list_paragraph_ratio": round(sum(item.startswith("• ") for item in paragraphs) / max(1, len(paragraphs)), 4),
    }


def analyze_writing_samples(paths: list[Path]) -> dict[str, Any]:
    if not paths or len(paths) > 3:
        raise V2Error("Provide between one and three prior writing samples")
    all_paragraphs: list[str] = []
    sample_ids: list[str] = []
    usable = 0
    for path in paths:
        resolved = path.expanduser().resolve()
        paragraphs = authored_paragraphs(resolved)
        if paragraphs:
            usable += 1
            all_paragraphs.extend(paragraphs)
        sample_ids.append("sample_" + file_sha256(resolved)[:16])
    if not all_paragraphs:
        raise V2Error("The supplied files contain too little authored prose after removing templates, metadata, and code")

    plain_paragraphs = [re.sub(r"^•\s+", "", item) for item in all_paragraphs]
    text = "\n".join(plain_paragraphs)
    compact = compact_text(text)
    sentences = [compact_text(item) for item in sentence_units(text) if len(compact_text(item)) >= 4]
    sentence_stats = numeric_summary([len(item) for item in sentences])
    paragraph_stats = numeric_summary([len(compact_text(item)) for item in plain_paragraphs])
    total_chars = len(compact)
    connector_count = len(re.findall(r"(?:首先|其次|再次|此外|然后|随后|因此|但是|不过|最后|综上所述)", text))
    first_person_count = len(re.findall(r"(?:我|我们|本人)", text))
    list_ratio = sum(item.startswith("• ") for item in all_paragraphs) / max(1, len(all_paragraphs))
    latin_terms = re.findall(r"\b[A-Za-z][A-Za-z0-9_+.#/-]{1,}\b", text)
    parenthetical_definitions = re.findall(r"[（(][^）)\n]{2,30}[）)]", text)
    term_rate = (len(latin_terms) + len(parenthetical_definitions)) * 1000 / max(1, total_chars)

    sentence_median = float(sentence_stats["median"])
    sentence_cv = float(sentence_stats["cv"])
    if sentence_median <= 24 and sentence_cv < 0.55:
        sentence_style = "short"
        sentence_rhythm = "以短句为主，句长变化较小"
    elif sentence_median >= 46 and sentence_cv < 0.65:
        sentence_style = "long"
        sentence_rhythm = "以完整的中长句为主"
    else:
        sentence_style = "mixed"
        sentence_rhythm = "短句和中长句混合"

    paragraph_median = float(paragraph_stats["median"])
    detail_level = "concise" if paragraph_median < 85 else "detailed" if paragraph_median > 210 else "balanced"
    terminology_density = "low" if term_rate < 4 else "high" if term_rate > 14 else "medium"
    connector_rate = connector_count * 1000 / max(1, total_chars)
    connector_density = "low" if connector_rate < 5 else "high" if connector_rate > 14 else "medium"
    person_rate = first_person_count * 1000 / max(1, total_chars)
    person_voice = "limited_first_person" if person_rate < 2 else "moderate_first_person" if person_rate < 8 else "frequent_first_person"
    voice_tone = "personal" if person_rate >= 4 else "technical" if terminology_density == "high" else "formal"

    order_positions = {
        "principle_first": first_keyword_position(plain_paragraphs, ("原理", "概念", "机制", "理论")),
        "procedure_first": first_keyword_position(plain_paragraphs, ("步骤", "配置", "运行", "操作", "实现")),
        "result_first": first_keyword_position(plain_paragraphs, ("结果", "输出", "现象", "验证", "得到")),
    }
    analysis_order = min(order_positions, key=order_positions.get)
    if len(set(order_positions.values())) == 1:
        analysis_order = "principle_first"

    reflection_hits = {
        "learning_process": sum(text.count(word) for word in ("理解", "掌握", "学习", "认识到")),
        "problem_solving": sum(text.count(word) for word in ("问题", "报错", "解决", "排查", "修复")),
        "engineering": sum(text.count(word) for word in ("效率", "维护", "复用", "性能", "工程")),
        "critical_improvement": sum(text.count(word) for word in ("不足", "局限", "改进", "优化", "仍然")),
    }
    reflection_depth = max(reflection_hits, key=reflection_hits.get)
    if not reflection_hits[reflection_depth]:
        reflection_depth = "problem_solving"

    confidence_score = min(0.95, 0.3 + usable * 0.15 + min(total_chars, 4000) / 10000)
    confidence_level = "low" if confidence_score < 0.6 else "medium" if confidence_score < 0.82 else "high"
    limitations = []
    if usable == 1:
        limitations.append("只有一份样本，可能混入单次课程或模板影响")
    if total_chars < 800:
        limitations.append("可分析的本人正文不足 800 字，画像按低置信度使用")
    if usable < len(paths):
        limitations.append("部分文件在去除模板、元数据和代码后没有足够正文")

    excluded = [dict(item, action="do_not_learn") for item in pattern_findings(text)]
    list_preference = "low" if list_ratio < 0.08 else "high" if list_ratio > 0.3 else "medium"
    preserve = [sentence_rhythm, f"段落详略：{detail_level}", f"分析顺序：{analysis_order}", f"人称习惯：{person_voice}"]
    return {
        "version": PERSONAL_PROFILE_VERSION,
        "kind": "personal_writing_profile",
        "sample_summary": {
            "sample_count": len(paths),
            "usable_sample_count": usable,
            "authored_char_count": total_chars,
            "sample_ids": sorted(set(sample_ids)),
        },
        "confidence": {"level": confidence_level, "score": round(confidence_score, 3), "limitations": limitations},
        "features": {
            "sentence_rhythm": sentence_rhythm,
            "sentence_length_stats": sentence_stats,
            "paragraph_pattern": f"段落长度倾向为 {detail_level}",
            "paragraph_length_stats": paragraph_stats,
            "analysis_order": analysis_order,
            "terminology_handling": f"术语密度 {terminology_density}，括号释义 {len(parenthetical_definitions)} 次",
            "person_voice": person_voice,
            "reflection_pattern": reflection_depth,
            "connector_density": connector_density,
            "list_preference": list_preference,
        },
        "recommended_preferences": {
            "writing_level": "natural_undergrad",
            "detail_level": detail_level,
            "sentence_paragraph_style": sentence_style,
            "terminology_density": terminology_density,
            "voice_tone": voice_tone,
            "analysis_order": analysis_order,
            "reflection_depth": reflection_depth,
            "variation_strength": "medium",
        },
        "humanization_preferences": {
            "preserve": preserve,
            "do_not_learn": [item["id"] for item in excluded],
            "rule": "保留稳定写作习惯，不学习模板原文、报告答案或公式化 AI 表达",
        },
        "excluded_patterns": excluded,
        "privacy": {
            "stores_report_body": False,
            "stores_source_paths": False,
            "stores_personal_identifiers": False,
            "local_analysis_only": True,
        },
    }


def humanization_audit(path: Path) -> dict[str, Any]:
    paragraphs = authored_paragraphs(path.expanduser().resolve())
    if not paragraphs:
        raise V2Error("The document contains too little authored prose for humanization audit")
    text = "\n".join(re.sub(r"^•\s+", "", item) for item in paragraphs)
    compact = compact_text(text)
    findings = pattern_findings(text)
    categories = len(findings)
    hits = sum(item["count"] for item in findings)
    density = hits * 1000 / max(1, len(compact))
    chatbot_hits = next((item["count"] for item in findings if item["id"] == "chatbot_trace"), 0)
    rewrite = chatbot_hits > 0 or (categories >= 3 and density >= 5.0)
    reported = [
        dict(item, severity="rewrite" if rewrite and item["id"] != "formulaic_connectors" else "notice")
        for item in findings
    ]
    fingerprint = style_fingerprint_from_paragraphs(paragraphs)
    return {
        "version": "1.0",
        "status": "retryable_failure" if rewrite else "pass",
        "metrics": {
            "authored_char_count": len(compact),
            "pattern_category_count": categories,
            "pattern_hit_count": hits,
            "pattern_hits_per_1000_chars": round(density, 4),
            "sentence_length_cv": fingerprint["sentence_length"]["cv"],
            "paragraph_length_cv": fingerprint["paragraph_length"]["cv"],
        },
        "pattern_findings": reported,
        "domain_exemptions": ["课程固定术语", "代码与命令", "公式", "引用", "老师模板标题", "技术方法中的必要被动表达"],
        "required_attestations": [
            "改写未添加材料中不存在的事实、经历、数据、报错或引用",
            "第一人称操作和观察均有真实材料或用户确认支持",
            "专业表达保持本科生能力边界，不伪装教师或行业专家",
        ],
        "detector_policy": "ai_detector_scores_are_not_quality_gates",
    }


def sentence_units(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[。！？!?；;])|\n+", text) if item.strip()]


def ngrams(value: str, size: int = 5) -> set[str]:
    return {value[index : index + size] for index in range(max(0, len(value) - size + 1))}


def similarity_check(generated: Path, references: list[Path], whitelist: list[str]) -> dict[str, Any]:
    generated_raw = extract_text(generated)
    for phrase in whitelist:
        generated_raw = generated_raw.replace(phrase, "")
    generated_compact = compact_text(generated_raw)
    generated_sentences = [compact_text(item) for item in sentence_units(generated_raw)]
    findings = []
    for reference in references:
        reference_raw = extract_text(reference)
        for phrase in whitelist:
            reference_raw = reference_raw.replace(phrase, "")
        reference_compact = compact_text(reference_raw)
        longest = difflib.SequenceMatcher(None, generated_compact, reference_compact, autojunk=False).find_longest_match()
        long_match = generated_compact[longest.a : longest.a + longest.size]
        sentence_matches = []
        reference_sentences = [compact_text(item) for item in sentence_units(reference_raw)]
        for sentence in generated_sentences:
            if len(sentence) < 30:
                continue
            best = max((ratio(sentence, other) for other in reference_sentences if len(other) >= 30), default=0.0)
            if best >= 0.88:
                sentence_matches.append({"text": sentence[:120], "similarity": round(best, 4)})
        left = ngrams(generated_compact)
        right = ngrams(reference_compact)
        overlap = len(left & right) / max(1, len(left))
        blocked = longest.size >= 40 or len(sentence_matches) >= 2 or overlap > 0.25
        findings.append(
            {
                "reference": str(reference),
                "blocked": blocked,
                "longest_common_length": longest.size,
                "longest_common_excerpt": long_match[:160] if longest.size >= 20 else "",
                "similar_sentence_count": len(sentence_matches),
                "similar_sentences": sentence_matches[:10],
                "generated_5gram_overlap": round(overlap, 4),
            }
        )
    blocked_findings = [item for item in findings if item["blocked"]]
    return {
        "ok": not blocked_findings,
        "gate": "pass" if not blocked_findings else "blocked",
        "thresholds": {"continuous_chars": 40, "sentence_similarity": 0.88, "sentence_hits": 2, "5gram_overlap": 0.25},
        "findings": findings,
        "rewrite_required": bool(blocked_findings),
    }


def style_fingerprint_distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    pairs = [
        (float(left["sentence_length"]["mean"]), float(right["sentence_length"]["mean"]), 45.0),
        (float(left["sentence_length"]["cv"]), float(right["sentence_length"]["cv"]), 1.0),
        (float(left["paragraph_length"]["mean"]), float(right["paragraph_length"]["mean"]), 220.0),
        (float(left["connector_rate_per_1000_chars"]), float(right["connector_rate_per_1000_chars"]), 20.0),
        (float(left["first_person_rate_per_1000_chars"]), float(right["first_person_rate_per_1000_chars"]), 15.0),
        (float(left["list_paragraph_ratio"]), float(right["list_paragraph_ratio"]), 0.6),
    ]
    distances = [min(1.0, abs(a - b) / scale) for a, b, scale in pairs]
    return round(statistics.fmean(distances), 4)


NUMBERED_EVIDENCE_PLACEHOLDER = re.compile(
    r"【\s*(图|表)\s*(\d+(?:[-－—.]\d+)*)\s*[：:]\s*([^】；;]+)(?:[；;][^】]*)?】"
)
GENERIC_EVIDENCE_PLACEHOLDER = re.compile(r"【\s*(?:截图|绘图|图片|图表|表格|图|表)[^】]*】")
FIGURE_OR_TABLE_REFERENCE = re.compile(r"(?:如|见|参见|详见)?\s*(图|表)\s*(\d+(?:[-－—.]\d+)*)")


def normalized_evidence_id(kind: str, value: str) -> str:
    return kind + value.replace("－", "-").replace("—", "-").replace(".", "-")


def structure_fingerprint(path: Path) -> dict[str, Any]:
    authored = authored_paragraphs(path)
    flow: list[str] = []
    counts = {
        "prose_short": 0,
        "prose_medium": 0,
        "prose_long": 0,
        "list_item": 0,
        "problem_solution": 0,
        "numbered_figure": 0,
        "numbered_table": 0,
        "unnumbered_evidence": 0,
    }
    for raw in authored:
        value = re.sub(r"^•\s+", "", raw).strip()
        numbered = list(NUMBERED_EVIDENCE_PLACEHOLDER.finditer(value))
        generic = list(GENERIC_EVIDENCE_PLACEHOLDER.finditer(value))
        if numbered:
            for match in numbered:
                category = "numbered_figure" if match.group(1) == "图" else "numbered_table"
                counts[category] += 1
                flow.append(category)
            value = NUMBERED_EVIDENCE_PLACEHOLDER.sub("", value).strip()
        elif generic:
            counts["unnumbered_evidence"] += len(generic)
            flow.extend(["unnumbered_evidence"] * len(generic))
            value = GENERIC_EVIDENCE_PLACEHOLDER.sub("", value).strip()
        if not value:
            continue
        if re.match(r"^问题\s*\d+\s*[：:]", value):
            category = "problem_solution"
        elif raw.startswith("• "):
            category = "list_item"
        else:
            length = len(compact_text(value))
            category = "prose_short" if length < 90 else "prose_long" if length >= 210 else "prose_medium"
        counts[category] += 1
        flow.append(category)

    problem_count = counts["problem_solution"]
    list_count = counts["list_item"]
    if problem_count == 3 and list_count >= 6:
        summary_shape = "fixed_three_three_three"
    elif problem_count:
        summary_shape = "paired_problem_solution"
    elif list_count:
        summary_shape = "list_or_takeaways"
    else:
        summary_shape = "narrative"
    return {
        "eligible": path.suffix.lower() == ".docx" and len(flow) >= 8,
        "block_count": len(flow),
        "flow_signature": flow,
        "counts": counts,
        "summary_shape": summary_shape,
    }


def structure_fingerprint_similarity(left: dict[str, Any], right: dict[str, Any]) -> tuple[float, float]:
    flow_similarity = difflib.SequenceMatcher(
        None, left.get("flow_signature", []), right.get("flow_signature", []), autojunk=False
    ).ratio()
    keys = set(left.get("counts", {})) | set(right.get("counts", {}))
    count_distances = []
    for key in keys:
        a = int(left.get("counts", {}).get(key, 0))
        b = int(right.get("counts", {}).get(key, 0))
        count_distances.append(abs(a - b) / max(1, a, b))
    count_similarity = 1.0 - statistics.fmean(count_distances) if count_distances else 1.0
    return round(flow_similarity, 4), round(count_similarity, 4)


def document_structure_audit(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    paragraphs = extract_paragraph_texts(resolved)
    full_text = "\n".join(paragraphs)
    numbered = list(NUMBERED_EVIDENCE_PLACEHOLDER.finditer(full_text))
    generic = list(GENERIC_EVIDENCE_PLACEHOLDER.finditer(full_text))
    entries = [
        {
            "kind": match.group(1),
            "id": normalized_evidence_id(match.group(1), match.group(2)),
            "title": match.group(3).strip(),
        }
        for match in numbered
    ]
    ids = [item["id"] for item in entries]
    duplicate_ids = sorted({item for item in ids if ids.count(item) > 1})
    prose_without_placeholders = GENERIC_EVIDENCE_PLACEHOLDER.sub("", full_text)
    referenced_ids = {
        normalized_evidence_id(match.group(1), match.group(2))
        for match in FIGURE_OR_TABLE_REFERENCE.finditer(prose_without_placeholders)
    }
    missing_cross_references = sorted(set(ids) - referenced_ids)
    unnumbered_placeholders = [
        match.group(0)[:160]
        for match in generic
        if not NUMBERED_EVIDENCE_PLACEHOLDER.fullmatch(match.group(0))
    ]
    multi_asset_placeholders = []
    for match in generic:
        value = match.group(0)
        asset_mentions = len(re.findall(r"(?:类图|活动图|状态图|时序图|流程图|截图|表格)", value))
        if asset_mentions > 1 or (asset_mentions and re.search(r"[、,，]|以及|和", value)):
            multi_asset_placeholders.append(value[:160])

    table_keywords = (
        "字段", "数据表", "核心表", "类名", "职责", "输入", "输出", "异常处理", "测试用例",
        "配置项", "对比", "主键", "外键", "属性", "方法", "状态", "关系",
    )
    table_scope_end_candidates = [
        position for marker in ("实验小结", "问题和解决办法")
        if (position := full_text.find(marker)) > 0
    ]
    table_scope = full_text[:min(table_scope_end_candidates)] if table_scope_end_candidates else full_text
    matched_table_keywords = {keyword for keyword in table_keywords if keyword in table_scope}
    has_numbered_table = any(item["kind"] == "表" for item in entries)
    explicit_table_signal = any(keyword in matched_table_keywords for keyword in ("字段", "数据表", "核心表", "测试用例"))
    table_required_by_content = (
        (explicit_table_signal and len(matched_table_keywords) >= 2)
        or len(matched_table_keywords) >= 4
    )
    table_decision_recorded = has_numbered_table or not table_required_by_content

    summary_start = full_text.find("问题和解决办法")
    summary_text = full_text[summary_start:] if summary_start >= 0 else ""
    if summary_text:
        summary_end_candidates = [
            position for marker in ("考核结果", "教师评语", DISCLAIMER_TEXT)
            if (position := summary_text.find(marker)) > 0
        ]
        if summary_end_candidates:
            summary_text = summary_text[:min(summary_end_candidates)]
    problem_evidence_needed = any(
        keyword in summary_text for keyword in ("报错", "错误提示", "异常界面", "运行结果", "配置界面", "前后对比")
    )
    problem_has_numbered_figure = any(
        match.group(1) == "图" for match in NUMBERED_EVIDENCE_PLACEHOLDER.finditer(summary_text)
    )
    problem_evidence_decision_recorded = problem_has_numbered_figure or not problem_evidence_needed

    unresolved_template_cues = sorted({
        value[:160]
        for value in paragraphs
        if re.search(r"(?:\d+(?:\.\d+)+\s+[^\n]{0,30}XXX|XXX\s*功能|<[^>]{1,80}>)", value)
    })
    evidence_expected = bool(generic) or any(
        keyword in full_text for keyword in ("需要截图", "补充截图", "绘制", "图中", "如图", "见图", "可视化图", "波形图", "拓扑图")
    )
    caption_cross_reference_ok = (
        (bool(entries) or not evidence_expected)
        and not duplicate_ids
        and not missing_cross_references
        and not unnumbered_placeholders
    )
    single_asset_ok = not multi_asset_placeholders
    fingerprint = structure_fingerprint(resolved)
    failures = []
    if evidence_expected and not entries:
        failures.append("没有预先编号并命名的图表占位")
    if duplicate_ids:
        failures.append("图表编号重复")
    if missing_cross_references:
        failures.append("正文缺少图表编号交叉引用")
    if unnumbered_placeholders:
        failures.append("仍有未编号或未命名的图表占位")
    if multi_asset_placeholders:
        failures.append("一个占位包含多个图表")
    if not table_decision_recorded:
        failures.append("存在适合行列表达的内容，但没有编号表格或表格占位")
    if not problem_evidence_decision_recorded:
        failures.append("问题/解决办法需要直观证据，但没有编号图片占位")
    if unresolved_template_cues:
        failures.append("仍有正文或目录结构占位提示")
    return {
        "version": "1.0",
        "status": "pass" if not failures else "retryable_failure",
        "caption_cross_reference_ok": caption_cross_reference_ok,
        "single_asset_per_placeholder_ok": single_asset_ok,
        "table_decision_recorded": table_decision_recorded,
        "problem_evidence_decision_recorded": problem_evidence_decision_recorded,
        "unresolved_template_cues": unresolved_template_cues,
        "structure_fingerprint": fingerprint,
        "evidence_counts": {
            "numbered_figures": sum(item["kind"] == "图" for item in entries),
            "numbered_tables": sum(item["kind"] == "表" for item in entries),
            "unnumbered_placeholders": len(unnumbered_placeholders),
        },
        "missing_cross_references": missing_cross_references,
        "duplicate_ids": duplicate_ids,
        "multi_asset_placeholders": multi_asset_placeholders,
        "table_required_by_content": table_required_by_content,
        "problem_evidence_needed": problem_evidence_needed,
        "failures": failures,
    }


def cohort_similarity_check(generated: Path, comparisons: list[Path], whitelist: list[str]) -> dict[str, Any]:
    generated_raw = extract_text(generated)
    for phrase in whitelist:
        generated_raw = generated_raw.replace(phrase, "")
    generated_compact = compact_text(generated_raw)
    generated_sentences = [compact_text(item) for item in sentence_units(generated_raw)]
    generated_fingerprint = style_fingerprint_from_paragraphs(authored_paragraphs(generated))
    generated_structure = structure_fingerprint(generated)
    findings = []
    for comparison in comparisons:
        comparison_raw = extract_text(comparison)
        for phrase in whitelist:
            comparison_raw = comparison_raw.replace(phrase, "")
        comparison_compact = compact_text(comparison_raw)
        longest = difflib.SequenceMatcher(None, generated_compact, comparison_compact, autojunk=False).find_longest_match()
        comparison_sentences = [compact_text(item) for item in sentence_units(comparison_raw)]
        sentence_hits = 0
        for sentence in generated_sentences:
            if len(sentence) < 30:
                continue
            best = max((ratio(sentence, other) for other in comparison_sentences if len(other) >= 30), default=0.0)
            sentence_hits += int(best >= 0.88)
        generated_grams = ngrams(generated_compact)
        comparison_grams = ngrams(comparison_compact)
        overlap = len(generated_grams & comparison_grams) / max(1, len(generated_grams))
        comparison_fingerprint = style_fingerprint_from_paragraphs(authored_paragraphs(comparison))
        style_distance = style_fingerprint_distance(generated_fingerprint, comparison_fingerprint)
        comparison_structure = structure_fingerprint(comparison)
        flow_similarity, count_similarity = structure_fingerprint_similarity(generated_structure, comparison_structure)
        structural_collision = (
            generated_structure["eligible"]
            and comparison_structure["eligible"]
            and flow_similarity >= 0.90
            and count_similarity >= 0.90
        )
        blocked = longest.size >= 40 or sentence_hits >= 2 or overlap > 0.25 or structural_collision
        findings.append({
            "comparison_id": "report_" + file_sha256(comparison)[:16],
            "blocked": blocked,
            "longest_common_length": longest.size,
            "similar_sentence_count": sentence_hits,
            "generated_5gram_overlap": round(overlap, 4),
            "style_fingerprint_distance": style_distance,
            "style_distance_notice": style_distance < 0.12,
            "structure_flow_similarity": flow_similarity,
            "structure_count_similarity": count_similarity,
            "structural_collision": structural_collision,
        })
    blocked_findings = [item for item in findings if item["blocked"]]
    return {
        "version": "1.0",
        "ok": not blocked_findings,
        "gate": "pass" if not blocked_findings else "blocked",
        "mode": "cross_report_collision",
        "coverage": {
            "status": "evaluated" if comparisons else "baseline_unavailable",
            "comparison_count": len(comparisons),
            "claim_boundary": (
                "collision_checked_against_available_baseline"
                if comparisons else "no_baseline_so_cross_report_difference_not_proven"
            ),
        },
        "thresholds": {
            "continuous_chars": 40,
            "sentence_similarity": 0.88,
            "sentence_hits": 2,
            "5gram_overlap": 0.25,
            "style_distance_notice_below": 0.12,
            "structure_flow_similarity": 0.90,
            "structure_count_similarity": 0.90,
        },
        "findings": findings,
        "style_fingerprint": generated_fingerprint,
        "structure_fingerprint": generated_structure,
        "privacy": {"stores_comparison_body": False, "stores_comparison_paths": False},
    }


def migrate_v1(fill_map: dict[str, Any]) -> dict[str, Any]:
    fields = []
    for index, item in enumerate(fill_map.get("items", [])):
        if not isinstance(item, dict):
            continue
        raw_id = re.sub(r"[^a-z0-9_-]+", "-", str(item.get("id", f"field-{index}")).lower()).strip("-")
        if not raw_id or not raw_id[0].isalpha():
            raw_id = f"field-{index}-{raw_id}".strip("-")
        operation_map = {"fill_table_cell": "fill_cell"}
        fields.append(
            {
                "id": raw_id[:64],
                "legacy_anchor": item.get("target_anchor"),
                "legacy_operation": item.get("operation"),
                "proposed_operation": operation_map.get(item.get("operation"), item.get("operation", "insert_after")),
                "requires_relocation": True,
                "requires_user_confirmation": True,
            }
        )
    return {
        "version": PROFILE_VERSION,
        "migration_source": "fill-map-v1",
        "target_document": fill_map.get("target_document"),
        "fields": fields,
        "status": "draft_requires_inventory_and_relocation",
        "warning": "Legacy string anchors are never treated as high-confidence v2 placements.",
    }


FORBIDDEN_SKILL_CONTENT = re.compile(
    r'("(?:name|student_id|password|token|sample_text|full_text|report_body)"\s*:)|(?:姓名|学号|账号|密码)"?\s*[:：]|data:image|base64,',
    re.I,
)


def allowed_skill_update_path(relative: Path) -> bool:
    if relative.is_absolute() or ".." in relative.parts:
        return False
    value = relative.as_posix()
    if value in {
        "references/course-rules.json",
        "references/writing-profile.json",
        "references/iteration-log.md",
    }:
        return True
    return bool(
        re.fullmatch(r"references/(?:style-cards|template-profiles)/[a-zA-Z0-9._-]+\.json", value)
    )


def propose_skill_update(skill_dir: Path, updates: list[dict[str, Any]]) -> dict[str, Any]:
    if not (skill_dir / "SKILL.md").exists():
        raise V2Error(f"Not a skill directory: {skill_dir}")
    prepared = []
    for index, update in enumerate(updates):
        if not isinstance(update, dict):
            raise V2Error(f"updates[{index}] must be an object")
        relative = Path(str(update.get("path", "")))
        if not allowed_skill_update_path(relative):
            raise V2Error(f"Skill update path is not allowed: {relative}")
        if update.get("reusable") is not True or update.get("scope") not in {"course", "template"}:
            raise V2Error(f"{relative}: update must be reusable and course/template scoped")
        content = update.get("content")
        if not isinstance(content, str) or not content.strip():
            raise V2Error(f"{relative}: content must be a non-empty string")
        if len(content.encode("utf-8")) > 200_000:
            raise V2Error(f"{relative}: content is too large for stable Skill knowledge")
        if FORBIDDEN_SKILL_CONTENT.search(content):
            raise V2Error(f"{relative}: content appears to contain private data or report/sample body")
        target = (skill_dir / relative).resolve()
        if skill_dir.resolve() not in target.parents:
            raise V2Error(f"Skill update escapes skill directory: {relative}")
        before = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True), content.splitlines(keepends=True),
                fromfile=f"a/{relative.as_posix()}", tofile=f"b/{relative.as_posix()}",
            )
        )
        prepared.append(
            {
                "path": relative.as_posix(),
                "reason": str(update.get("reason", "稳定课程规则更新")),
                "scope": update["scope"],
                "reusable": True,
                "before_sha256": sha256(before.encode("utf-8")),
                "after_sha256": sha256(content.encode("utf-8")),
                "content": content,
                "diff": diff,
            }
        )
    return {
        "version": PROFILE_VERSION,
        "update_id": "su_" + uuid.uuid4().hex[:16],
        "skill_dir": str(skill_dir.resolve()),
        "created_at": now_iso(),
        "status": "pending_user_confirmation",
        "updates": prepared,
        "excluded_content": ["个人信息", "参考样本正文", "本次报告正文", "一次性模板异常"],
    }


def apply_skill_update(proposal: dict[str, Any]) -> dict[str, Any]:
    if proposal.get("version") != PROFILE_VERSION or proposal.get("status") != "pending_user_confirmation":
        raise V2Error("Skill update proposal is invalid or already applied")
    skill_dir = Path(str(proposal.get("skill_dir", ""))).resolve()
    if not (skill_dir / "SKILL.md").exists():
        raise V2Error(f"Skill directory no longer exists: {skill_dir}")
    prepared = []
    for update in proposal.get("updates", []):
        relative = Path(update["path"])
        if not allowed_skill_update_path(relative):
            raise V2Error(f"Skill update path is no longer allowed: {relative}")
        target = (skill_dir / relative).resolve()
        current = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        if sha256(current.encode("utf-8")) != update.get("before_sha256"):
            raise V2Error(f"Skill file changed after diff review: {relative}")
        prepared.append((update, target, current, target.exists()))

    temporary_files: list[tuple[dict[str, Any], Path, Path, str, bool]] = []
    applied_targets: list[tuple[Path, str, bool]] = []
    try:
        for update, target, current, existed in prepared:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            temporary.write_text(update["content"], encoding="utf-8")
            temporary_files.append((update, target, temporary, current, existed))
        for update, target, temporary, current, existed in temporary_files:
            os.replace(temporary, target)
            applied_targets.append((target, current, existed))
    except Exception:
        for target, current, existed in reversed(applied_targets):
            if existed:
                rollback = target.with_name(f".{target.name}.{uuid.uuid4().hex}.rollback")
                rollback.write_text(current, encoding="utf-8")
                os.replace(rollback, target)
            elif target.exists():
                target.unlink()
        raise
    finally:
        for _, _, temporary, _, _ in temporary_files:
            if temporary.exists():
                temporary.unlink()

    applied = []
    for update, target, _, _ in prepared:
        applied.append({"path": update["path"], "sha256": update["after_sha256"]})
    return {"ok": True, "update_id": proposal.get("update_id"), "skill_dir": str(skill_dir), "applied": applied}


def print_result(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Lab Factory v2 deterministic engine")
    sub = parser.add_subparsers(dest="command", required=True)

    inventory_parser = sub.add_parser("inventory")
    inventory_parser.add_argument("docx")
    inventory_parser.add_argument("--output")

    profile_parser = sub.add_parser("create-profile")
    profile_parser.add_argument("inventory")
    profile_parser.add_argument("--fields-json", required=True)
    profile_parser.add_argument("--subject", required=True)
    profile_parser.add_argument("--output", required=True)

    validate_profile_parser = sub.add_parser("validate-profile")
    validate_profile_parser.add_argument("profile")

    propose_parser = sub.add_parser("propose")
    propose_parser.add_argument("profile")
    propose_parser.add_argument("docx")
    propose_parser.add_argument("--output")

    confirm_parser = sub.add_parser("confirm-profile")
    confirm_parser.add_argument("profile")
    confirm_parser.add_argument("docx")
    confirm_parser.add_argument("placement_plan")
    confirm_parser.add_argument("--selections-json", required=True)
    confirm_parser.add_argument("--summary", required=True)
    confirm_parser.add_argument("--output", required=True)

    section_plan_parser = sub.add_parser("create-section-plan")
    section_plan_parser.add_argument("inventory")
    section_plan_parser.add_argument("--proposal-json", required=True)
    section_plan_parser.add_argument("--output", required=True)

    apply_sections_parser = sub.add_parser("apply-section-plan")
    apply_sections_parser.add_argument("plan")
    apply_sections_parser.add_argument("docx")
    apply_sections_parser.add_argument("--confirmation", required=True)
    apply_sections_parser.add_argument("--output", required=True)
    apply_sections_parser.add_argument("--overwrite", action="store_true")

    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("profile")
    apply_parser.add_argument("docx")
    apply_parser.add_argument("content")
    apply_parser.add_argument("--output", required=True)
    apply_parser.add_argument("--overwrite", action="store_true")

    disclaimer_parser = sub.add_parser("ensure-disclaimer")
    disclaimer_parser.add_argument("docx")

    create_session_parser = sub.add_parser("create-session")
    create_session_parser.add_argument("workspace")
    create_session_parser.add_argument("--subject", required=True)
    create_session_parser.add_argument("--report-id")

    session_status_parser = sub.add_parser("session-status")
    session_status_parser.add_argument("workspace")

    advance_parser = sub.add_parser("advance-session")
    advance_parser.add_argument("workspace")
    advance_parser.add_argument("--event", required=True, choices=sorted(EVENTS))
    advance_parser.add_argument("--review-id")
    advance_parser.add_argument("--feedback")

    writing_parser = sub.add_parser("create-writing-profile")
    writing_parser.add_argument("--subject", required=True)
    writing_parser.add_argument("--preset", choices=sorted(PRESETS), default="balanced")
    writing_parser.add_argument("--overrides-json", default="{}")
    writing_parser.add_argument("--output", required=True)

    sample_profile_parser = sub.add_parser("analyze-writing-samples")
    sample_profile_parser.add_argument("samples", nargs="+")
    sample_profile_parser.add_argument("--output", required=True)

    style_parser = sub.add_parser("validate-style-card")
    style_parser.add_argument("style_card")

    requirements_parser = sub.add_parser("validate-requirements")
    requirements_parser.add_argument("summary")

    similarity_parser = sub.add_parser("similarity")
    similarity_parser.add_argument("generated")
    similarity_parser.add_argument("references", nargs="+")
    similarity_parser.add_argument("--whitelist-json", default="[]")

    cohort_parser = sub.add_parser("cohort-similarity")
    cohort_parser.add_argument("generated")
    cohort_parser.add_argument("comparisons", nargs="*")
    cohort_parser.add_argument("--whitelist-json", default="[]")

    humanization_parser = sub.add_parser("humanization-audit")
    humanization_parser.add_argument("document")
    humanization_parser.add_argument("--output")

    structure_parser = sub.add_parser("document-structure-audit")
    structure_parser.add_argument("document")
    structure_parser.add_argument("--output")

    migrate_parser = sub.add_parser("migrate-v1")
    migrate_parser.add_argument("fill_map")
    migrate_parser.add_argument("--output", required=True)

    propose_update_parser = sub.add_parser("propose-skill-update")
    propose_update_parser.add_argument("skill_dir")
    propose_update_parser.add_argument("--updates-json", required=True)
    propose_update_parser.add_argument("--output", required=True)

    apply_update_parser = sub.add_parser("apply-skill-update")
    apply_update_parser.add_argument("proposal")

    args = parser.parse_args()
    try:
        if args.command == "inventory":
            result = inventory_docx(Path(args.docx).expanduser().resolve())
            if args.output:
                write_json(Path(args.output).expanduser().resolve(), result)
                result["inventory_path"] = str(Path(args.output).expanduser().resolve())
        elif args.command == "create-profile":
            fields = json.loads(args.fields_json)
            if not isinstance(fields, list):
                raise V2Error("fields-json must be an array")
            result = create_template_profile(load_json(Path(args.inventory)), fields, args.subject)
            write_json(Path(args.output).expanduser().resolve(), result)
            result = {"ok": True, "profile_path": str(Path(args.output).expanduser().resolve()), "profile": result}
        elif args.command == "validate-profile":
            errors = validate_template_profile(load_json(Path(args.profile)))
            result = {"ok": not errors, "errors": errors}
        elif args.command == "propose":
            result = propose_placements(load_json(Path(args.profile)), inventory_docx(Path(args.docx).resolve()))
            if args.output:
                write_json(Path(args.output).expanduser().resolve(), result)
                result["placement_plan_path"] = str(Path(args.output).expanduser().resolve())
        elif args.command == "confirm-profile":
            selections = json.loads(args.selections_json)
            if not isinstance(selections, list):
                raise V2Error("selections-json must be an array")
            updated = confirmed_profile(
                load_json(Path(args.profile)), inventory_docx(Path(args.docx).resolve()),
                load_json(Path(args.placement_plan)), selections, args.summary,
            )
            write_json(Path(args.output).resolve(), updated)
            result = {"ok": True, "profile_path": str(Path(args.output).resolve()), "profile": updated}
        elif args.command == "create-section-plan":
            proposal = json.loads(args.proposal_json)
            if not isinstance(proposal, dict):
                raise V2Error("proposal-json must be an object")
            section_plan = create_section_plan(load_json(Path(args.inventory)), proposal)
            write_json(Path(args.output).expanduser().resolve(), section_plan)
            result = {
                "ok": True,
                "section_plan_path": str(Path(args.output).expanduser().resolve()),
                "section_plan": section_plan,
            }
        elif args.command == "apply-section-plan":
            result = apply_section_plan(
                load_json(Path(args.plan)), Path(args.docx).expanduser().resolve(),
                Path(args.output).expanduser().resolve(), args.confirmation, args.overwrite,
            )
        elif args.command == "apply":
            result = apply_v2(
                load_json(Path(args.profile)), Path(args.docx).resolve(), load_json(Path(args.content)),
                Path(args.output).resolve(), args.overwrite,
            )
        elif args.command == "ensure-disclaimer":
            result = ensure_docx_disclaimer(Path(args.docx).expanduser().resolve())
        elif args.command == "create-session":
            result = create_session(Path(args.workspace).resolve(), args.subject, args.report_id)
        elif args.command == "session-status":
            state_path, audit_path = session_paths(Path(args.workspace).resolve())
            result = {"ok": True, "state_path": str(state_path), "audit_path": str(audit_path), "session": load_json(state_path)}
        elif args.command == "advance-session":
            result = advance_session(Path(args.workspace).resolve(), args.event, args.review_id, args.feedback)
        elif args.command == "create-writing-profile":
            result = create_writing_profile(args.subject, args.preset, json.loads(args.overrides_json))
            write_json(Path(args.output).resolve(), result)
            result = {"ok": True, "writing_profile_path": str(Path(args.output).resolve()), "profile": result}
        elif args.command == "analyze-writing-samples":
            profile = analyze_writing_samples([Path(item) for item in args.samples])
            output = Path(args.output).expanduser().resolve()
            write_json(output, profile)
            result = {"ok": True, "personal_writing_profile_path": str(output), "profile": profile}
        elif args.command == "validate-style-card":
            errors = validate_style_card(load_json(Path(args.style_card)))
            result = {"ok": not errors, "errors": errors}
        elif args.command == "validate-requirements":
            errors = validate_requirements(load_json(Path(args.summary)))
            result = {"ok": not errors, "errors": errors}
        elif args.command == "similarity":
            whitelist = json.loads(args.whitelist_json)
            if not isinstance(whitelist, list) or not all(isinstance(item, str) for item in whitelist):
                raise V2Error("whitelist-json must be an array of strings")
            result = similarity_check(Path(args.generated).resolve(), [Path(item).resolve() for item in args.references], whitelist)
        elif args.command == "cohort-similarity":
            whitelist = json.loads(args.whitelist_json)
            if not isinstance(whitelist, list) or not all(isinstance(item, str) for item in whitelist):
                raise V2Error("whitelist-json must be an array of strings")
            result = cohort_similarity_check(
                Path(args.generated).resolve(), [Path(item).resolve() for item in args.comparisons], whitelist
            )
        elif args.command == "humanization-audit":
            result = humanization_audit(Path(args.document).resolve())
            if args.output:
                output = Path(args.output).expanduser().resolve()
                write_json(output, result)
                result["audit_path"] = str(output)
        elif args.command == "document-structure-audit":
            result = document_structure_audit(Path(args.document).resolve())
            if args.output:
                output = Path(args.output).expanduser().resolve()
                write_json(output, result)
                result["audit_path"] = str(output)
        elif args.command == "migrate-v1":
            migration = migrate_v1(load_json(Path(args.fill_map)))
            write_json(Path(args.output).resolve(), migration)
            result = {"ok": True, "migration_path": str(Path(args.output).resolve()), "migration": migration}
        elif args.command == "propose-skill-update":
            updates = json.loads(args.updates_json)
            if not isinstance(updates, list) or not updates:
                raise V2Error("updates-json must be a non-empty array")
            proposal = propose_skill_update(Path(args.skill_dir).resolve(), updates)
            write_json(Path(args.output).resolve(), proposal)
            result = {"ok": True, "proposal_path": str(Path(args.output).resolve()), "proposal": proposal}
        elif args.command == "apply-skill-update":
            result = apply_skill_update(load_json(Path(args.proposal)))
        else:
            raise V2Error(f"Unknown command: {args.command}")
        print_result(result)
        return 0 if result.get("ok", True) else 1
    except (V2Error, OSError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print_result({"ok": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
