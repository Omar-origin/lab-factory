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
}
W = f"{{{NS['w']}}}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
PROFILE_VERSION = "2.0"
AUTO_THRESHOLD = 0.90
CONFIRM_THRESHOLD = 0.65
AUTO_MARGIN = 0.15
STATES = [
    "materials_scanned",
    "requirements_confirmed",
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


def inventory_docx(path: Path) -> dict[str, Any]:
    if not path.exists() or path.suffix.lower() != ".docx":
        raise V2Error(f"DOCX does not exist or has wrong extension: {path}")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        nodes: list[dict[str, Any]] = []
        parts: dict[str, str] = {}
        story_counts: dict[str, int] = {}
        image_relationships = 0
        for story, part_name in story_parts(names):
            raw = archive.read(part_name)
            parts[part_name] = sha256(raw)
            root = etree.fromstring(raw)
            tree = root.getroottree()
            paragraphs = root.xpath(".//w:p", namespaces=NS)
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
    return {
        "ok": True,
        "version": PROFILE_VERSION,
        "document": str(path.resolve()),
        "document_sha256": file_sha256(path),
        "family_fingerprint": family_fingerprint,
        "content_fingerprint": sha256("\n".join(label_tokens).encode("utf-8")),
        "node_count": len(nodes),
        "story_counts": story_counts,
        "image_relationships": image_relationships,
        "nodes": nodes,
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
    family_match = profile.get("family_fingerprint") == inventory.get("family_fingerprint")
    proposals = []
    for field in profile["fields"]:
        scored = []
        for node in inventory.get("nodes", []):
            score, features = score_candidate(field["locator"], node)
            if not family_match:
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
        "family_fingerprint_match": family_match,
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
    updated["source_document_sha256"] = inventory.get("document_sha256")
    updated.setdefault("drift_history", []).append(
        {
            "at": now_iso(),
            "document_sha256": inventory.get("document_sha256"),
            "family_fingerprint": inventory.get("family_fingerprint"),
            "changed_fields": changed_fields,
            "user_confirmation_summary": summary,
        }
    )
    return updated


def paragraph_with_text(source: etree._Element, text: str) -> etree._Element:
    paragraph = copy.deepcopy(source)
    ppr = paragraph.find(f"{W}pPr")
    reference_rpr = paragraph.find(f".//{W}rPr")
    for child in list(paragraph):
        if child is not ppr:
            paragraph.remove(child)
    run = etree.SubElement(paragraph, f"{W}r")
    if reference_rpr is not None:
        run.append(copy.deepcopy(reference_rpr))
    text_node = etree.SubElement(run, f"{W}t")
    if text.startswith(" ") or text.endswith(" "):
        text_node.set(XML_SPACE, "preserve")
    text_node.text = text
    return paragraph


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
    for node, _, _ in touched[1:]:
        node.text = ""
    return True


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
                    for change in part_changes[info.filename]:
                        matches = root.xpath(change["node"]["path"], namespaces=NS)
                        if len(matches) != 1:
                            raise V2Error(
                                f"{change['field']['id']}: structural path resolved to {len(matches)} nodes"
                            )
                        paragraph = matches[0]
                        operation = change["field"]["operation"]
                        content_lines = [line for line in change["content"].splitlines() if line.strip()] or [change["content"]]
                        if operation == "insert_after":
                            current = paragraph
                            for line in content_lines:
                                new_paragraph = paragraph_with_text(paragraph, line)
                                current.addnext(new_paragraph)
                                current = new_paragraph
                        elif operation == "replace_placeholder":
                            anchor = change["field"]["locator"].get("text") or ""
                            if not anchor or not replace_placeholder(paragraph, anchor, change["content"]):
                                raise V2Error(f"{change['field']['id']}: placeholder no longer matches")
                        elif operation == "fill_cell":
                            if change["node"]["container"] != "table_cell":
                                raise V2Error(f"{change['field']['id']}: fill_cell target is outside a table")
                            replacement = paragraph_with_text(paragraph, change["content"])
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
        after_entries = zip_entry_hashes(temporary)
        changed_parts = sorted(name for name in before_entries if before_entries[name] != after_entries.get(name))
        expected_parts = sorted(part_changes)
        unexpected = sorted(set(changed_parts) - set(expected_parts))
        if unexpected:
            raise V2Error(f"Unexpected DOCX package parts changed: {unexpected}")
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "ok": True,
        "version": PROFILE_VERSION,
        "source_document": str(target),
        "source_sha256": source_hash,
        "output_document": str(output),
        "output_sha256": file_sha256(output),
        "changed_parts": sorted(part_changes),
        "untouched_part_count": len(before_entries) - len(part_changes),
        "audit": audit,
        "wps_review_required": True,
        "wps_review_checklist": ["写入位置", "表格边框与合并单元格", "分页与行距", "图片和公式位置"],
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
    "resolve_placements": ({"requirements_confirmed"}, "placements_resolved"),
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

    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("profile")
    apply_parser.add_argument("docx")
    apply_parser.add_argument("content")
    apply_parser.add_argument("--output", required=True)
    apply_parser.add_argument("--overwrite", action="store_true")

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

    style_parser = sub.add_parser("validate-style-card")
    style_parser.add_argument("style_card")

    requirements_parser = sub.add_parser("validate-requirements")
    requirements_parser.add_argument("summary")

    similarity_parser = sub.add_parser("similarity")
    similarity_parser.add_argument("generated")
    similarity_parser.add_argument("references", nargs="+")
    similarity_parser.add_argument("--whitelist-json", default="[]")

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
        elif args.command == "apply":
            result = apply_v2(
                load_json(Path(args.profile)), Path(args.docx).resolve(), load_json(Path(args.content)),
                Path(args.output).resolve(), args.overwrite,
            )
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
