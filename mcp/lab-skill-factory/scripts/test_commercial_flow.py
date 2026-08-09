#!/usr/bin/env python3
"""End-to-end checks for offline issuance, local telemetry, and manual updates."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

MCP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MCP_DIR))

import commercial_client as client
from offline_license import create_issuer, issue_license, read_object, write_json


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        private_key, public_key = root / "issuer-private.json", root / "public.json"
        request_path, license_path = root / "device.lfreq", root / "device.lflicense"
        create_issuer(private_key, public_key)

        client.APP_DIR = root / "app"
        client.DEVICE_FILE = client.APP_DIR / "device.json"
        client.PREFERENCES_FILE = client.APP_DIR / "preferences.json"
        client.LICENSE_METADATA_FILE = client.APP_DIR / "license.json"
        client.TELEMETRY_LOG = client.APP_DIR / "telemetry.jsonl"
        client.FEEDBACK_LOG = client.APP_DIR / "feedback.jsonl"
        client.PUBLIC_KEY_FILE = public_key
        os.environ["LAB_FACTORY_CREDENTIAL_BACKEND"] = "file"

        generated = client.create_license_request(request_path)
        check(generated["ok"] and request_path.exists(), "request was not generated")
        envelope = issue_license(read_object(request_path), private_key, "campus-a")
        write_json(license_path, envelope)
        activated = client.activate(license_path, True, "1.0")
        check(activated["activated"], "offline license did not activate")
        check(client.activation_status()["mode"] == "offline_permanent_license", "wrong activation mode")

        forged = read_object(license_path)
        forged["payload"]["channel_id"] = "forged"
        write_json(root / "forged.lflicense", forged)
        try:
            client.activate(root / "forged.lflicense", True, "1.0")
            raise AssertionError("forged license was accepted")
        except Exception:
            pass

        event = {"event": "tool_call", "version": "test", "platform": "macos", "architecture": "arm64",
                 "tool": "test", "ok": True, "error_code": "", "duration_ms": 5, "channel_id": "campus-a"}
        check(not client.record_telemetry(event)["recorded"], "unset telemetry recorded data")
        client.set_telemetry(True)
        check(client.record_telemetry(event)["recorded"], "enabled telemetry did not record")
        check(not client.record_telemetry(event | {"document_text": "secret"})["ok"], "unknown field was accepted")
        client.record_feedback({"review_id": "r1", "rating": 4, "issue_categories": ["format"],
                                "edit_time_bucket": "15_30m", "channel_id": "campus-a"})
        exported = client.export_feedback(root / "feedback.json")
        check(exported["event_count"] == 1 and exported["feedback_count"] == 1, "feedback export counts are wrong")
        text = (root / "feedback.json").read_text(encoding="utf-8")
        check("secret" not in text and "install_" not in text, "feedback export leaked forbidden data")

        package = root / "update.bin"
        package.write_bytes(b"manual update")
        digest = client.file_sha256(package)
        check(client.verify_update_file(package, digest)["ok"], "valid SHA-256 was rejected")
        check(not client.verify_update_file(package, "0" * 64)["ok"], "invalid SHA-256 was accepted")
        check(client.deactivate()["ok"] and not client.activation_status()["activated"], "local removal failed")
    print(json.dumps({"ok": True, "tests": 12}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
