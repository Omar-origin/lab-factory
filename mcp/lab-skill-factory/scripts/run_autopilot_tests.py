#!/usr/bin/env python3
"""Regression tests for Lab Factory v2.1 autopilot orchestration."""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path


HERE = Path(__file__).resolve()
MCP_DIR = HERE.parents[1]
try:
    import autopilot as AUTOPILOT
except ImportError:
    import importlib.util
    MODULE_PATH = MCP_DIR / "autopilot.py"
    SPEC = importlib.util.spec_from_file_location("lab_factory_autopilot", MODULE_PATH)
    assert SPEC and SPEC.loader
    AUTOPILOT = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(AUTOPILOT)


def key() -> str:
    return str(uuid.uuid4())


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare_files(root: Path) -> tuple[Path, Path]:
    requirements = root / "requirements.json"
    profile = root / "template-profile.json"
    write_json(requirements, {
        "version": "2.0", "experiment": {}, "tools": {}, "formatting": {"body_font": "楷体"},
        "evidence": {}, "submission": {}, "writable_regions": [], "protected_regions": [],
        "missing": [], "conflicts": [],
    })
    write_json(profile, {
        "version": "2.0", "profile_id": "tp_test", "family_fingerprint": "f" * 64,
        "fields": [{"id": "body", "locator": {"style_id": "Normal", "numbering": {}, "container": "paragraph", "path": "/w:document/w:body/w:p[1]"}}],
    })
    return requirements, profile


def error_code(function, *args) -> str | None:
    try:
        function(*args)
    except AUTOPILOT.AutopilotError as exc:
        return exc.code
    return None


def quality_evidence() -> dict:
    return {
        "fact_ledger": {"object_id": "fact-ledger-v1", "sha256": "b" * 64, "stores_report_body": False},
        "humanization_audit": {"version": "1.0", "status": "pass"},
        "layout_audit": {
            "version": "1.0",
            "status": "pass",
            "caption_cross_reference_ok": True,
            "single_asset_per_placeholder_ok": True,
            "table_decision_recorded": True,
            "problem_evidence_decision_recorded": True,
            "unresolved_template_cues": [],
            "structure_fingerprint": {
                "eligible": True, "block_count": 12, "flow_signature": ["prose_medium"],
                "counts": {"prose_medium": 1}, "summary_shape": "narrative",
            },
        },
        "diversity_report": {
            "version": "1.0", "gate": "pass",
            "coverage": {
                "status": "baseline_unavailable", "comparison_count": 0,
                "claim_boundary": "no_baseline_so_cross_report_difference_not_proven",
            },
        },
        "quality_gates": {
            "status": "pass",
            "passed_gate_ids": sorted(AUTOPILOT.REQUIRED_QUALITY_GATES),
        },
    }


