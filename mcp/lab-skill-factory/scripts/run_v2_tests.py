#!/usr/bin/env python3
"""Self-contained regression tests for the Lab Factory v2 engine."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

from docx import Document


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
ROOT = SCRIPT_ROOT if (SCRIPT_ROOT / "skills" / "lab-skill-factory").exists() else Path(__file__).resolve().parents[3]
ENGINE_PATH = ROOT / "skills" / "lab-skill-factory" / "scripts" / "v2_engine.py"
SPEC = importlib.util.spec_from_file_location("lab_factory_v2_engine", ENGINE_PATH)
assert SPEC and SPEC.loader
ENGINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ENGINE)


def make_template(path: Path) -> None:
    document = Document()
    document.add_heading("实验报告", level=1)
    document.add_paragraph("实验目的")
    document.add_paragraph("请在此处填写实验目的")
    table = document.add_table(rows=3, cols=2)
    table.style = "Table Grid"
    table.cell(0, 0).text = "栏目"
    table.cell(0, 1).text = "填写内容"
    table.cell(1, 0).text = "实验结果"
    table.cell(1, 1).text = "<结果待填>"
    table.cell(2, 0).text = "实验小结"
    table.cell(2, 1).text = "<小结待填>"
    document.add_paragraph("实验结果")
    document.add_paragraph("此处仅为提交说明，不应写入")
    if not getattr(sys, "frozen", False):
        section = document.sections[0]
        section.header.paragraphs[0].text = "课程实验报告"
    document.save(path)


def xml_entry_hashes(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        return {name: ENGINE.sha256(archive.read(name)) for name in archive.namelist()}


def add_alternate_text_box(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    root = ENGINE.etree.fromstring(entries["word/document.xml"])
    body = root.find(f".//{ENGINE.W}body")
    alternate = ENGINE.etree.Element(f"{{{ENGINE.NS['mc']}}}AlternateContent")
    choice = ENGINE.etree.SubElement(alternate, f"{{{ENGINE.NS['mc']}}}Choice")
    choice.set("Requires", "wps")
    fallback = ENGINE.etree.SubElement(alternate, f"{{{ENGINE.NS['mc']}}}Fallback")
    for branch in (choice, fallback):
        text_box = ENGINE.etree.SubElement(branch, f"{ENGINE.W}txbxContent")
        paragraph = ENGINE.etree.SubElement(text_box, f"{ENGINE.W}p")
        run = ENGINE.etree.SubElement(paragraph, f"{ENGINE.W}r")
        text = ENGINE.etree.SubElement(run, f"{ENGINE.W}t")
        text.text = "兼容文本框"
    section_properties = body.find(f"{ENGINE.W}sectPr")
    if section_properties is None:
        body.append(alternate)
    else:
        body.insert(body.index(section_properties), alternate)
    entries["word/document.xml"] = ENGINE.etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone="yes")
    rewritten = path.with_suffix(".rewritten.docx")
    with zipfile.ZipFile(rewritten, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    os.replace(rewritten, path)


def run() -> dict:
    results = []
    with tempfile.TemporaryDirectory(prefix="lab-factory-v2-tests-") as temporary_dir:
        root = Path(temporary_dir)
        template = root / "template.docx"
        output = root / "draft.docx"
        make_template(template)
        source_hash = ENGINE.file_sha256(template)

        inventory = ENGINE.inventory_docx(template)
        header_expected = not getattr(sys, "frozen", False)
        results.append({"name": "inventory-stories", "ok": (inventory["story_counts"].get("header1") == 1) == header_expected})
        result_node = next(
            node for node in inventory["nodes"]
            if node["container"] == "table_cell" and node["text"] == "<结果待填>"
        )
        summary_node = next(
            node for node in inventory["nodes"]
            if node["container"] == "table_cell" and node["text"] == "<小结待填>"
        )
        results.append({"name": "inventory-table-coordinate", "ok": result_node["coordinates"] == {"table": 0, "row": 1, "cell": 1, "paragraph": 0}})

        alternate_template = root / "alternate-template.docx"
        make_template(alternate_template)
        add_alternate_text_box(alternate_template)
        alternate_inventory = ENGINE.inventory_docx(alternate_template)
        alternate_nodes = [node for node in alternate_inventory["nodes"] if node["text"] == "兼容文本框"]
        results.append({
            "name": "alternate-content-deduplicated",
            "ok": len(alternate_nodes) == 1 and alternate_nodes[0]["unsupported"] == ["text_box"],
        })

        profile = ENGINE.create_template_profile(
            inventory,
            [
                {"id": "result", "node_id": result_node["node_id"], "operation": "replace_placeholder", "semantic_role": "实验结果"},
                {"id": "summary", "node_id": summary_node["node_id"], "operation": "fill_cell", "semantic_role": "实验小结"},
            ],
            "软件工程",
        )
        proposals = ENGINE.propose_placements(profile, inventory)
        results.append({"name": "placements-auto", "ok": proposals["summary"] == {"auto": 2, "confirm": 0, "blocked": 0}})
        related = root / "related.docx"
        related_document = Document(template)
        related_document.add_paragraph("本次实验新增的长段落内容不会改变模板家族判断。")
        related_document.add_paragraph("另一段填写后的实验说明。")
        related_document.save(related)
        related_inventory = ENGINE.inventory_docx(related)
        related_plan = ENGINE.propose_placements(profile, related_inventory)
        results.append({
            "name": "family-compatible-after-content-growth",
            "ok": (
                not related_plan["family_fingerprint_match"]
                and related_plan["family_compatible"]
                and related_plan["family_compatibility"]["score"] >= ENGINE.FAMILY_COMPATIBILITY_THRESHOLD
                and related_plan["summary"]["auto"] == 2
            ),
        })
        confirmed = ENGINE.confirmed_profile(profile, inventory, proposals, [], "用户确认当前模板位置")
        results.append({"name": "profile-drift-history", "ok": len(confirmed["drift_history"]) == 1})

        incompatible = root / "incompatible.docx"
        incompatible_document = Document()
        incompatible_document.add_paragraph("实验结果")
        incompatible_document.add_paragraph("这里没有表格")
        incompatible_document.save(incompatible)
        incompatible_plan = ENGINE.propose_placements(profile, ENGINE.inventory_docx(incompatible))
        results.append({"name": "container-conflict-blocked", "ok": incompatible_plan["summary"]["blocked"] == 2})
        results.append({"name": "unrelated-family-rejected", "ok": incompatible_plan["family_compatible"] is False})

        content = {
            "version": "2.0",
            "items": [
                {"field_id": "result", "content": "程序运行成功，输出与预期一致。"},
                {"field_id": "summary", "content": "本次实验重点验证了表格内安全写入。"},
            ],
        }
        before_entries = xml_entry_hashes(template)
        apply_result = ENGINE.apply_v2(profile, template, content, output)
        after_entries = xml_entry_hashes(output)
        untouched = all(
            before_entries[name] == after_entries[name]
            for name in before_entries
            if name not in apply_result["changed_parts"]
        )
        output_inventory = ENGINE.inventory_docx(output)
        output_text = "\n".join(node["text"] for node in output_inventory["nodes"])
        results.append({"name": "source-unchanged", "ok": ENGINE.file_sha256(template) == source_hash})
        results.append({"name": "package-preservation", "ok": untouched and apply_result["changed_parts"] == ["word/document.xml"]})
        results.append({"name": "table-writeback", "ok": "程序运行成功" in output_text and "表格内安全写入" in output_text})

        session_workspace = root / "session"
        session = ENGINE.create_session(session_workspace, "软件工程")
        for event in ("confirm_requirements", "resolve_placements", "mark_content_ready", "record_draft"):
            session = ENGINE.advance_session(session_workspace, event, None, None)
        review_id = session["session"]["review_id"]
        session = ENGINE.advance_session(session_workspace, "approve_draft", review_id, "用户确认草稿位置正确")
        session = ENGINE.advance_session(session_workspace, "finalize", review_id, "用户确认生成终稿")
        session = ENGINE.advance_session(session_workspace, "finish_without_update", review_id, "本次不更新 Skill")
        results.append({"name": "session-state-machine", "ok": session["session"]["state"] == "iteration_decided"})

        writing = ENGINE.create_writing_profile("软件工程", "technical", {"tone": "规范"})
        results.append({"name": "writing-profile", "ok": writing["dimensions"]["detail"] == "详细" and writing["dimensions"]["tone"] == "规范"})

        generated = root / "generated.md"
        reference = root / "reference.md"
        repeated = "这是一段长度超过四十个汉字并且不应该从参考实验报告原样复制到最终报告中的测试内容用于验证门禁"
        generated.write_text(repeated + "。", encoding="utf-8")
        reference.write_text(repeated + "。另一段。", encoding="utf-8")
        similarity = ENGINE.similarity_check(generated, [reference], [])
        results.append({"name": "similarity-block", "ok": similarity["gate"] == "blocked"})

        migration = ENGINE.migrate_v1({"target_document": "old.docx", "items": [{"id": "summary", "target_anchor": "实验小结", "operation": "insert_after"}]})
        results.append({"name": "v1-migration", "ok": migration["fields"][0]["requires_relocation"] is True})

        # Exercise the public MCP handlers and their workflow preconditions in source mode.
        server_path = ROOT / "mcp" / "lab-skill-factory" / "server.py"
        if server_path.exists():
            server_spec = importlib.util.spec_from_file_location("lab_factory_test_server", server_path)
            assert server_spec and server_spec.loader
            server = importlib.util.module_from_spec(server_spec)
            server_spec.loader.exec_module(server)
            os.environ["LAB_FACTORY_DEV_ALLOW"] = "1"
            api_workspace = root / "api-workspace"
            server.tool_v2_create_session({"workspace": str(api_workspace), "subject": "软件工程"})
            requirements_path = root / "requirements.json"
            ENGINE.write_json(
                requirements_path,
                {
                    "version": "2.0", "experiment": {}, "tools": [], "formatting": {},
                    "evidence": [], "submission": {}, "writable_regions": [],
                    "protected_regions": [], "missing": [], "conflicts": [],
                },
            )
            server.tool_v2_confirm_requirements({"workspace": str(api_workspace), "requirements_path": str(requirements_path), "user_confirmation_summary": "用户确认需求摘要"})
            inventory_path = root / "inventory.json"
            server.tool_v2_inventory({"docx_path": str(template), "output_path": str(inventory_path)})
            profile_path = root / "profile.json"
            fields = [
                {"id": "result", "node_id": result_node["node_id"], "operation": "replace_placeholder"},
                {"id": "summary", "node_id": summary_node["node_id"], "operation": "fill_cell"},
            ]
            server.tool_v2_create_template_profile({"inventory_path": str(inventory_path), "subject": "软件工程", "fields": fields, "output_path": str(profile_path)})
            plan_path = root / "placements.json"
            server.tool_v2_propose_placements({"profile_path": str(profile_path), "docx_path": str(template), "output_path": str(plan_path)})
            updated_profile_path = root / "profile-confirmed.json"
            server.tool_v2_resolve_placements({
                "workspace": str(api_workspace), "profile_path": str(profile_path), "docx_path": str(template),
                "placement_plan_path": str(plan_path), "updated_profile_path": str(updated_profile_path),
                "selections": [], "user_confirmation_summary": "全部为高置信度位置",
            })
            server.tool_v2_mark_content_ready({"workspace": str(api_workspace), "content_summary": "两个字段内容已准备"})
            content_path = root / "content.json"
            ENGINE.write_json(content_path, content)
            api_output = root / "api-draft.docx"
            draft_result = server.tool_v2_apply_draft({
                "workspace": str(api_workspace), "profile_path": str(updated_profile_path),
                "docx_path": str(template), "content_package_path": str(content_path), "output_path": str(api_output),
            })
            api_review_id = draft_result["session"]["review_id"]
            server.tool_v2_review_draft({"workspace": str(api_workspace), "review_id": api_review_id, "decision": "approve", "user_feedback_summary": "WPS 检查通过"})
            server.tool_v2_finalize({"workspace": str(api_workspace), "review_id": api_review_id, "generated_path": str(api_output), "reference_paths": [], "user_confirmation_summary": "用户确认终稿"})
            subject_skill = root / "subject-skill"
            subject_skill.mkdir()
            (subject_skill / "SKILL.md").write_text("---\nname: test-skill\ndescription: test\n---\n", encoding="utf-8")
            update_proposal_path = root / "skill-update.json"
            update_proposal = server.tool_v2_propose_skill_update({
                "workspace": str(api_workspace), "skill_dir": str(subject_skill),
                "updates": [{
                    "path": "references/course-rules.json", "scope": "course", "reusable": True,
                    "reason": "保存稳定课程格式", "content": json.dumps({"font": "宋体", "size": "小四"}, ensure_ascii=False),
                }],
                "output_path": str(update_proposal_path),
            })
            update_id = update_proposal["proposal"]["update_id"]
            final_state = server.tool_v2_apply_skill_update({
                "workspace": str(api_workspace), "proposal_path": str(update_proposal_path),
                "update_id": update_id, "review_id": api_review_id,
                "user_confirmation_summary": "用户审阅 diff 后确认更新",
            })
            results.append({"name": "mcp-v2-workflow", "ok": final_state["session"]["state"] == "iteration_decided"})
            try:
                ENGINE.propose_skill_update(subject_skill, [{
                    "path": "references/course-rules.json", "scope": "course", "reusable": True,
                    "content": '{"学号":"20260001"}',
                }])
                privacy_blocked = False
            except ENGINE.V2Error:
                privacy_blocked = True
            results.append({"name": "skill-update-privacy-gate", "ok": privacy_blocked})

    failed = [item["name"] for item in results if not item["ok"]]
    return {"ok": not failed, "count": len(results), "failed": failed, "results": results}


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)
