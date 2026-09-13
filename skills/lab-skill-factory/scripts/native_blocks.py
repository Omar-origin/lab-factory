"""Native DOCX blocks; no model, network, or desktop access is required."""

from __future__ import annotations
import copy
import hashlib
import math
import os
import re
import tempfile
import zipfile
from pathlib import Path
from lxml import etree
from docx.image.image import Image

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
NS = {
    "w": W,
    "r": R,
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}


def node(tag, **attrs):
    element = etree.Element("{" + W + "}" + tag)
    for key, value in attrs.items():
        element.set("{" + W + "}" + key, str(value))
    return element


def native_inventory(path):
    """Read actual objects and nearby captions, never count a bare caption as an object."""
    with zipfile.ZipFile(path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
        rels = (
            etree.fromstring(archive.read("word/_rels/document.xml.rels"))
            if "word/_rels/document.xml.rels" in archive.namelist()
            else etree.Element("rels")
        )
        image_ids = {
            x.get("Id")
            for x in rels
            if x.get("Type", "").endswith("/image")
            and x.get("TargetMode") != "External"
            and "word/" + x.get("Target", "") in archive.namelist()
        }
        entries = []
        for element in root.xpath("//w:tbl|//w:p[w:r/w:drawing]", namespaces=NS):
            kind = "表" if element.tag == "{" + W + "}tbl" else "图"
            if kind == "图" and not any(
                x in image_ids
                for x in element.xpath(".//a:blip/@r:embed", namespaces=NS)
            ):
                continue
            candidates = [element.getprevious(), element.getnext()]
            for sibling in candidates:
                if sibling is None or sibling.tag != "{" + W + "}p":
                    continue
                text = "".join(sibling.xpath(".//w:t/text()", namespaces=NS)).strip()
                match = re.fullmatch(r"(图|表)\s*(\d+(?:[-－.]\d+)*)[：:\s]+(.+)", text)
                if match and match[1] == kind:
                    entries.append(
                        {
                            "kind": kind,
                            "id": kind + match[2].replace("－", "-").replace(".", "-"),
                            "title": match[3],
                        }
                    )
                    break
        authored = []
        authored_prose = []
        for paragraph in root.xpath(
            '//w:p[w:bookmarkStart[starts-with(@w:name,"lf_")]]', namespaces=NS
        ):
            text = "".join(paragraph.xpath(".//w:t/text()", namespaces=NS))
            if text:
                authored.append(text)
                if paragraph.xpath(
                    'w:bookmarkStart[starts-with(@w:name,"lf_prose_")]', namespaces=NS
                ):
                    authored_prose.append(text)
        return {
            "entries": entries,
            "table_count": len(root.xpath("//w:tbl", namespaces=NS)),
            "image_count": len(root.xpath("//wp:inline", namespaces=NS)),
            "authored_paragraphs": authored,
            "authored_prose": authored_prose,
        }


def apply(engine, profile, target, package, output, overwrite=False, workspace=None):
    E = engine.V2Error
    root_dir = Path(workspace or output.parent).resolve()
    if target.resolve() == output.resolve():
        raise E("Output must not overwrite the source document")
    if output.exists() and not overwrite:
        raise E(f"Output already exists: {output}")
    if not output.resolve().is_relative_to(root_dir):
        raise E("Output must be inside workspace")
    items = package.get("items")
    if not isinstance(items, list) or not items:
        raise E("items must be a non-empty array")
    assets = package.get("assets", {})
    if not isinstance(assets, dict):
        raise E("assets must be an object")
    caption_map, seen = {}, set()
    counts = {"figure": 0, "table": 0}
    chapter = str(package.get("chapter", "1"))
    if not re.fullmatch(r"\d{1,3}", chapter):
        raise E("chapter must be 1-3 digits")
    converted = []
    for item in items:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("blocks"), list)
            or not item["blocks"]
        ):
            raise E("Each item requires blocks")
        if item.get("field_id") in seen:
            raise E("Duplicate field_id")
        seen.add(item.get("field_id"))
        texts = []
        for block in item["blocks"]:
            if not isinstance(block, dict) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,64}", str(block.get("id", ""))
            ):
                raise E("Each block requires a stable ASCII id")
            if block["id"] in seen:
                raise E("Duplicate block id")
            seen.add(block["id"])
            kind = block.get("type")
            if kind not in ("paragraph", "figure", "table"):
                raise E(f"Unsupported block type: {kind}")
            if kind in counts:
                cap = block.get("caption_id")
                title = block.get("caption")
                if (
                    not isinstance(cap, str)
                    or not cap
                    or cap in caption_map
                    or not isinstance(title, str)
                    or not title.strip()
                ):
                    raise E("Unique caption_id and caption required")
                counts[kind] += 1
                caption_map[cap] = (
                    "图" if kind == "figure" else "表"
                ) + f" {chapter}-{counts[kind]}"
                texts.append(title)
            else:
                segments = block.get("segments", [])
                if not isinstance(segments, list):
                    raise E("paragraph.segments must be an array")
                texts.append(
                    str(block.get("text", ""))
                    or "".join(
                        str(x.get("text", "")) if isinstance(x, dict) else ""
                        for x in segments
                    )
                    or "正文引用"
                )
        converted.append(dict(item, content="\n".join(texts)))
    inventory = engine.inventory_docx(target)
    placements = engine.propose_placements(profile, inventory)
    resolved = engine.resolve_content_items(
        profile, inventory, placements, {"items": converted}
    )
    before = engine.zip_entry_hashes(target)
    with zipfile.ZipFile(target) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    source_hash = engine.file_sha256(target)
    document = etree.fromstring(parts["word/document.xml"])
    relname = "word/_rels/document.xml.rels"
    rels = (
        etree.fromstring(parts[relname])
        if relname in parts
        else etree.Element("{" + PKG + "}Relationships", nsmap={None: PKG})
    )
    types = etree.fromstring(parts["[Content_Types].xml"])
    drawing_ids = document.xpath("//@id") + document.xpath("//@w:id", namespaces=NS)
    seq = max([int(x) for x in drawing_ids if str(x).isdigit()] + [0]) + 1
    emitted_assets = []
    inserted = []
    references = []

    def paragraph(
        text, reference, block_id=None, center=False, keep=False, prose=False
    ):
        nonlocal seq
        p = engine.paragraph_with_text(
            reference, text, strip_numbering=True, normalize_color=True
        )
        prop = p.find("{" + W + "}pPr")
        if prop is None:
            prop = node("pPr")
            p.insert(0, prop)
        for old in list(prop):
            if old.tag in [
                "{" + W + "}keepNext",
                "{" + W + "}jc",
                "{" + W + "}spacing",
            ]:
                prop.remove(old)
        prop.append(node("spacing", after=120, line=276, lineRule="auto"))
        if center:
            prop.append(node("jc", val="center"))
        if keep:
            prop.append(node("keepNext"))
        if block_id:
            mark = node(
                "bookmarkStart",
                id=seq,
                name=("lf_prose_" if prose else "lf_")
                + hashlib.sha256(block_id.encode()).hexdigest()[:24],
            )
            end = node("bookmarkEnd", id=seq)
            seq += 1
            p.insert(1, mark)
            p.append(end)
        return p

    def plain(block):
        if "segments" not in block:
            value = block.get("text")
            if not isinstance(value, str) or not value.strip():
                raise E("paragraph.text required")
            return value
        result = []
        for segment in block["segments"]:
            if not isinstance(segment, dict):
                raise E("Invalid paragraph segment")
            if "ref" in segment:
                if segment["ref"] not in caption_map:
                    raise E("Unknown caption reference")
                references.append(segment["ref"])
                result.append(caption_map[segment["ref"]])
            elif isinstance(segment.get("text"), str):
                result.append(segment["text"])
            else:
                raise E("Segment requires text or ref")
        return "".join(result)

    targets = []
    for change, item in zip(resolved, items):
        if change["node"]["part_name"] != "word/document.xml":
            raise E("Native blocks currently require main document story")
        found = document.xpath(change["node"]["path"], namespaces=NS)
        if len(found) != 1:
            raise E("Template location drift")
        target_p = found[0]
        operation = change["field"]["operation"]
        if (
            operation == "replace_placeholder"
            and engine.element_text(target_p).strip()
            != str(change["field"]["locator"].get("text", "")).strip()
        ):
            raise E("Native replacement requires a whole-paragraph placeholder")
        if operation not in ("insert_after", "replace_placeholder", "fill_cell"):
            raise E("Unsupported native operation")
        if target_p.xpath(
            'ancestor::w:tr/w:trPr/w:trHeight[@w:hRule="exact"]', namespaces=NS
        ):
            raise E(
                "Fixed-height template row requires review before inserting native blocks"
            )
        targets.append((change, item, target_p))
    if len({id(x[2]) for x in targets}) != len(targets):
        raise E("Native block targets must be distinct")
    for change, item, target_p in targets:
        reference = engine.insert_style_reference(target_p)
        section = target_p.xpath(
            "following::w:sectPr[1]", namespaces=NS
        ) or document.xpath("//w:sectPr", namespaces=NS)
        width = 9000
        if section:
            size = section[0].find("{" + W + "}pgSz")
            margins = section[0].find("{" + W + "}pgMar")
            if size is not None and margins is not None:
                width = int(size.get("{" + W + "}w", "11906")) - sum(
                    int(margins.get("{" + W + "}" + k, "1440"))
                    for k in ("left", "right")
                )
            cols = section[0].find("{" + W + "}cols")
            if cols is not None and int(cols.get("{" + W + "}num", "1")) > 1:
                raise E(
                    "Multi-column native insertion requires an explicit layout review"
                )
        parent = target_p.getparent()
        if parent.tag == "{" + W + "}tc":
            tcw = parent.find("{" + W + "}tcPr/{" + W + "}tcW")
            if tcw is None or tcw.get("{" + W + "}type") != "dxa":
                raise E("Cannot determine table cell width")
            width = min(width, int(tcw.get("{" + W + "}w")) - 240)
        if width < 720:
            raise E("Writable region too narrow")
        blocks = []
        for b in item["blocks"]:
            if b["type"] == "paragraph":
                blocks.append(paragraph(plain(b), reference, b["id"], prose=True))
                continue
            cap = caption_map[b["caption_id"]] + " " + b["caption"]
            if b["type"] == "figure":
                asset = assets.get(b.get("asset_id"))
                if not isinstance(asset, dict):
                    raise E("Figure asset is not registered")
                file = (root_dir / str(asset.get("relative_path", ""))).resolve()
                if not file.is_relative_to(root_dir) or not file.is_file():
                    raise E("Asset path is outside workspace or missing")
                if file.stat().st_size > 25 * 1024 * 1024:
                    raise E("Image exceeds 25 MB")
                raw = file.read_bytes()
                if len(raw) > 25 * 1024 * 1024:
                    raise E("Image exceeds 25 MB")
                digest = hashlib.sha256(raw).hexdigest()
                if digest != asset.get("sha256"):
                    raise E("Asset hash mismatch")
                try:
                    image = Image.from_blob(raw)
                except Exception as exc:
                    raise E("Invalid image") from exc
                if (
                    image.content_type not in ("image/png", "image/jpeg")
                    or image.px_width * image.px_height > 40000000
                ):
                    raise E("Only PNG/JPEG up to 40 megapixels supported")
                ext = "png" if image.content_type == "image/png" else "jpg"
                media = "media/lf_" + digest + "." + ext
                if "word/" + media in parts and parts["word/" + media] != raw:
                    raise E("Media name conflict")
                parts["word/" + media] = raw
                rid = next(
                    (
                        x.get("Id")
                        for x in rels
                        if x.get("Target") == media
                        and x.get("Type", "").endswith("/image")
                    ),
                    None,
                )
                if rid is None:
                    rid = "rIdLF" + digest[:16]
                    existing = {x.get("Id") for x in rels}
                    while rid in existing:
                        rid += "x"
                    etree.SubElement(
                        rels,
                        "{" + PKG + "}Relationship",
                        Id=rid,
                        Type=R + "/image",
                        Target=media,
                    )
                if not any(x.get("Extension") == ext for x in types):
                    etree.SubElement(
                        types,
                        "{" + CT + "}Default",
                        Extension=ext,
                        ContentType=image.content_type,
                    )
                cx = min(width * 635, image.px_width * 9525)
                cy = round(cx * image.px_height / image.px_width)
                if cy > 7000000:
                    cx = round(cx * 7000000 / cy)
                    cy = 7000000
                p = paragraph("", reference, b["id"], True, True)
                drawing = etree.fromstring(
                    f'''<w:r xmlns:w="{W}" xmlns:r="{R}" xmlns:wp="{NS["wp"]}" xmlns:a="{NS["a"]}" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:drawing><wp:inline><wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{seq}" name="Figure {seq}"/><wp:cNvGraphicFramePr/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="{seq}" name="Image"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>'''
                )
                drawing.xpath(".//wp:docPr", namespaces=NS)[0].set(
                    "descr", b["caption"]
                )
                seq += 1
                p.insert(len(p) - 1, drawing)
                blocks.extend([p, paragraph(cap, reference, b["id"] + "_cap", True)])
                emitted_assets.append(
                    {
                        "asset_id": b["asset_id"],
                        "sha256": digest,
                        "media_part": "word/" + media,
                    }
                )
            else:
                columns = b.get("columns")
                rows = b.get("rows")
                if (
                    not isinstance(columns, list)
                    or not 1 <= len(columns) <= 12
                    or not all(isinstance(x, str) for x in columns)
                ):
                    raise E("table.columns requires 1-12 strings")
                if not isinstance(rows, list) or not rows or len(rows) > 1000:
                    raise E("table.rows requires 1-1000 rows")
                if any(
                    not isinstance(row, list)
                    or len(row) != len(columns)
                    or any(
                        not isinstance(v, (str, int, float))
                        or isinstance(v, bool)
                        or (isinstance(v, float) and not math.isfinite(v))
                        for v in row
                    )
                    for row in rows
                ):
                    raise E("Table row column count/type mismatch")
                tbl = node("tbl")
                props = node("tblPr")
                tbl.append(props)
                props.append(node("tblW", w=width, type="dxa"))
                props.append(node("tblLayout", type="fixed"))
                borders = node("tblBorders")
                props.append(borders)
                for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
                    borders.append(
                        node(
                            edge,
                            val="single" if edge in ("top", "bottom") else "nil",
                            sz=12,
                            color="000000",
                        )
                    )
                margins = node("tblCellMar")
                props.append(margins)
                for edge in ("top", "left", "bottom", "right"):
                    margins.append(node(edge, w=80, type="dxa"))
                grid = node("tblGrid")
                tbl.append(grid)
                colwidths = [width // len(columns)] * len(columns)
                colwidths[-1] += width - sum(colwidths)
                for cw in colwidths:
                    grid.append(node("gridCol", w=cw))
                for ri, row in enumerate([columns] + rows):
                    tr = node("tr")
                    tbl.append(tr)
                    rp = node("trPr")
                    tr.append(rp)
                    if ri == 0:
                        rp.append(node("tblHeader"))
                    rp.append(node("cantSplit"))
                    for ci, value in enumerate(row):
                        tc = node("tc")
                        tr.append(tc)
                        cp = node("tcPr")
                        tc.append(cp)
                        cp.append(node("tcW", w=colwidths[ci], type="dxa"))
                        if ri == 0:
                            cb = node("tcBorders")
                            cp.append(cb)
                            cb.append(
                                node("bottom", val="single", sz=4, color="000000")
                            )
                        tc.append(
                            paragraph(str(value), reference, b["id"] + f"_{ri}_{ci}")
                        )
                blocks.extend(
                    [paragraph(cap, reference, b["id"] + "_cap", True, True), tbl]
                )
            inserted.append(
                {
                    "block_id": b["id"],
                    "kind": b["type"],
                    "caption_id": b["caption_id"],
                    "label": caption_map[b["caption_id"]],
                }
            )
        index = parent.index(target_p) + (
            1 if change["field"]["operation"] == "insert_after" else 0
        )
        if change["field"]["operation"] != "insert_after":
            parent.remove(target_p)
        for offset, element in enumerate(blocks):
            parent.insert(index + offset, element)
        if parent.tag == "{" + W + "}tc" and parent[-1].tag != "{" + W + "}p":
            parent.append(node("p"))
    # All captions must have explicit machine-resolved references in authored prose.
    if set(caption_map) - set(references):
        raise E(
            "Every figure/table requires a paragraph segment ref: "
            + ",".join(sorted(set(caption_map) - set(references)))
        )
    parts["word/document.xml"] = etree.tostring(
        document, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    if emitted_assets:
        parts[relname] = etree.tostring(
            rels, xml_declaration=True, encoding="UTF-8", standalone=True
        )
        parts["[Content_Types].xml"] = etree.tostring(
            types, xml_declaration=True, encoding="UTF-8", standalone=True
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(suffix=".docx", dir=output.parent)
    os.close(fd)
    temp = Path(temp)
    try:
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as z:
            for name, raw in parts.items():
                z.writestr(name, raw)
        engine.ensure_docx_disclaimer(temp)
        after = engine.zip_entry_hashes(temp)
        changed = {n for n in before if before[n] != after.get(n)}
        allowed = {"word/document.xml"} | (
            {relname, "[Content_Types].xml"} if emitted_assets else set()
        )
        if changed - allowed:
            raise E("Unexpected package change")
        if engine.file_sha256(target) != source_hash:
            raise E("Source changed during native write")
        native_inventory(temp)
        os.replace(temp, output)
    finally:
        if temp.exists():
            temp.unlink()
    return {
        "ok": True,
        "version": "3.0",
        "source_sha256": source_hash,
        "output_document": str(output),
        "output_sha256": engine.file_sha256(output),
        "changed_parts": sorted(changed),
        "added_parts": sorted(set(after) - set(before)),
        "assets": emitted_assets,
        "blocks": inserted,
        "wps_review_required": True,
        "native_objects": native_inventory(output),
    }