def run() -> dict:
    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="lab-factory-autopilot-tests-") as temporary:
        root = Path(temporary)
        requirements, profile = prepare_files(root)
        workspace = root / "normal"

        prepared = AUTOPILOT.prepare(
            workspace, key(), "软件工程", "balanced", requirements, profile,
            style_identity="installation-a",
        )
        questions = prepared["interaction_plan"]["questions"]
        results.append({
            "name": "cold-start-assigns-capsule-without-blocking-preference-form",
            "ok": (
                not questions
                and prepared["next_action"] == "deliver_preview"
                and prepared["interaction_plan"]["checkpoint"]["summary"]["personalization"]["source"] == "system_assigned"
            ),
        })
        disclosure = prepared["interaction_plan"]["format_disclosure"]
        results.append({
            "name": "format-defaults-and-sources-disclosed",
            "ok": (
                disclosure["body_font"] == {"value": "楷体", "source": "task", "confidence": 1.0, "supported": True}
                and disclosure["body_size"]["source"] == "built_in_default"
                and disclosure["manual_or_unsupported"]["supported"] is False
            ),
        })
        persisted_text = (workspace / "lab-factory" / "session-state.json").read_text(encoding="utf-8")
        results.append({
            "name": "state-persists-object-ids-not-source-paths",
            "ok": str(requirements) not in persisted_text and str(profile) not in persisted_text and "object_ids" in persisted_text,
        })

        answered = prepared
        preflight = answered["interaction_plan"]["checkpoint"]
        results.append({
            "name": "preflight-is-first-routine-checkpoint",
            "ok": preflight["id"] == "preflight" and answered["next_action"] == "deliver_preview",
        })

        confirm_key = key()
        preflight_confirmed = AUTOPILOT.confirm_checkpoint(
            workspace, answered["session"]["state_version"], confirm_key,
            "preflight", preflight["summary_sha256"],
        )
        repeated_confirmation = AUTOPILOT.confirm_checkpoint(
            workspace, answered["session"]["state_version"], confirm_key,
            "preflight", preflight["summary_sha256"],
        )
        results.append({
            "name": "idempotent-confirmation-replays-token",
            "ok": repeated_confirmation == preflight_confirmed,
        })
        stale_code = error_code(
            AUTOPILOT.advance, workspace, answered["session"]["state_version"], key(),
            preflight_confirmed["confirmation_token"], {},
        )
        results.append({"name": "stale-state-rejected", "ok": stale_code == "STALE_SESSION"})

        running = AUTOPILOT.advance(
            workspace, preflight_confirmed["session"]["state_version"], key(),
            preflight_confirmed["confirmation_token"], {},
        )
        results.append({
            "name": "low-risk-flow-awaits-host-artifacts",
            "ok": running["next_action"] == "await_host_artifact" and running["session"]["orchestration_state"] == "running",
        })
        final_preview = AUTOPILOT.advance(
            workspace, running["session"]["state_version"], key(), None,
            {
                "placement": {"score": 0.96, "margin": 0.22},
                "content_package_ready": True,
                "draft": {"object_id": "docx-final-v1", "sha256": "a" * 64, "wps_review_checklist": ["分页", "行距"]},
                **quality_evidence(),
            },
        )
        final_checkpoint = final_preview["interaction_plan"]["checkpoint"]
        results.append({
            "name": "final-docx-is-second-routine-checkpoint",
            "ok": final_checkpoint["id"] == "final_review" and final_preview["session"]["orchestration_state"] == "final_review_pending",
        })
        final_confirmed = AUTOPILOT.confirm_checkpoint(
            workspace, final_preview["session"]["state_version"], key(),
            "final_review", final_checkpoint["summary_sha256"],
        )
        finalized = AUTOPILOT.advance(
            workspace, final_confirmed["session"]["state_version"], key(),
            final_confirmed["confirmation_token"], {"action": "accept"},
        )
        finished = AUTOPILOT.advance(
            workspace, finalized["session"]["state_version"], key(), None,
            {"action": "finish_without_update"},
        )
        results.append({
            "name": "normal-balanced-flow-has-exactly-two-checkpoints",
            "ok": (
                finished["session"]["orchestration_state"] == "iteration_decided"
                and finished["next_action"] == "done"
            ),
        })
        preferences = json.loads((workspace / "lab-factory" / "objects" / "preferences-v1.json").read_text(encoding="utf-8"))
        variation = json.loads((workspace / "lab-factory" / "objects" / "variation-v3.json").read_text(encoding="utf-8"))
        writer_genome = json.loads((workspace / "lab-factory" / "objects" / "writer-genome-v3.json").read_text(encoding="utf-8"))
        generation_contract = json.loads((workspace / "lab-factory" / "objects" / "generation-contract-v3.json").read_text(encoding="utf-8"))
        results.append({
            "name": "writer-genome-and-generation-contract-control-semantic-and-style-axes",
            "ok": (
                len(preferences["values"]) == 8
                and {
                    "section_emphasis", "explanation_order", "evidence_example_density",
                    "reflection_angle", "secondary_emphasis", "opening_mode", "paragraph_progression",
                    "sentence_rhythm", "first_person_policy", "uncertainty_expression", "revision_focus",
                    "layout_archetype", "opening_flow", "visual_density", "table_role",
                    "problem_evidence_position", "summary_shape",
                }.issubset(variation["observable_axes"])
                and variation["forbidden_strategy"] == "random_synonym_substitution"
                and len(writer_genome["stable_axes"]) == 12
                and set(generation_contract["required_quality_gates"]) == AUTOPILOT.REQUIRED_QUALITY_GATES
                and generation_contract["layout_policy"]["single_asset_per_placeholder"] is True
                and generation_contract["caption_reference_policy"]["prose_cross_reference_required"] is True
            ),
        })

        layout_signatures = []
        for index in range(80):
            layout_variation = AUTOPILOT.variation_contract(
                preferences, f"layout-seed-{index}", writer_genome
            )
            axes = layout_variation["observable_axes"]
            layout_signatures.append((axes["layout_archetype"], axes["summary_shape"], axes["problem_evidence_position"]))
        results.append({
            "name": "per-report-seed-varies-observable-layout-not-only-wording",
            "ok": (
                len({item[0] for item in layout_signatures}) == len(AUTOPILOT.LAYOUT_ARCHETYPES)
                and len({item[1] for item in layout_signatures}) == 4
                and len(set(layout_signatures)) >= 15
            ),
        })

        same_identity_workspace = root / "same-identity"
        same_identity = AUTOPILOT.prepare(
            same_identity_workspace, key(), "计算机网络", "balanced", requirements, profile,
            style_identity="installation-a",
        )
        other_identity_workspace = root / "other-identity"
        other_identity = AUTOPILOT.prepare(
            other_identity_workspace, key(), "计算机网络", "balanced", requirements, profile,
            style_identity="installation-b",
        )
        results.append({
            "name": "capsule-is-stable-per-installation-and-different-across-installations",
            "ok": (
                same_identity["session"]["style_capsule_id"] == prepared["session"]["style_capsule_id"]
                and other_identity["session"]["style_capsule_id"] != same_identity["session"]["style_capsule_id"]
            ),
        })

        cold_start_signatures = []
        for index in range(128):
            identity = f"distribution-installation-{index}"
            cold_preferences = AUTOPILOT.default_preferences("计算机网络", identity)
            cold_genome = AUTOPILOT.build_writer_genome("计算机网络", cold_preferences, identity, None)
            cold_start_signatures.append(tuple(sorted(cold_genome["stable_axes"].items())))
        signature_counts = {signature: cold_start_signatures.count(signature) for signature in set(cold_start_signatures)}
        results.append({
            "name": "cold-start-genome-distribution-has-no-axis-collision-across-128-identities",
            "ok": len(signature_counts) == 128 and max(signature_counts.values()) == 1,
        })

        personal_profile_path = root / "personal-writing-profile.json"
        write_json(personal_profile_path, {
            "version": "1.0", "kind": "personal_writing_profile",
            "sample_summary": {
                "sample_count": 1, "usable_sample_count": 1,
                "authored_char_count": 1200, "sample_ids": ["sample_0123456789abcdef"],
            },
            "confidence": {"level": "high", "score": 0.9, "limitations": []},
            "features": {
                "sentence_rhythm": "短句和中长句混合", "terminology_handling": "术语首次简释",
                "person_voice": "少量第一人称", "reflection_pattern": "problem_solving",
                "connector_density": "low", "list_preference": "medium",
            },
            "recommended_preferences": {
                "writing_level": "natural_undergrad", "detail_level": "balanced",
                "sentence_paragraph_style": "mixed", "terminology_density": "medium",
                "voice_tone": "personal", "analysis_order": "procedure_first",
                "reflection_depth": "problem_solving", "variation_strength": "medium",
            },
            "humanization_preferences": {
                "preserve": ["短句和中长句混合"],
                "do_not_learn": ["通用意义拔高"],
            },
            "excluded_patterns": [
                {"id": "significance_inflation", "count": 1, "action": "do_not_learn"},
            ],
            "privacy": {
                "stores_report_body": False, "stores_source_paths": False,
                "stores_personal_identifiers": False, "local_analysis_only": True,
            },
        })
        personal_workspace = root / "personal"
        personal = AUTOPILOT.prepare(
            personal_workspace, key(), "数据结构", "balanced", requirements, profile,
            personal_profile_path=personal_profile_path, style_identity="installation-personal",
        )
        personal_summary = personal["interaction_plan"]["checkpoint"]["summary"]
        persisted_personal = (personal_workspace / "lab-factory" / "objects" / "personal-profile-v1.json").read_text(encoding="utf-8")
        results.append({
            "name": "prior-report-profile-is-optional-private-and-takes-precedence",
            "ok": (
                personal_summary["personalization"]["source"] == "prior_report_profile"
                and personal_summary["preferences"]["analysis_order"] == "procedure_first"
                and "sample_text" not in persisted_personal
                and "full_text" not in persisted_personal
                and str(personal_profile_path) not in persisted_personal
            ),
        })

        exception_workspace = root / "exception"
        exception_prepared = AUTOPILOT.prepare(
            exception_workspace, key(), "计算机网络", "balanced", requirements, profile,
            style_identity="installation-exception",
        )
        exception_preflight = exception_prepared
        exception_confirm = AUTOPILOT.confirm_checkpoint(
            exception_workspace, 1, key(), "preflight",
            exception_preflight["interaction_plan"]["checkpoint"]["summary_sha256"],
        )
        exception_running = AUTOPILOT.advance(
            exception_workspace, 2, key(), exception_confirm["confirmation_token"], {}
        )
        style_question = AUTOPILOT.advance(
            exception_workspace, exception_running["session"]["state_version"], key(), None,
            {"style_calibration": {"confidence": 0.52, "sample_ids": ["style-a", "style-b"]}},
        )
        results.append({
            "name": "low-style-confidence-triggers-two-sample-calibration",
            "ok": (
                style_question["next_action"] == "ask_user"
                and style_question["interaction_plan"]["questions"][0]["allowed_values"] == ["style-a", "style-b"]
            ),
        })
        style_answered = AUTOPILOT.answer_questions(
            exception_workspace, style_question["session"]["state_version"], key(),
            style_question["interaction_plan"]["plan_id"],
            [{"question_id": "style_calibration", "value": "style-b"}],
        )
        low_confidence = AUTOPILOT.advance(
            exception_workspace, style_answered["session"]["state_version"], key(), None,
            {"placement": {"score": 0.82, "margin": 0.05}},
        )
        results.append({
            "name": "low-confidence-placement-asks-user",
            "ok": low_confidence["next_action"] == "ask_user" and low_confidence["interaction_plan"]["questions"][0]["scope"] == "placement_choice",
        })

        fast_code = error_code(
            AUTOPILOT.prepare, root / "fast", key(), "软件工程", "fast", requirements, profile
        )
        results.append({"name": "fast-mode-reserved-but-disabled", "ok": fast_code == "MODE_NOT_ENABLED"})

        legacy_workspace = root / "legacy"
        (legacy_workspace / "lab-factory").mkdir(parents=True)
        write_json(legacy_workspace / "lab-factory" / "session-state.json", {"version": "2.0", "state": "materials_scanned"})
        legacy_code = error_code(AUTOPILOT.status, legacy_workspace)
        results.append({"name": "legacy-session-remains-strict", "ok": legacy_code == "LEGACY_SESSION"})

    failed = [item for item in results if not item["ok"]]
    return {"ok": not failed, "count": len(results), "failed": failed, "results": results}


def main() -> int:
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
