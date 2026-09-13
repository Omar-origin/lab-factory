#!/usr/bin/env python3
"""Lab Factory v2.1 outcome-first orchestration.

This module deliberately does not read conversations or generate report prose.
It persists a small, privacy-safe interaction plan and tells the host agent when
it may continue automatically and when user input is required.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import artifact_store


VERSION = "2.1"
WRITER_GENOME_VERSION = "3.0"
MAX_IDEMPOTENCY_RESULTS = 50
LOCK_TIMEOUT_SECONDS = 5.0
NEXT_ACTIONS = {
    "ask_user", "auto_advance", "await_host_artifact",
    "deliver_preview", "blocked", "done",
}
QUESTION_SCOPES = {
    "stable_preference", "task_requirement", "format_conflict",
    "section_change", "placement_choice",
}
TERMINAL_STATES = {"iteration_decided", "cancelled"}
REQUIRED_QUALITY_GATES = {
    "source_coverage",
    "fact_integrity",
    "student_identity",
    "style_application",
    "humanization",
    "anti_copy",
    "cross_report_collision",
    "structure_diversity",
    "caption_cross_reference",
    "evidence_placeholder_balance",
}

LAYOUT_ARCHETYPES = [
    "figure_led_explanation",
    "explanation_then_evidence",
    "visual_walkthrough",
    "table_led_analysis",
    "mixed_evidence_weave",
]

LAYOUT_ARCHETYPE_RULES = {
    "figure_led_explanation": {
        "opening_flow": "figure_placeholder_then_caption_then_explanation",
        "visual_density": "medium",
        "table_role": "comparison_or_registry_after_visual",
    },
    "explanation_then_evidence": {
        "opening_flow": "explanation_then_cross_reference_then_figure_placeholder",
        "visual_density": "low_to_medium",
        "table_role": "summary_after_explanation_when_row_column_data_exists",
    },
    "visual_walkthrough": {
        "opening_flow": "short_context_then_interleaved_visuals_and_notes",
        "visual_density": "high",
        "table_role": "compact_checkpoint_or_result_matrix",
    },
    "table_led_analysis": {
        "opening_flow": "numbered_table_then_interpretation_then_supporting_figure",
        "visual_density": "medium",
        "table_role": "primary_comparison_or_design_inventory",
    },
    "mixed_evidence_weave": {
        "opening_flow": "alternate_prose_table_and_figure_by_information_type",
        "visual_density": "medium_to_high",
        "table_role": "use_for_repeated_comparable_records_not_prose_packaging",
    },
}

GENOME_AXES: dict[str, list[str]] = {
    "reasoning_route": ["principle_to_operation", "operation_to_result", "result_to_explanation", "problem_to_resolution"],
    "explanation_shape": ["cause_and_effect", "step_and_verification", "comparison_and_choice", "constraint_and_tradeoff"],
    "sentence_rhythm": ["short_with_occasional_long", "mixed_balanced", "medium_with_short_checks", "long_then_short_conclusion"],
    "paragraph_movement": ["one_action_one_paragraph", "claim_evidence_explanation", "observation_then_reason", "problem_process_takeaway"],
    "terminology_handling": ["brief_first_use_definition", "term_then_operation", "term_then_example", "direct_course_term_use"],
    "evidence_habit": ["result_linked", "step_verified", "contrast_expected_actual", "limitation_linked"],
    "person_voice": ["mostly_neutral", "first_person_in_actions", "first_person_in_reflection", "limited_first_person_mixed"],
    "reflection_signature": ["debugging_process", "concept_understanding", "implementation_tradeoff", "limitation_and_improvement"],
    "uncertainty_style": ["state_specific_limit", "name_missing_evidence", "compare_expected_actual", "reserve_only_with_reason"],
    "connector_density": ["low", "medium", "selective"],
    "list_usage": ["low", "medium", "section_dependent"],
    "revision_focus": ["remove_filler", "clarify_evidence", "vary_rhythm", "tighten_student_boundary"],
}

PREFERENCE_SCHEMA: dict[str, dict[str, Any]] = {
    "writing_level": {
        "values": ["basic", "natural_undergrad", "mature"],
        "default": "natural_undergrad", "prompt": "写作水平希望偏基础、自然本科还是较成熟？",
    },
    "detail_level": {
        "values": ["concise", "balanced", "detailed"],
        "default": "balanced", "prompt": "正文希望精简、均衡还是详细？",
    },
    "sentence_paragraph_style": {
        "values": ["short", "mixed", "long"],
        "default": "mixed", "prompt": "句子和段落希望偏短、长短混合还是偏长？",
    },
    "terminology_density": {
        "values": ["low", "medium", "high"],
        "default": "medium", "prompt": "专业术语密度希望低、中还是高？",
    },
    "voice_tone": {
        "values": ["plain", "formal", "technical", "personal"],
        "default": "formal", "prompt": "语气希望朴素、正式、技术型还是个人化？",
    },
    "analysis_order": {
        "values": ["principle_first", "procedure_first", "result_first"],
        "default": "principle_first", "prompt": "分析希望先讲原理、先讲步骤还是先讲结果？",
    },
    "reflection_depth": {
        "values": ["learning_process", "problem_solving", "engineering", "critical_improvement"],
        "default": "problem_solving", "prompt": "反思重点希望是学习过程、问题解决、工程实践还是批判改进？",
    },
    "variation_strength": {
        "values": ["low", "medium", "high"],
        "default": "medium", "prompt": "与通用报告相比，希望差异化程度低、中还是高？",
    },
}

LEGACY_PROFILE_MAP = {
    "level": {"基础": "basic", "自然本科": "natural_undergrad", "较成熟": "mature"},
    "detail": {"精简": "concise", "均衡": "balanced", "详细": "detailed"},
    "tone": {"朴素": "plain", "规范": "formal", "技术型": "technical", "个人化": "personal"},
    "reflection": {
        "学习过程": "learning_process", "问题解决": "problem_solving",
        "工程实践": "engineering", "批判改进": "critical_improvement",
    },
}


class AutopilotError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AutopilotError("ARTIFACT_INVALID", f"无法读取 {label}：{exc}") from exc
    if not isinstance(value, dict):
        raise AutopilotError("ARTIFACT_INVALID", f"{label} 顶层必须是对象。")
    return value


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def root_path(workspace: Path) -> Path:
    return workspace / "lab-factory"


def state_path(workspace: Path) -> Path:
    return root_path(workspace) / "session-state.json"


def object_path(workspace: Path, object_id: str) -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,80}", object_id):
        raise AutopilotError("OBJECT_ID_INVALID", f"非法对象 ID：{object_id}")
    return root_path(workspace) / "objects" / f"{object_id}.json"


def read_state(workspace: Path) -> dict[str, Any]:
    path = state_path(workspace)
    if not path.exists():
        raise AutopilotError("SESSION_NOT_FOUND", "当前 workspace 没有自动驾驶会话。")
    value = load_object(path, "session state")
    if value.get("version") != VERSION:
        raise AutopilotError(
            "LEGACY_SESSION",
            "检测到旧版 v2.0 会话；请继续使用 strict 旧流程，新建 workspace 后才能启用自动驾驶。",
            {"version": value.get("version"), "mode": "strict"},
        )
    return value


def append_audit(workspace: Path, event: dict[str, Any]) -> None:
    path = root_path(workspace) / "autopilot-audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = {
        key: value for key, value in event.items()
        if key in {"at", "event", "from", "to", "state_version", "question_ids", "reason_code", "error_code"}
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe, ensure_ascii=False) + "\n")


@contextlib.contextmanager
def session_lock(workspace: Path) -> Iterator[None]:
    root = root_path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".autopilot.lock"
    handle = path.open("a+b")
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    acquired = False
    try:
        while time.monotonic() < deadline:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    if handle.tell() == 0:
                        handle.write(b"0")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (BlockingIOError, OSError):
                time.sleep(0.05)
        if not acquired:
            raise AutopilotError("SESSION_BUSY", "会话正在被另一个请求更新，请稍后重试。")
        yield
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def validate_idempotency_key(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise AutopilotError("IDEMPOTENCY_KEY_INVALID", "idempotency_key 必须是 UUID。") from exc
    return str(parsed)


def idempotency_path(workspace: Path) -> Path:
    return root_path(workspace) / "idempotency.json"


def cached_result(workspace: Path, key: str) -> dict[str, Any] | None:
    path = idempotency_path(workspace)
    if not path.exists():
        return None
    cache = load_object(path, "idempotency cache")
    for item in cache.get("items", []):
        if item.get("key") == key and isinstance(item.get("result"), dict):
            return item["result"]
    return None


def store_result(workspace: Path, key: str, result: dict[str, Any]) -> None:
    path = idempotency_path(workspace)
    cache = load_object(path, "idempotency cache") if path.exists() else {"version": VERSION, "items": []}
    items = [item for item in cache.get("items", []) if item.get("key") != key]
    items.append({"key": key, "at": now_iso(), "result": result})
    cache["items"] = items[-MAX_IDEMPOTENCY_RESULTS:]
    atomic_write_json(path, cache)


def check_state_version(state: dict[str, Any], expected: int) -> None:
    if not isinstance(expected, int) or expected != state.get("state_version"):
        raise AutopilotError(
            "STALE_SESSION", "会话版本已变化，请重新调用 autopilot_status。",
            {"expected": state.get("state_version"), "received": expected},
        )


def capsule_preference_values(identity_key: str) -> dict[str, str]:
    digest = hashlib.sha256(("lab-factory-writer-capsule\n" + identity_key).encode("utf-8")).digest()
    selectable = {
        "detail_level": ["concise", "balanced", "detailed"],
        "sentence_paragraph_style": ["short", "mixed", "long"],
        "terminology_density": ["low", "medium", "high"],
        "voice_tone": ["plain", "formal", "technical", "personal"],
        "analysis_order": ["principle_first", "procedure_first", "result_first"],
        "reflection_depth": ["learning_process", "problem_solving", "engineering", "critical_improvement"],
        "variation_strength": ["medium", "high"],
    }
    values = {"writing_level": "natural_undergrad"}
    for index, (key, choices) in enumerate(selectable.items(), start=1):
        values[key] = choices[digest[index] % len(choices)]
    return values


def default_preferences(subject: str, identity_key: str) -> dict[str, Any]:
    values = capsule_preference_values(identity_key)
    return {
        "version": VERSION,
        "subject": subject,
        "status": "provisional",
        "values": values,
        "sources": {key: "system_assigned_capsule" for key in PREFERENCE_SCHEMA},
        "answered": list(PREFERENCE_SCHEMA),
        "updated_at": now_iso(),
    }


def forbidden_profile_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"sample_text", "full_text", "report_body", "source_paths", "student_name", "student_id"}:
                return key
            found = forbidden_profile_key(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = forbidden_profile_key(child)
            if found:
                return found
    return None


def validate_personal_profile(profile: dict[str, Any]) -> None:
    if profile.get("version") != "1.0" or profile.get("kind") != "personal_writing_profile":
        raise AutopilotError("PERSONAL_PROFILE_INVALID", "旧报告画像版本或类型不受支持。")
    forbidden = forbidden_profile_key(profile)
    if forbidden:
        raise AutopilotError("PERSONAL_PROFILE_PRIVATE_CONTENT", f"旧报告画像不得保存 {forbidden}。")
    sample_summary = profile.get("sample_summary")
    if not isinstance(sample_summary, dict) or not isinstance(sample_summary.get("sample_ids"), list):
        raise AutopilotError("PERSONAL_PROFILE_INVALID", "旧报告画像缺少脱敏样本摘要。")
    if not isinstance(profile.get("features"), dict):
        raise AutopilotError("PERSONAL_PROFILE_INVALID", "旧报告画像缺少可解释写作特征。")
    if not isinstance(profile.get("humanization_preferences"), dict) or not isinstance(profile.get("excluded_patterns"), list):
        raise AutopilotError("PERSONAL_PROFILE_INVALID", "旧报告画像缺少去模板腔偏好或排除模式。")
    privacy = profile.get("privacy") if isinstance(profile.get("privacy"), dict) else {}
    required_privacy = {
        "stores_report_body": False,
        "stores_source_paths": False,
        "stores_personal_identifiers": False,
        "local_analysis_only": True,
    }
    if any(privacy.get(key) is not value for key, value in required_privacy.items()):
        raise AutopilotError(
            "PERSONAL_PROFILE_PRIVATE_CONTENT",
            "旧报告画像必须明确仅本地分析，且不保存正文、源路径和个人标识。",
        )
    recommended = profile.get("recommended_preferences")
    if not isinstance(recommended, dict):
        raise AutopilotError("PERSONAL_PROFILE_INVALID", "旧报告画像缺少 recommended_preferences。")
    for key, spec in PREFERENCE_SCHEMA.items():
        if recommended.get(key) not in spec["values"]:
            raise AutopilotError("PERSONAL_PROFILE_INVALID", f"旧报告画像中的 {key} 不合法。")


def preferences_from_profile(
    subject: str,
    profile: dict[str, Any] | None,
    personal_profile: dict[str, Any] | None,
    identity_key: str,
) -> dict[str, Any]:
    result = default_preferences(subject, identity_key)
    if personal_profile:
        validate_personal_profile(personal_profile)
        recommended = personal_profile["recommended_preferences"]
        result["values"] = {key: recommended[key] for key in PREFERENCE_SCHEMA}
        result["sources"] = {key: "prior_report_profile" for key in PREFERENCE_SCHEMA}
        result["answered"] = list(PREFERENCE_SCHEMA)
        confidence = personal_profile.get("confidence", {}).get("level", "low")
        result["status"] = "accepted" if confidence in {"medium", "high"} else "provisional"
        result["personal_profile_confidence"] = confidence
        return result
    if not profile:
        return result
    dimensions = profile.get("dimensions") if isinstance(profile.get("dimensions"), dict) else {}
    if profile.get("version") == VERSION:
        source_values = profile.get("values") if isinstance(profile.get("values"), dict) else dimensions
        for key, spec in PREFERENCE_SCHEMA.items():
            value = source_values.get(key)
            if value in spec["values"]:
                result["values"][key] = value
                result["sources"][key] = "accepted_user_profile"
                result["answered"].append(key)
    else:
        mapping = {
            "writing_level": ("level", LEGACY_PROFILE_MAP["level"]),
            "detail_level": ("detail", LEGACY_PROFILE_MAP["detail"]),
            "voice_tone": ("tone", LEGACY_PROFILE_MAP["tone"]),
            "reflection_depth": ("reflection", LEGACY_PROFILE_MAP["reflection"]),
        }
        for target, (legacy, values) in mapping.items():
            mapped = values.get(dimensions.get(legacy))
            if mapped:
                result["values"][target] = mapped
                result["sources"][target] = "legacy_profile_inference"
                result["answered"].append(target)
    if len(result["answered"]) == len(PREFERENCE_SCHEMA) and profile.get("status") == "accepted":
        result["status"] = "accepted"
    return result


def format_summary(requirements: dict[str, Any], template_profile: dict[str, Any]) -> dict[str, Any]:
    supplied = requirements.get("formatting") if isinstance(requirements.get("formatting"), dict) else {}
    fields = template_profile.get("fields") if isinstance(template_profile.get("fields"), list) else []
    locators = [item.get("locator", {}) for item in fields if isinstance(item, dict)]
    template_styles = sorted({item.get("style_id") for item in locators if item.get("style_id")})
    has_numbering = any((item.get("numbering") or {}).get("num_id") for item in locators)

    def item(key: str, fallback: Any, source: str = "built_in_default", confidence: float = 0.6,
             supported: bool = True) -> dict[str, Any]:
        if key in supplied and supplied[key] not in (None, "", [], {}):
            return {"value": supplied[key], "source": "task", "confidence": 1.0, "supported": supported}
        return {"value": fallback, "source": source, "confidence": confidence, "supported": supported}

    values = {
        "body_font": item("body_font", "宋体"),
        "body_size": item("body_size", "小四（12pt）"),
        "body_color": item("body_color", "黑色"),
        "heading_styles": item(
            "heading_styles", template_styles or "沿用模板同级标题样式",
            "template" if template_styles else "built_in_default", 0.95 if template_styles else 0.6,
        ),
        "alignment": item("alignment", "正文两端对齐，标题沿用模板"),
        "first_line_indent": item("first_line_indent", "2 字符"),
        "line_spacing": item("line_spacing", "1.5 倍"),
        "paragraph_spacing": item("paragraph_spacing", "段前 0，段后 0"),
        "numbering": item(
            "numbering", "沿用模板编号" if has_numbering else "无明确模板编号时使用层级标题",
            "template" if has_numbering else "built_in_default", 0.95 if has_numbering else 0.6,
        ),
        "table_style": item("table_style", "沿用目标单元格和模板表格样式", "template", 0.9),
        "header_footer": item("header_footer", "保留模板页眉页脚，不自动改写", "template", 0.95),
        "image_relationships": item("image_relationships", "保留原关系；新增图片由宿主提供受控产物", "template", 0.9),
        "manual_or_unsupported": {
            "value": ["主题字体", "复杂域", "修订", "文本框", "公式", "跨节编号", "WPS 专有差异"],
            "source": "engine_capability", "confidence": 1.0, "supported": False,
        },
    }
    return {"version": VERSION, "items": values, "disclosure_complete": True, "updated_at": now_iso()}


def build_writer_genome(
    subject: str,
    preferences: dict[str, Any],
    identity_key: str,
    personal_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    base_digest = hashlib.sha256(("writer-genome\n" + identity_key).encode("utf-8")).digest()
    course_digest = hashlib.sha256((identity_key + "\n" + subject).encode("utf-8")).digest()
    axes = {
        key: choices[base_digest[index] % len(choices)]
        for index, (key, choices) in enumerate(GENOME_AXES.items())
    }
    provenance = "system_assigned"
    confidence = "medium"
    if personal_profile:
        provenance = "prior_report_profile"
        confidence = str(personal_profile.get("confidence", {}).get("level", "low"))
        features = personal_profile.get("features") if isinstance(personal_profile.get("features"), dict) else {}
        feature_overrides = {
            "sentence_rhythm": features.get("sentence_rhythm"),
            "terminology_handling": features.get("terminology_handling"),
            "person_voice": features.get("person_voice"),
            "reflection_signature": features.get("reflection_pattern"),
            "connector_density": features.get("connector_density"),
            "list_usage": features.get("list_preference"),
        }
        axes.update({key: str(value) for key, value in feature_overrides.items() if value})
    elif any(source == "accepted_user_profile" for source in preferences.get("sources", {}).values()):
        provenance = "accepted_user_profile"
        confidence = "high"

    order_map = {
        "principle_first": "principle_to_operation",
        "procedure_first": "operation_to_result",
        "result_first": "result_to_explanation",
    }
    reflection_map = {
        "learning_process": "concept_understanding",
        "problem_solving": "debugging_process",
        "engineering": "implementation_tradeoff",
        "critical_improvement": "limitation_and_improvement",
    }
    axes["reasoning_route"] = order_map[preferences["values"]["analysis_order"]]
    axes["reflection_signature"] = reflection_map[preferences["values"]["reflection_depth"]]
    capsule_id = "wc_" + hashlib.sha256((identity_key + "\nbase").encode("utf-8")).hexdigest()[:16]
    return {
        "version": WRITER_GENOME_VERSION,
        "capsule_id": capsule_id,
        "provenance": {"base": provenance, "confidence": confidence, "user_adjustable": True},
        "student_capability": {
            "level": preferences["values"]["writing_level"],
            "professional_boundary": "术语和方法保持专业，但不冒充教师、研究者或行业专家",
            "evidence_boundary": "第一人称操作、观察、问题和结论必须来自真实材料、运行结果或用户确认",
        },
        "stable_axes": axes,
        "course_overlay": {
            "subject_key": hashlib.sha256(subject.encode("utf-8")).hexdigest()[:12],
            "term_density_adjustment": ["preserve", "slightly_lower", "slightly_higher"][course_digest[0] % 3],
            "analysis_depth_adjustment": ["preserve", "example_led", "constraint_led"][course_digest[1] % 3],
        },
        "invariants": [
            "task_facts", "course_terms", "real_evidence", "target_nodes", "heading_structure",
            "template_fixed_content", "writer_capsule",
        ],
        "prohibited_strategies": [
            "random_synonym_substitution", "demographic_or_dialect_imitation", "fabricated_personal_experience",
            "deliberate_grammar_errors", "invented_uncertainty", "expert_impersonation", "ai_detector_evasion",
        ],
        "privacy": {"stores_identity_key": False, "stores_report_body": False, "stores_sample_body": False},
    }


def apply_preferences_to_genome(writer_genome: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any]:
    updated = json.loads(json.dumps(writer_genome, ensure_ascii=False))
    values = preferences["values"]
    updated["student_capability"]["level"] = values["writing_level"]
    updated["stable_axes"]["reasoning_route"] = {
        "principle_first": "principle_to_operation",
        "procedure_first": "operation_to_result",
        "result_first": "result_to_explanation",
    }[values["analysis_order"]]
    updated["stable_axes"]["reflection_signature"] = {
        "learning_process": "concept_understanding",
        "problem_solving": "debugging_process",
        "engineering": "implementation_tradeoff",
        "critical_improvement": "limitation_and_improvement",
    }[values["reflection_depth"]]
    return updated


def variation_contract(
    preferences: dict[str, Any], variation_seed: str, writer_genome: dict[str, Any]
) -> dict[str, Any]:
    values = preferences["values"]
    digest = hashlib.sha256((variation_seed + sha256_json(values)).encode("utf-8")).digest()
    emphasis_by_reflection = {
        "learning_process": "learning_progress", "problem_solving": "problem_and_resolution",
        "engineering": "engineering_tradeoffs", "critical_improvement": "limitations_and_improvements",
    }
    order = values["analysis_order"]
    density = {"concise": "low", "balanced": "medium", "detailed": "high"}[values["detail_level"]]
    strength = values["variation_strength"]
    stable = writer_genome["stable_axes"]
    layout_archetype = LAYOUT_ARCHETYPES[digest[2] % len(LAYOUT_ARCHETYPES)]
    layout_rule = LAYOUT_ARCHETYPE_RULES[layout_archetype]
    choices = {
        "section_emphasis": emphasis_by_reflection[values["reflection_depth"]],
        "explanation_order": order,
        "evidence_example_density": density,
        "reflection_angle": values["reflection_depth"],
        "secondary_emphasis": ["method_constraints", "result_interpretation", "implementation_decisions"][digest[0] % 3],
        "opening_mode": stable["reasoning_route"],
        "explanation_shape": stable["explanation_shape"],
        "paragraph_progression": stable["paragraph_movement"],
        "sentence_rhythm": stable["sentence_rhythm"],
        "term_introduction": stable["terminology_handling"],
        "evidence_habit": stable["evidence_habit"],
        "first_person_policy": stable["person_voice"],
        "uncertainty_expression": stable["uncertainty_style"],
        "connector_density": stable["connector_density"],
        "list_pattern": stable["list_usage"],
        "closure_mode": [stable["reflection_signature"], "specific_limit", "verified_takeaway"][digest[1] % 3],
        "revision_focus": stable["revision_focus"],
        "layout_archetype": layout_archetype,
        "opening_flow": layout_rule["opening_flow"],
        "visual_density": layout_rule["visual_density"],
        "table_role": layout_rule["table_role"],
        "problem_evidence_position": ["after_problem", "between_problem_and_solution", "after_solution"][digest[3] % 3],
        "summary_shape": ["paired_problem_solution", "process_reflection", "compact_issue_matrix", "narrative_with_takeaways"][digest[4] % 4],
    }
    return {
        "version": WRITER_GENOME_VERSION, "variation_seed": variation_seed, "strength": strength,
        "writer_capsule_id": writer_genome["capsule_id"],
        "observable_axes": choices,
        "invariants": writer_genome["invariants"],
        "forbidden_strategy": "random_synonym_substitution",
    }


def generation_contract(object_ids: dict[str, str]) -> dict[str, Any]:
    return {
        "version": WRITER_GENOME_VERSION,
        "object_refs": {
            "preferences": object_ids["preferences"],
            "writer_genome": object_ids["writer_genome"],
            "variation_contract": object_ids["variation_contract"],
            "style_card": object_ids.get("style_card") or None,
            "personal_writing_profile": object_ids.get("personal_profile") or None,
        },
        "pipeline": ["fact_ledger", "discourse_plan", "draft", "identity_humanization", "deterministic_gates"],
        "student_identity": {
            "professional_not_expert": True,
            "first_person_requires_evidence": True,
            "uncertainty_requires_reason": True,
            "no_deliberate_errors": True,
        },
        "humanization_policy": {
            "mode": "identity_conditioned",
            "preserve": ["course_terms", "verified_facts", "citations", "code", "formulas", "writer_genome_axes"],
            "remove_clusters": [
                "significance_inflation", "promotional_language", "vague_attribution", "negative_parallelism",
                "formulaic_connectors", "generic_conclusion", "chatbot_trace", "empty_emphasis",
            ],
            "domain_exemptions": ["required_template_headings", "technical_passive_voice", "fixed_course_phrases"],
            "no_new_facts": True,
        },
        "layout_policy": {
            "template_boundary": "preserve_fixed_template_regions_but_vary_flow_inside_writable_regions",
            "archetype_source": "variation_contract.observable_axes.layout_archetype",
            "plan_before_prose": True,
            "required_form_factors": [
                "prose", "numbered_figure_placeholder_when_visual_evidence_is_expected",
                "table_when_row_column_data_exists",
            ],
            "single_asset_per_placeholder": True,
            "avoid_fixed_three_three_three_summary": True,
            "table_gate": "use_tables_for_repeated_comparable_records_and_reserve_a_numbered_table_placeholder_when_real_data_is_pending",
        },
        "caption_reference_policy": {
            "independent_sequences": ["figure", "table"],
            "numbering": "chapter_or_section_aware",
            "placeholder_format": "【图 2-1：名称；待补：具体截图或绘图要求】 or 【表 2-1：名称；待补：字段或数据来源】",
            "caption_known_before_insertion": True,
            "prose_cross_reference_required": True,
            "forbid_multi_asset_placeholder": True,
        },
        "problem_evidence_policy": {
            "reserve_when_helpful": ["error_message", "unexpected_output", "configuration_state", "before_after_result"],
            "allowed_positions": ["after_problem", "between_problem_and_solution", "after_solution"],
            "requires_number_title_and_cross_reference": True,
            "do_not_fabricate_evidence": True,
        },
        "candidate_policy": {
            "default_count": 1,
            "high_collision_count": 3,
            "rerank_by": [
                "fact_coverage", "writer_genome_adherence", "structural_distance",
                "cross_report_distance", "student_authenticity",
            ],
        },
        "required_quality_gates": sorted(REQUIRED_QUALITY_GATES),
        "privacy": {"report_body_not_uploaded_to_license_service": True, "sample_body_not_persisted": True, "cloud_host_may_receive_selected_materials": True},
    }


def preference_questions(preferences: dict[str, Any]) -> list[dict[str, Any]]:
    answered = set(preferences.get("answered", []))
    questions = []
    for key, spec in PREFERENCE_SCHEMA.items():
        if key in answered:
            continue
        questions.append({
            "id": f"pref_{key}", "scope": "stable_preference", "reason": "missing",
            "source": preferences["sources"].get(key, "built_in_default"), "prompt": spec["prompt"],
            "allowed_values": spec["values"], "default": spec["default"], "blocking": True,
        })
    return questions


def make_preflight_summary(subject: str, preferences: dict[str, Any], formats: dict[str, Any],
                           requirements: dict[str, Any], variation: dict[str, Any],
                           writer_genome: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject": subject,
        "preferences": preferences["values"],
        "preference_sources": preferences["sources"],
        "personalization": {
            "capsule_id": writer_genome["capsule_id"],
            "source": writer_genome["provenance"]["base"],
            "confidence": writer_genome["provenance"]["confidence"],
            "sample_body_stored": False,
            "user_adjustable": True,
        },
        "writer_genome_summary": writer_genome["stable_axes"],
        "format_summary": formats["items"],
        "requirements_status": {
            "missing": requirements.get("missing", []),
            "conflicts": requirements.get("conflicts", []),
        },
        "variation": variation["observable_axes"],
        "humanization": {
            "mode": "identity_conditioned",
            "no_new_facts": True,
            "student_boundary": writer_genome["student_capability"]["professional_boundary"],
            "ai_detector_is_gate": False,
        },
        "routine_checkpoints": ["preflight", "final_review"],
    }


def write_plan(workspace: Path, state: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    plan_id = f"plan-v{state['state_version']}"
    plan["version"] = VERSION
    plan["plan_id"] = plan_id
    plan["session_id"] = state["session_id"]
    plan["state_version"] = state["state_version"]
    plan["mode"] = state["orchestration_mode"]
    if plan.get("next_action") not in NEXT_ACTIONS:
        raise AutopilotError("PLAN_INVALID", "interaction plan 返回了非法 next_action。")
    for question in plan.get("questions", []):
        if question.get("scope") not in QUESTION_SCOPES:
            raise AutopilotError("PLAN_INVALID", "interaction plan 返回了非法 question scope。")
    atomic_write_json(object_path(workspace, plan_id), plan)
    state["object_ids"]["interaction_plan"] = plan_id
    return plan


def current_plan(workspace: Path, state: dict[str, Any]) -> dict[str, Any]:
    object_id = state.get("object_ids", {}).get("interaction_plan")
    if not object_id:
        raise AutopilotError("PLAN_NOT_FOUND", "会话缺少 interaction plan。")
    return load_object(object_path(workspace, object_id), "interaction plan")


def commit_state(workspace: Path, state: dict[str, Any], event: str, previous: str | None = None) -> None:
    state["updated_at"] = now_iso()
    atomic_write_json(state_path(workspace), state)
    append_audit(workspace, {
        "at": now_iso(), "event": event, "from": previous, "to": state.get("orchestration_state"),
        "state_version": state.get("state_version"),
    })


def response(state: dict[str, Any], plan: dict[str, Any], **extra: Any) -> dict[str, Any]:
    value = {"ok": True, "session": state, "interaction_plan": plan, "next_action": plan["next_action"]}
    value.update(extra)
    return value


def prepare(workspace: Path, idempotency_key: str, subject: str, mode: str,
            requirements_path: Path, template_profile_path: Path,
            writing_profile_path: Path | None = None, style_card_path: Path | None = None,
            personal_profile_path: Path | None = None, style_identity: str | None = None) -> dict[str, Any]:
    key = validate_idempotency_key(idempotency_key)
    if mode == "fast":
        raise AutopilotError("MODE_NOT_ENABLED", "fast 模式将在完成 3 次无人协助真实试用后开放。")
    if mode == "strict":
        raise AutopilotError("STRICT_USE_LEGACY_FLOW", "strict 模式由 MCP 层映射到现有 v2.0 状态机。")
    if mode != "balanced":
        raise AutopilotError("MODE_INVALID", "mode 只能是 balanced、strict 或暂未开放的 fast。")
    with session_lock(workspace):
        cached = cached_result(workspace, key)
        if cached:
            return cached
        existing = state_path(workspace)
        if existing.exists():
            old = load_object(existing, "session state")
            if old.get("version") == VERSION:
                raise AutopilotError("SESSION_EXISTS", "自动驾驶会话已经存在，请调用 autopilot_status。")
            raise AutopilotError("LEGACY_SESSION", "旧 v2.0 会话必须继续使用 strict 旧流程。")

        requirements = load_object(requirements_path, "requirements")
        template = load_object(template_profile_path, "template profile")
        profile = load_object(writing_profile_path, "writing profile") if writing_profile_path else None
        style_card = load_object(style_card_path, "style card") if style_card_path else None
        personal_profile = load_object(personal_profile_path, "personal writing profile") if personal_profile_path else None
        if personal_profile:
            validate_personal_profile(personal_profile)
        identity_key = style_identity or sha256_json({"workspace": str(workspace.resolve()), "subject": subject})
        preferences = preferences_from_profile(subject, profile, personal_profile, identity_key)
        formats = format_summary(requirements, template)
        seed = secrets.token_hex(8)
        writer_genome = build_writer_genome(subject, preferences, identity_key, personal_profile)
        variation = variation_contract(preferences, seed, writer_genome)
        questions = preference_questions(preferences)
        requirements_conflicts = requirements.get("conflicts", [])
        requirements_missing = requirements.get("missing", [])
        if requirements_conflicts:
            questions.append({
                "id": "requirements_conflicts", "scope": "task_requirement", "reason": "conflict",
                "source": "task", "prompt": "任务要求存在冲突，请给出最终采用的要求。",
                "allowed_values": [], "default": None, "blocking": True,
            })
        if requirements_missing:
            questions.append({
                "id": "requirements_missing", "scope": "task_requirement", "reason": "missing",
                "source": "task", "prompt": "任务要求存在缺失项，请补充后再生成。",
                "allowed_values": [], "default": None, "blocking": True,
            })
        if style_card:
            preferences["style_card_applied"] = True

        object_ids = {
            "preferences": "preferences-v1", "format_summary": "format-v1",
            "writer_genome": "writer-genome-v3", "variation_contract": "variation-v3",
            "generation_contract": "generation-contract-v3", "interaction_plan": "",
            "requirements": "requirements-v1", "template_profile": "template-profile-v1",
        }
        if style_card:
            object_ids["style_card"] = "style-card-v1"
        if personal_profile:
            object_ids["personal_profile"] = "personal-profile-v1"
        atomic_write_json(object_path(workspace, object_ids["requirements"]), requirements)
        atomic_write_json(object_path(workspace, object_ids["template_profile"]), template)
        host_contract = generation_contract(object_ids)
        state = {
            "version": VERSION, "session_id": "s_" + uuid.uuid4().hex[:16],
            "report_id": "report_" + uuid.UUID(key).hex, "subject": subject,
            "state_version": 1, "state": "materials_scanned",
            "orchestration_state": "collecting_preferences" if questions else "preflight_pending",
            "orchestration_mode": mode, "current_checkpoint": None if questions else "preflight",
            "profile_status": preferences["status"], "repair_attempts": 0,
            "variation_seed": seed, "style_capsule_id": writer_genome["capsule_id"], "object_ids": object_ids,
            "active_confirmation": None, "created_at": now_iso(), "updated_at": now_iso(),
        }
        atomic_write_json(object_path(workspace, object_ids["preferences"]), preferences)
        atomic_write_json(object_path(workspace, object_ids["format_summary"]), formats)
        atomic_write_json(object_path(workspace, object_ids["writer_genome"]), writer_genome)
        atomic_write_json(object_path(workspace, object_ids["variation_contract"]), variation)
        atomic_write_json(object_path(workspace, object_ids["generation_contract"]), host_contract)
        if style_card:
            atomic_write_json(object_path(workspace, object_ids["style_card"]), style_card)
        if personal_profile:
            atomic_write_json(object_path(workspace, object_ids["personal_profile"]), personal_profile)
        preflight = make_preflight_summary(subject, preferences, formats, requirements, variation, writer_genome)
        if questions:
            plan = {"questions": questions, "checkpoint": None, "exceptions": [],
                    "next_action": "ask_user", "reason_code": "PREFERENCES_INCOMPLETE",
                    "format_disclosure": formats["items"]}
        else:
            summary_hash = sha256_json(preflight)
            plan = {"questions": [], "checkpoint": {"id": "preflight", "required": True,
                    "summary_sha256": summary_hash, "summary": preflight}, "exceptions": [],
                    "next_action": "deliver_preview", "reason_code": "PREFLIGHT_READY",
                    "format_disclosure": formats["items"]}
        plan = write_plan(workspace, state, plan)
        commit_state(workspace, state, "autopilot_prepared")
        result = response(state, plan)
        store_result(workspace, key, result)
        return result


def answer_questions(workspace: Path, state_version: int, idempotency_key: str,
                     plan_id: str, answers: list[dict[str, Any]]) -> dict[str, Any]:
    key = validate_idempotency_key(idempotency_key)
    with session_lock(workspace):
        cached = cached_result(workspace, key)
        if cached:
            return cached
        state = read_state(workspace)
        check_state_version(state, state_version)
        if state["orchestration_state"] not in {"collecting_preferences", "exception_pending"}:
            raise AutopilotError("INVALID_TRANSITION", "当前状态不能回答问题。")
        plan = current_plan(workspace, state)
        if plan_id != plan.get("plan_id"):
            raise AutopilotError("STALE_PLAN", "plan_id 已过期，请重新读取状态。")
        if not isinstance(answers, list):
            raise AutopilotError("INVALID_ANSWER", "answers 必须是数组。")
        by_id = {item.get("id"): item for item in plan.get("questions", [])}
        if not by_id:
            raise AutopilotError("INVALID_ANSWER", "当前 interaction plan 没有待回答问题。")
        preferences = load_object(object_path(workspace, state["object_ids"]["preferences"]), "preferences")
        seen: set[str] = set()
        for answer in answers:
            if not isinstance(answer, dict) or answer.get("question_id") not in by_id:
                raise AutopilotError("INVALID_ANSWER", "answers 包含未知 question_id。")
            question_id = answer["question_id"]
            if question_id in seen:
                raise AutopilotError("INVALID_ANSWER", f"问题 {question_id} 被重复回答。")
            seen.add(question_id)
            question = by_id[question_id]
            value = answer.get("value")
            allowed = question.get("allowed_values", [])
            if allowed and value not in allowed:
                raise AutopilotError("INVALID_ANSWER", f"{question_id} 的答案不在允许范围内。")
            if question_id.startswith("pref_"):
                dimension = question_id.removeprefix("pref_")
                preferences["values"][dimension] = value
                preferences["sources"][dimension] = "current_user"
                if dimension not in preferences["answered"]:
                    preferences["answered"].append(dimension)
        unanswered = [item for item in plan.get("questions", []) if item.get("blocking") and item.get("id") not in seen]
        if unanswered:
            raise AutopilotError(
                "INVALID_ANSWER", "必须一次回答当前所有阻断问题。",
                {"unanswered_question_ids": [item["id"] for item in unanswered]},
            )
        preferences["updated_at"] = now_iso()
        atomic_write_json(object_path(workspace, state["object_ids"]["preferences"]), preferences)
        writer_genome = load_object(object_path(workspace, state["object_ids"]["writer_genome"]), "writer genome")
        writer_genome = apply_preferences_to_genome(writer_genome, preferences)
        atomic_write_json(object_path(workspace, state["object_ids"]["writer_genome"]), writer_genome)
        variation = variation_contract(preferences, state["variation_seed"], writer_genome)
        atomic_write_json(object_path(workspace, state["object_ids"]["variation_contract"]), variation)
        atomic_write_json(
            object_path(workspace, state["object_ids"]["generation_contract"]), generation_contract(state["object_ids"])
        )
        previous = state["orchestration_state"]
        if previous == "exception_pending":
            selected = {item["question_id"]: item.get("value") for item in answers}
            if "style_calibration" in selected:
                state["style_calibration"] = {"completed": True, "selected_sample_id": selected["style_calibration"]}
            if any(value == "cancel" for value in selected.values()):
                state["state_version"] += 1
                state["orchestration_state"] = "cancelled"
                plan = write_plan(workspace, state, {
                    "questions": [], "checkpoint": None, "exceptions": [],
                    "next_action": "done", "reason_code": "CANCELLED",
                })
            else:
                state["state_version"] += 1
                state["orchestration_state"] = "running"
                plan = write_plan(workspace, state, {
                    "questions": [], "checkpoint": None, "exceptions": [],
                    "next_action": "auto_advance", "reason_code": "EXCEPTION_RESOLVED",
                })
            commit_state(workspace, state, "exception_answered", previous)
            result = response(state, plan)
            store_result(workspace, key, result)
            return result

        formats = load_object(object_path(workspace, state["object_ids"]["format_summary"]), "format summary")
        preflight = make_preflight_summary(state["subject"], preferences, formats, {}, variation, writer_genome)
        state["state_version"] += 1
        state["orchestration_state"] = "preflight_pending"
        state["current_checkpoint"] = "preflight"
        summary_hash = sha256_json(preflight)
        plan = write_plan(workspace, state, {
            "questions": [], "checkpoint": {"id": "preflight", "required": True,
            "summary_sha256": summary_hash, "summary": preflight}, "exceptions": [],
            "next_action": "deliver_preview", "reason_code": "PREFLIGHT_READY",
            "format_disclosure": formats["items"],
        })
        commit_state(workspace, state, "questions_answered", previous)
        result = response(state, plan)
        store_result(workspace, key, result)
        return result


def confirm_checkpoint(workspace: Path, state_version: int, idempotency_key: str,
                       checkpoint_id: str, summary_sha256: str) -> dict[str, Any]:
    key = validate_idempotency_key(idempotency_key)
    with session_lock(workspace):
        cached = cached_result(workspace, key)
        if cached:
            return cached
        state = read_state(workspace)
        check_state_version(state, state_version)
        plan = current_plan(workspace, state)
        checkpoint = plan.get("checkpoint") or {}
        if checkpoint.get("id") != checkpoint_id or checkpoint.get("summary_sha256") != summary_sha256:
            raise AutopilotError("CHECKPOINT_MISMATCH", "checkpoint 或摘要哈希已变化，请重新展示最新摘要。")
        if checkpoint_id == "preflight" and state["orchestration_state"] != "preflight_pending":
            raise AutopilotError("INVALID_TRANSITION", "当前状态不能确认 preflight。")
        if checkpoint_id == "final_review" and state["orchestration_state"] != "final_review_pending":
            raise AutopilotError("INVALID_TRANSITION", "当前状态不能确认 final review。")
        if checkpoint_id == "final_review":
            summary = checkpoint["summary"]
            try: artifact_store.verify(workspace, summary["artifact_id"], summary["sha256"], require_audit=True)
            except artifact_store.ArtifactError as exc: raise AutopilotError("ARTIFACT_CHANGED", str(exc)) from exc
        token = secrets.token_urlsafe(32)
        state["state_version"] += 1
        state["active_confirmation"] = {
            "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
            "checkpoint_id": checkpoint_id, "summary_sha256": summary_sha256,
            "state_version": state["state_version"],
        }
        plan["state_version"] = state["state_version"]
        atomic_write_json(object_path(workspace, state["object_ids"]["interaction_plan"]), plan)
        commit_state(workspace, state, "checkpoint_confirmed")
        result = response(state, plan, confirmation_token=token)
        store_result(workspace, key, result)
        return result


def consume_confirmation(state: dict[str, Any], token: str | None, checkpoint_id: str) -> None:
    active = state.get("active_confirmation")
    if not active or not token:
        raise AutopilotError("CONFIRMATION_REQUIRED", f"{checkpoint_id} 需要有效确认 token。")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if (digest != active.get("token_sha256") or active.get("checkpoint_id") != checkpoint_id
            or active.get("state_version") != state.get("state_version")):
        raise AutopilotError("CONFIRMATION_REQUIRED", "确认 token 无效、已消费或已过期。")
    state["active_confirmation"] = None


def placement_exception(artifacts: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    placement = artifacts.get("placement")
    if not isinstance(placement, dict):
        return None
    if placement.get("blocked") or placement.get("unsupported") or placement.get("container_conflict"):
        return "blocked", {
            "id": "placement_blocked", "scope": "placement_choice", "severity": "hard",
            "reason": "定位被阻断、容器冲突或目标不受支持。",
        }
    score = placement.get("score")
    margin = placement.get("margin")
    if isinstance(score, (int, float)) and (score < 0.65):
        return "blocked", {"id": "placement_low_confidence", "scope": "placement_choice", "severity": "hard", "reason": "定位分数低于 0.65。"}
    if isinstance(score, (int, float)) and (score < 0.90 or not isinstance(margin, (int, float)) or margin < 0.15):
        return "ask_user", {"id": "placement_confirmation", "scope": "placement_choice", "severity": "confirm", "reason": "定位分数或领先幅度不足以自动采用。"}
    return None


def host_artifact_plan(state: dict[str, Any], reason_code: str = "CONTENT_PACKAGE_REQUIRED") -> dict[str, Any]:
    return {
        "questions": [],
        "checkpoint": None,
        "exceptions": [],
        "next_action": "await_host_artifact",
        "reason_code": reason_code,
        "required_artifacts": [
            "placement", "content_package_ready", "draft",
        ],
        "required_object_ids": {
            key: state["object_ids"][key]
            for key in ("preferences", "writer_genome", "variation_contract", "generation_contract", "requirements", "template_profile") if key in state["object_ids"]
        },
        "host_generation_sequence": [
            "read_required_objects", "build_fact_ledger", "plan_layout_and_caption_registry",
            "plan_before_prose", "draft", "identity_conditioned_humanization",
            "lab_factory_v3_import_asset_when_needed", "lab_factory_v3_apply_draft",
            "lab_factory_v3_verify_draft", "submit_returned_draft_receipt",
        ],
    }


def validated_quality_gates(artifacts: dict[str, Any], workspace: Path | None = None) -> dict[str, Any] | None:
    draft = artifacts.get("draft")
    gates = artifacts.get("quality_gates")
    if not isinstance(draft, dict):
        return gates if isinstance(gates, dict) else None
    try:
        if workspace is None: raise artifact_store.ArtifactError("缺少本地工作区")
        record = artifact_store.verify(workspace, draft.get("object_id"), draft.get("sha256"), require_audit=True)
        return {"status": "pass", "local_audit": record["audit"]}
    except (artifact_store.ArtifactError, KeyError, TypeError) as exc:
        return {"status": "retryable_failure", "reason": str(exc)}


def advance(workspace: Path, state_version: int, idempotency_key: str,
            confirmation_token: str | None, artifacts: dict[str, Any]) -> dict[str, Any]:
    key = validate_idempotency_key(idempotency_key)
    if not isinstance(artifacts, dict):
        raise AutopilotError("ARTIFACT_INVALID", "artifacts 必须是对象。")
    with session_lock(workspace):
        cached = cached_result(workspace, key)
        if cached:
            return cached
        state = read_state(workspace)
        check_state_version(state, state_version)
        previous = state["orchestration_state"]
        if previous in TERMINAL_STATES:
            raise AutopilotError("INVALID_TRANSITION", "终态会话不能继续推进。")

        if previous == "preflight_pending":
            consume_confirmation(state, confirmation_token, "preflight")
            preferences = load_object(object_path(workspace, state["object_ids"]["preferences"]), "preferences")
            preferences["status"] = "accepted"
            preferences["updated_at"] = now_iso()
            atomic_write_json(object_path(workspace, state["object_ids"]["preferences"]), preferences)
            state["profile_status"] = "accepted"
            state["orchestration_state"] = "running"
            state["current_checkpoint"] = None
            state["state"] = "requirements_confirmed"
            plan_data = host_artifact_plan(state)
        elif previous == "running":
            style_calibration = artifacts.get("style_calibration")
            style_confidence = style_calibration.get("confidence") if isinstance(style_calibration, dict) else None
            sample_ids = style_calibration.get("sample_ids") if isinstance(style_calibration, dict) else None
            if (
                isinstance(style_confidence, (int, float)) and style_confidence < 0.65
                and not state.get("style_calibration", {}).get("completed")
            ):
                if not isinstance(sample_ids, list) or len(sample_ids) != 2 or not all(isinstance(item, str) and item for item in sample_ids):
                    raise AutopilotError("ARTIFACT_INVALID", "低风格置信度时必须提供两个不含正文的 sample_ids。")
                state["orchestration_state"] = "exception_pending"
                question = {
                    "id": "style_calibration", "scope": "stable_preference", "reason": "low_confidence",
                    "source": "generated_comparison", "prompt": "下面两个短样例中，哪一个更像你希望的写法？",
                    "allowed_values": sample_ids, "default": sample_ids[0], "blocking": True,
                }
                plan_data = {"questions": [question], "checkpoint": None,
                             "exceptions": [{"id": "style_confidence_low", "severity": "confirm"}],
                             "next_action": "ask_user", "reason_code": "STYLE_CALIBRATION_REQUIRED",
                             "required_host_display": "two_short_style_samples"}
            elif artifacts.get("section_change_required"):
                state["orchestration_state"] = "exception_pending"
                question = {
                    "id": "confirm_section_change", "scope": "section_change", "reason": "structure_change",
                    "source": "task", "prompt": "报告需要新增、删除或移动标题，请确认结构差异。",
                    "allowed_values": ["approve", "revise", "cancel"], "default": "revise", "blocking": True,
                }
                plan_data = {"questions": [question], "checkpoint": None, "exceptions": [question],
                             "next_action": "ask_user", "reason_code": "SECTION_CHANGE_CONFIRMATION"}
            else:
                exception = placement_exception(artifacts)
                if exception:
                    action, detail = exception
                    state["orchestration_state"] = "exception_pending"
                    if action == "ask_user":
                        question = {
                            "id": detail["id"], "scope": "placement_choice", "reason": "low_confidence",
                            "source": "template", "prompt": detail["reason"],
                            "allowed_values": ["approve_candidate", "choose_another", "cancel"],
                            "default": "choose_another", "blocking": True,
                        }
                        plan_data = {"questions": [question], "checkpoint": None, "exceptions": [detail],
                                     "next_action": "ask_user", "reason_code": "PLACEMENT_CONFIRMATION"}
                    else:
                        plan_data = {"questions": [], "checkpoint": None, "exceptions": [detail],
                                     "next_action": "blocked", "reason_code": "PLACEMENT_BLOCKED"}
                else:
                    gates = validated_quality_gates(artifacts, workspace)
                    if isinstance(gates, dict) and gates.get("status") == "retryable_failure":
                        state["repair_attempts"] += 1
                        if state["repair_attempts"] <= 2:
                            plan_data = host_artifact_plan(state, "CONTENT_REPAIR_REQUIRED")
                            plan_data.update({
                                "repair_attempt": state["repair_attempts"],
                                "repair_reason": gates.get("reason"),
                                "repair_invariants": [
                                    "facts", "target_nodes", "heading_structure", "variation_seed", "writer_capsule_id"
                                ],
                            })
                        else:
                            state["orchestration_state"] = "exception_pending"
                            question = {
                                "id": "content_gate_unresolved", "scope": "task_requirement", "reason": "repair_exhausted",
                                "source": "quality_gate", "prompt": "内容自动修复两次仍未通过，请调整要求或材料。",
                                "allowed_values": [], "default": None, "blocking": True,
                            }
                            plan_data = {"questions": [question], "checkpoint": None, "exceptions": [question],
                                         "next_action": "ask_user", "reason_code": "REPAIR_EXHAUSTED"}
                    elif isinstance(gates, dict) and gates.get("status") == "hard_failure":
                        state["orchestration_state"] = "exception_pending"
                        plan_data = {"questions": [], "checkpoint": None,
                                     "exceptions": [{"id": "hard_gate_failure", "severity": "hard", "reason": gates.get("reason", "硬安全门禁失败")}],
                                     "next_action": "blocked", "reason_code": "GATE_BLOCKED"}
                    elif isinstance(artifacts.get("draft"), dict) and artifacts["draft"].get("object_id") and artifacts["draft"].get("sha256"):
                        draft = artifacts["draft"]
                        final_summary = {
                            "artifact_id": draft["object_id"], "sha256": draft["sha256"],
                            "writer_capsule_id": state["style_capsule_id"],
                            "humanization_status": gates["local_audit"]["humanization"]["status"],
                            "cross_report_diversity_gate": gates["local_audit"]["diversity"]["gate"],
                            "cross_report_coverage": gates["local_audit"]["diversity"]["coverage"],
                            "assumptions": artifacts.get("assumptions", []),
                            "warnings": artifacts.get("warnings", []),
                            "wps_review_checklist": draft.get("wps_review_checklist", ["写入位置", "分页与行距", "图片和公式位置"]),
                            "format_disclosure_complete": True,
                        }
                        state["orchestration_state"] = "final_review_pending"
                        state["current_checkpoint"] = "final_review"
                        state["state"] = "draft_generated"
                        state["artifact_ids"] = {"final_preview": draft["object_id"]}
                        plan_data = {"questions": [], "checkpoint": {"id": "final_review", "required": True,
                                     "summary_sha256": sha256_json(final_summary), "summary": final_summary},
                                     "exceptions": [], "next_action": "deliver_preview", "reason_code": "FINAL_REVIEW_READY"}
                    else:
                        plan_data = host_artifact_plan(state)
        elif previous == "exception_pending":
            if artifacts.get("action") == "cancel":
                state["orchestration_state"] = "cancelled"
                plan_data = {"questions": [], "checkpoint": None, "exceptions": [],
                             "next_action": "done", "reason_code": "CANCELLED"}
            elif artifacts.get("exception_resolved") is True:
                state["orchestration_state"] = "running"
                plan_data = {"questions": [], "checkpoint": None, "exceptions": [],
                             "next_action": "auto_advance", "reason_code": "EXCEPTION_RESOLVED"}
            else:
                raise AutopilotError("EXCEPTION_UNRESOLVED", "必须提供 exception_resolved=true 或取消会话。")
        elif previous == "final_review_pending":
            consume_confirmation(state, confirmation_token, "final_review")
            action = artifacts.get("action")
            if action == "accept":
                summary = current_plan(workspace, state)["checkpoint"]["summary"]
                try: artifact_store.verify(workspace, summary["artifact_id"], summary["sha256"], require_audit=True)
                except artifact_store.ArtifactError as exc: raise AutopilotError("ARTIFACT_CHANGED", str(exc)) from exc
                state["orchestration_state"] = "finalized"
                state["state"] = "finalized"
                state["current_checkpoint"] = None
                learning = {
                    "preference_object_id": state["object_ids"]["preferences"],
                    "variation_contract_id": state["object_ids"]["variation_contract"],
                    "stores_report_body": False,
                    "choices": ["accept_skill_update", "edit_skill_update", "finish_without_update"],
                }
                plan_data = {"questions": [], "checkpoint": None, "exceptions": [],
                             "next_action": "deliver_preview", "reason_code": "SKILL_LEARNING_REVIEW",
                             "skill_learning_summary": learning}
            elif action == "revise":
                state["orchestration_state"] = "running"
                state["state"] = "content_ready"
                state["current_checkpoint"] = None
                plan_data = {"questions": [], "checkpoint": None, "exceptions": [],
                             "next_action": "await_host_artifact", "reason_code": "REVISION_REQUIRED",
                             "preserve": ["variation_seed", "artifact_ids.final_preview"]}
            elif action == "cancel":
                state["orchestration_state"] = "cancelled"
                plan_data = {"questions": [], "checkpoint": None, "exceptions": [],
                             "next_action": "done", "reason_code": "CANCELLED"}
            else:
                raise AutopilotError("ARTIFACT_INVALID", "final review 的 action 必须是 accept、revise 或 cancel。")
        elif previous == "finalized":
            action = artifacts.get("action")
            if action not in {"accept_skill_update", "finish_without_update"}:
                raise AutopilotError("INVALID_TRANSITION", "finalized 状态需要决定是否接受 Skill 更新。")
            state["orchestration_state"] = "iteration_decided"
            state["state"] = "iteration_decided"
            state["profile_status"] = "accepted" if action == "accept_skill_update" else state["profile_status"]
            plan_data = {"questions": [], "checkpoint": None, "exceptions": [],
                         "next_action": "done", "reason_code": action.upper()}
        else:
            raise AutopilotError("INVALID_TRANSITION", f"无法从 {previous} 推进。")

        state["state_version"] += 1
        plan = write_plan(workspace, state, plan_data)
        commit_state(workspace, state, "autopilot_advanced", previous)
        result = response(state, plan)
        store_result(workspace, key, result)
        return result


def status(workspace: Path) -> dict[str, Any]:
    state = read_state(workspace)
    plan = current_plan(workspace, state)
    return response(state, plan)
