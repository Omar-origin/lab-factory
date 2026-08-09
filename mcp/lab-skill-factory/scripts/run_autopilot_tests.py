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


def run() -> dict:
    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="lab-factory-autopilot-tests-") as temporary:
        root = Path(temporary)
        requirements, profile = prepare_files(root)
        workspace = root / "normal"

        prepared = AUTOPILOT.prepare(
            workspace, key(), "软件工程", "balanced", requirements, profile
        )
        questions = prepared["interaction_plan"]["questions"]
        results.append({
            "name": "first-run-asks-eight-stable-preferences",
            "ok": len(questions) == 8 and {q["scope"] for q in questions} == {"stable_preference"},
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

        answers = [{"question_id": q["id"], "value": q["default"]} for q in questions]
        answered = AUTOPILOT.answer_questions(
            workspace, prepared["session"]["state_version"], key(),
            prepared["interaction_plan"]["plan_id"], answers,
        )
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
                "quality_gates": {"status": "pass"},
                "draft": {"object_id": "docx-final-v1", "sha256": "a" * 64, "wps_review_checklist": ["分页", "行距"]},
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
        variation = json.loads((workspace / "lab-factory" / "objects" / "variation-v1.json").read_text(encoding="utf-8"))
        results.append({
            "name": "variation-contract-is-observable-not-synonym-randomization",
            "ok": (
                len(preferences["values"]) == 8
                and set(variation["observable_axes"]) == {
                    "section_emphasis", "explanation_order", "evidence_example_density",
                    "reflection_angle", "secondary_emphasis",
                }
                and variation["forbidden_strategy"] == "random_synonym_substitution"
            ),
        })

        exception_workspace = root / "exception"
        exception_prepared = AUTOPILOT.prepare(
            exception_workspace, key(), "计算机网络", "balanced", requirements, profile
        )
        exception_answers = [
            {"question_id": q["id"], "value": q["default"]}
            for q in exception_prepared["interaction_plan"]["questions"]
        ]
        exception_preflight = AUTOPILOT.answer_questions(
            exception_workspace, 1, key(), exception_prepared["interaction_plan"]["plan_id"], exception_answers
        )
        exception_confirm = AUTOPILOT.confirm_checkpoint(
            exception_workspace, 2, key(), "preflight",
            exception_preflight["interaction_plan"]["checkpoint"]["summary_sha256"],
        )
        exception_running = AUTOPILOT.advance(
            exception_workspace, 3, key(), exception_confirm["confirmation_token"], {}
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
