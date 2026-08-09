#!/usr/bin/env python3
"""Validate a scaffolded subject lab-report skill package."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


REQUIRED_FILES = [
    "SKILL.md",
    "references/workflow.md",
    "references/document-understanding-policy.md",
    "references/docx-tooling-policy.md",
    "references/fill-policy.md",
    "references/finalize-policy.md",
    "references/formatting-notes.md",
    "references/tool-artifact-policy.md",
    "references/user-guidance-policy.md",
    "references/default-writing-parameters.md",
    "references/compliance.md",
    "references/iteration-log.md",
    "references/v2-workflow.md",
    "references/subject-contract.md",
    "references/skill-quality-contract.md",
    "references/quality-profile.json",
    "assets/fill-template.md",
    "assets/fill-map.schema.json",
    "assets/requirements-summary-v2.schema.json",
    "assets/section-plan-v2.schema.json",
    "assets/template-profile-v2.schema.json",
    "assets/content-package-v2.schema.json",
    "assets/writing-profile-v2.schema.json",
    "assets/style-card-v2.schema.json",
    "assets/skill-quality-profile-v2.schema.json",
    "evals/evals.json",
]


REQUIRED_SKILL_PHRASES = [
    "从头到尾完整阅读",
    "复述任务要求",
    "lab_factory_v2_prepare_autopilot",
    "第一次默认只填补",
    "section-plan.json",
    "不删除、不改写、不重排原文",
    "除此之外不得改变原结构、字体、字号、内容、格式和排版",
    "python-docx + lxml",
    "不使用生图伪造截图",
    "preflight 和最终 DOCX 两个常规确认点",
    "Finalize",
    "免责声明",
    "受控迭代",
    "不依赖 Codex-only 指令",
    "Claude Code",
    "requirements-summary",
    "OOXML inventory",
    "template-profile.json",
    "content-package.json",
    "variation_seed",
    "生成质量优先",
    "quality-profile.json",
    "用户临时调整",
    "质量自检",
    "WPS",
    "完成但不更新",
]


REQUIRED_REFERENCE_PHRASES = {
    "references/default-writing-parameters.md": [
        "小四",
        "黑色",
        "中文字体：宋体",
        "Times New Roman",
        "首行缩进",
        "150-200",
        "100 字",
    ],
    "references/docx-tooling-policy.md": [
        "python-docx",
        "lxml",
        "docxtpl",
        "Mammoth",
        "pywin32",
    ],
    "references/fill-policy.md": [
        "copy_mode: byte_for_byte_first",
        "format_strategy: inherit_target_anchor",
        "preserve_original: true",
    ],
    "references/finalize-policy.md": [
        "草稿输出后",
        "删除用户确认可删内容",
        "免责声明",
        "完成但不更新",
    ],
    "references/v2-workflow.md": [
        "lab_factory_v2_create_session",
        "lab_factory_v2_inventory_docx",
        "auto",
        "confirm",
        "blocked",
        "variation_seed",
        "相似性门禁",
        "完成且不更新",
    ],
    "references/subject-contract.md": [
        "规则摘要",
        "每次报告",
        "个人信息",
    ],
    "references/skill-quality-contract.md": [
        "生成质量优先",
        "variation_seed",
        "用户微调面板",
        "生成后自检",
        "不得写入",
    ],
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def validate_evals(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        return [f"evals/evals.json is invalid JSON: {exc}"]
    evals = data.get("evals") if isinstance(data, dict) else None
    if not isinstance(evals, list):
        return ["evals/evals.json must contain an evals array"]
    if len(evals) < 5:
        errors.append("evals/evals.json should contain at least 5 quality checks")
    expected_topics = [
        "fill",
        "完整阅读",
        "删除",
        "写作规范",
        "截图",
        "finalize",
    ]
    serialized = json.dumps(data, ensure_ascii=False)
    for topic in expected_topics:
        if topic not in serialized:
            errors.append(f"evals/evals.json missing topic: {topic}")
    return errors


def validate_quality_profile(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        return [f"references/quality-profile.json is invalid JSON: {exc}"]
    if not isinstance(data, dict):
        return ["references/quality-profile.json must contain an object"]
    if data.get("version") != "2.0":
        errors.append("quality profile version must be 2.0")
    if data.get("quality_priority") != "generation_quality_first":
        errors.append("quality profile must prioritize generation_quality_first")
    if data.get("scope_level") not in {"subject", "template", "experiment"}:
        errors.append("quality profile scope_level is invalid")
    axes = data.get("quality_axes")
    if not isinstance(axes, list) or len(axes) < 5:
        errors.append("quality profile needs at least 5 quality axes")
    else:
        required_axes = {"grounding", "coverage", "writing", "differentiation", "usability", "safety"}
        actual_axes = {item.get("id") for item in axes if isinstance(item, dict)}
        missing_axes = sorted(required_axes - actual_axes)
        if missing_axes:
            errors.append(f"quality profile missing axes: {', '.join(missing_axes)}")
    variation = data.get("variation_controls")
    if not isinstance(variation, dict):
        errors.append("quality profile missing variation_controls")
    else:
        if variation.get("variation_seed") != "session.variation_seed":
            errors.append("variation_controls must use session.variation_seed")
        if not isinstance(variation.get("dimensions"), list) or len(variation["dimensions"]) < 4:
            errors.append("variation_controls needs at least 4 dimensions")
        if not isinstance(variation.get("protected_facts"), list) or len(variation["protected_facts"]) < 3:
            errors.append("variation_controls needs protected facts")
    points = data.get("user_adjustment_points")
    if not isinstance(points, list) or len(points) < 4:
        errors.append("quality profile needs at least 4 user adjustment points")
    gates = data.get("quality_gates")
    if not isinstance(gates, list) or len(gates) < 6:
        errors.append("quality profile needs at least 6 quality gates")
    privacy = data.get("privacy")
    if not isinstance(privacy, dict) or privacy.get("style_card_only") is not True:
        errors.append("quality profile must enforce style-card-only reference persistence")
    elif not isinstance(privacy.get("forbidden_persistence"), list) or len(privacy["forbidden_persistence"]) < 4:
        errors.append("quality profile needs forbidden persistence categories")
    return errors


def validate_no_sensitive_leaks(skill_dir: Path) -> list[str]:
    """Reject obvious source paths, identifiers, or secret values in generated assets."""
    errors: list[str] = []
    path_pattern = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\)")
    identifier_pattern = re.compile(
        r"(?i)(姓名|学号|班级|序号|账号|密码|token|secret|api[_ -]?key)\s*[:：=]\s*(?!<)(?!用户)(?!运行时)[^\s，。；;]+"
    )
    number_pattern = re.compile(r"\b\d{10,18}\b")
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".json"}:
            continue
        text = read_text(path)
        if path_pattern.search(text):
            errors.append(f"generated skill contains a local path: {path.relative_to(skill_dir)}")
        if identifier_pattern.search(text):
            errors.append(f"generated skill contains a personal/secret value: {path.relative_to(skill_dir)}")
        if number_pattern.search(text):
            errors.append(f"generated skill contains a long identifier: {path.relative_to(skill_dir)}")
    return errors


def validate(skill_dir: Path) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    if not skill_dir.exists():
        return {"ok": False, "errors": [f"skill directory does not exist: {skill_dir}"], "warnings": []}
    if not skill_dir.is_dir():
        return {"ok": False, "errors": [f"path is not a directory: {skill_dir}"], "warnings": []}

    for relative in REQUIRED_FILES:
        if not (skill_dir / relative).exists():
            errors.append(f"missing required file: {relative}")

    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists():
        text = read_text(skill_md)
        if not text.lstrip().startswith("---"):
            errors.append("SKILL.md missing frontmatter")
        for phrase in REQUIRED_SKILL_PHRASES:
            if phrase not in text:
                errors.append(f"SKILL.md missing required phrase: {phrase}")
        if "Codex" in text and "Claude" not in text:
            warnings.append("SKILL.md mentions Codex without Claude; keep generated skills platform-neutral.")

    for relative, phrases in REQUIRED_REFERENCE_PHRASES.items():
        path = skill_dir / relative
        if not path.exists():
            continue
        text = read_text(path)
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{relative} missing required phrase: {phrase}")

    evals_path = skill_dir / "evals" / "evals.json"
    if evals_path.exists():
        errors.extend(validate_evals(evals_path))

    quality_profile_path = skill_dir / "references" / "quality-profile.json"
    if quality_profile_path.exists():
        errors.extend(validate_quality_profile(quality_profile_path))
    errors.extend(validate_no_sensitive_leaks(skill_dir))

    return {
        "ok": not errors,
        "skill_dir": str(skill_dir),
        "errors": errors,
        "warnings": warnings,
        "required_files": REQUIRED_FILES,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a scaffolded subject lab-report skill.")
    parser.add_argument("skill_dir", help="Path to generated subject skill directory.")
    args = parser.parse_args()

    result = validate(Path(args.skill_dir).expanduser().resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
