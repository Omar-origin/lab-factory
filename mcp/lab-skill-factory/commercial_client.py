"""Offline paid-beta client: device-bound licenses and user-exported diagnostics."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import stat
import sys
import uuid
from pathlib import Path
from typing import Any

from offline_license import (
    FORMAT_VERSION, PRODUCT_ID, REQUEST_FORMAT, TERMS_VERSION, read_object, utc_now,
    verify_license, write_json,
)


APP_DIR = Path(os.environ.get("LAB_FACTORY_APP_DIR", Path.home() / ".lab-factory"))
DEVICE_FILE = APP_DIR / "device.json"
PREFERENCES_FILE = APP_DIR / "preferences.json"
LICENSE_METADATA_FILE = APP_DIR / "license.json"
TELEMETRY_LOG = APP_DIR / "telemetry.jsonl"
FEEDBACK_LOG = APP_DIR / "feedback.jsonl"
PUBLIC_KEY_FILE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "license_public_key.json"
PURCHASE_URL = os.environ.get("LAB_FACTORY_PURCHASE_URL", "请联系销售者购买")
SUPPORT_EMAIL = os.environ.get("LAB_FACTORY_SUPPORT_EMAIL", "support@example.invalid")
FEEDBACK_EMAIL = os.environ.get("LAB_FACTORY_FEEDBACK_EMAIL", SUPPORT_EMAIL)
TELEMETRY_ALLOWLIST = {
    "event", "version", "platform", "architecture", "tool", "ok", "error_code", "duration_ms",
    "auto_count", "confirm_count", "blocked_count", "quality_gate", "placeholder_count", "unsupported_count",
    "channel_id",
}
FEEDBACK_ALLOWLIST = {"review_id", "rating", "issue_categories", "edit_time_bucket", "channel_id"}


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return read_object(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return default or {}


def write_private_json(path: Path, value: dict[str, Any]) -> None:
    write_json(path, value, private=True)


def install_id() -> str:
    configured = os.environ.get("LAB_FACTORY_INSTALL_ID", "").strip()
    if configured and not bool(getattr(sys, "frozen", False)):
        return configured
    value = read_json(DEVICE_FILE).get("install_id")
    if isinstance(value, str) and value:
        return value
    value = "install_" + uuid.uuid4().hex
    write_private_json(DEVICE_FILE, {"install_id": value, "created_at": utc_now()})
    return value


def client_platform() -> tuple[str, str]:
    system, machine = platform.system().lower(), platform.machine().lower()
    return ("macos" if system == "darwin" else "windows" if system == "windows" else system,
            "arm64" if machine in {"arm64", "aarch64"} else "x64" if machine in {"x86_64", "amd64"} else machine)


def embedded_public_key() -> dict[str, Any]:
    override = os.environ.get("LAB_FACTORY_LICENSE_PUBLIC_KEY_FILE", "").strip()
    path = Path(override) if override and not bool(getattr(sys, "frozen", False)) else PUBLIC_KEY_FILE
    return read_json(path)


def create_license_request(output_path: Path) -> dict[str, Any]:
    platform_name, architecture = client_platform()
    request = {
        "format": REQUEST_FORMAT, "version": FORMAT_VERSION, "request_id": "lfreq_" + uuid.uuid4().hex,
        "product_id": PRODUCT_ID, "install_id": install_id(), "platform": platform_name,
        "architecture": architecture, "created_at": utc_now(),
    }
    write_json(output_path, request)
    return {"ok": True, "request_path": str(output_path), "request_id": request["request_id"],
            "next_step": "将 .lfreq 文件通过微信或邮箱发给销售者；收到 .lflicense 后执行 activate。"}


class CredentialStore:
    service, username = "lab-factory-1", "offline-license"

    def _keyring(self):
        if os.environ.get("LAB_FACTORY_CREDENTIAL_BACKEND") == "file":
            return None
        try:
            import keyring
            return keyring
        except Exception:
            return None

    def get(self) -> dict[str, Any] | None:
        keyring = self._keyring()
        if keyring:
            try:
                value = keyring.get_password(self.service, self.username)
                if value:
                    parsed = json.loads(value)
                    return parsed if isinstance(parsed, dict) else None
            except Exception:
                pass
        value = read_json(LICENSE_METADATA_FILE).get("license")
        return value if isinstance(value, dict) else None

    def save(self, license_envelope: dict[str, Any], metadata: dict[str, Any]) -> None:
        keyring, stored = self._keyring(), False
        if keyring:
            try:
                keyring.set_password(self.service, self.username, json.dumps(license_envelope, ensure_ascii=False))
                stored = True
            except Exception:
                pass
        value = dict(metadata, credential_backend="keyring" if stored else "restricted_file")
        if not stored:
            value["license"] = license_envelope
        write_private_json(LICENSE_METADATA_FILE, value)

    def clear(self) -> None:
        keyring = self._keyring()
        if keyring:
            try:
                keyring.delete_password(self.service, self.username)
            except Exception:
                pass
        write_private_json(LICENSE_METADATA_FILE, {"status": "REMOVED", "removed_at": utc_now()})


def activate(license_path: Path, adult_confirmed: bool, terms_version: str) -> dict[str, Any]:
    if not adult_confirmed or terms_version != TERMS_VERSION:
        raise ValueError(f"must confirm age 18+ and accept terms version {TERMS_VERSION}")
    envelope = read_object(license_path)
    payload = verify_license(envelope, embedded_public_key())
    if payload["install_id"] != install_id():
        raise ValueError("license belongs to a different installation; generate a new request on this device")
    CredentialStore().save(envelope, {
        "status": "ACTIVE", "license_id": payload["license_id"], "channel_id": payload["channel_id"],
        "entitlement": payload["entitlement"], "issued_at": payload["issued_at"], "imported_at": utc_now(),
    })
    return {"ok": True, "activated": True, "mode": "offline_permanent_license",
            "license_id": payload["license_id"], "entitlement": payload["entitlement"]}


def activation_status(refresh: bool = False) -> dict[str, Any]:
    if os.environ.get("LAB_FACTORY_DEV_ALLOW") == "1" and not bool(getattr(sys, "frozen", False)):
        return {"activated": True, "mode": "source_development_override"}
    envelope = CredentialStore().get()
    if not envelope:
        return {"activated": False, "mode": "offline_permanent_license",
                "message": f"尚未激活。先生成授权请求并发送给销售者。购买：{PURCHASE_URL}；支持：{SUPPORT_EMAIL}"}
    try:
        payload = verify_license(envelope, embedded_public_key())
    except Exception as exc:
        return {"activated": False, "mode": "offline_permanent_license", "message": f"本地授权无效：{exc}"}
    if payload["install_id"] != install_id():
        return {"activated": False, "mode": "offline_permanent_license", "message": "授权不属于当前安装。"}
    return {"activated": True, "mode": "offline_permanent_license", "license_id": payload["license_id"],
            "channel_id": payload["channel_id"], "entitlement": payload["entitlement"], "issued_at": payload["issued_at"]}


def deactivate() -> dict[str, Any]:
    existed = CredentialStore().get() is not None
    CredentialStore().clear()
    return {"ok": True, "removed": existed,
            "message": "已从本机移除授权。离线授权无法远程吊销；换机请生成新请求并联系销售者。"}


def preferences() -> dict[str, Any]:
    return read_json(PREFERENCES_FILE, {"telemetry": "unset"})


def set_telemetry(enabled: bool) -> dict[str, Any]:
    value = {"telemetry": "enabled" if enabled else "disabled", "decided_at": utc_now()}
    write_private_json(PREFERENCES_FILE, value)
    return {"ok": True, **value}


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    if os.name != "nt":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def telemetry_status() -> dict[str, Any]:
    return {"ok": True, "telemetry": preferences().get("telemetry", "unset"),
            "storage": "local_only", "collects_document_content": False,
            "event_count": len(_read_jsonl(TELEMETRY_LOG)), "feedback_email": FEEDBACK_EMAIL}


def record_telemetry(event: dict[str, Any]) -> dict[str, Any]:
    if preferences().get("telemetry") != "enabled":
        return {"ok": True, "recorded": False, "reason": "telemetry_not_enabled"}
    if set(event) - TELEMETRY_ALLOWLIST:
        return {"ok": False, "recorded": False, "error": "event contains fields outside allowlist"}
    _append_jsonl(TELEMETRY_LOG, dict(event, recorded_at=utc_now()))
    return {"ok": True, "recorded": True, "storage": "local_only"}


def record_feedback(feedback: dict[str, Any]) -> dict[str, Any]:
    if set(feedback) - FEEDBACK_ALLOWLIST:
        return {"ok": False, "error": "feedback contains fields outside allowlist"}
    _append_jsonl(FEEDBACK_LOG, dict(feedback, recorded_at=utc_now()))
    return {"ok": True, "recorded": True, "storage": "local_only",
            "next_step": f"执行 feedback-export 后，将导出文件发到 {FEEDBACK_EMAIL}。"}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    values: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                values.append(value)
        except json.JSONDecodeError:
            continue
    return values


def clear_telemetry() -> dict[str, Any]:
    removed = 0
    for path in (TELEMETRY_LOG, FEEDBACK_LOG):
        if path.exists():
            removed += 1
            path.unlink()
    return {"ok": True, "cleared_files": removed}


def export_feedback(output_path: Path) -> dict[str, Any]:
    status = activation_status()
    platform_name, architecture = client_platform()
    bundle = {
        "format": "lab-factory-feedback-export", "version": 1, "generated_at": utc_now(),
        "platform": platform_name, "architecture": architecture,
        "channel_id": status.get("channel_id"), "telemetry_events": _read_jsonl(TELEMETRY_LOG),
        "draft_feedback": _read_jsonl(FEEDBACK_LOG),
        "privacy_note": "不包含正文、标题、文件名、路径、源码、截图或自然语言摘要。",
    }
    write_json(output_path, bundle)
    return {"ok": True, "output_path": str(output_path), "event_count": len(bundle["telemetry_events"]),
            "feedback_count": len(bundle["draft_feedback"]), "send_to": FEEDBACK_EMAIL}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_update_file(path: Path, expected_sha256: str) -> dict[str, Any]:
    actual = file_sha256(path)
    ok = actual == expected_sha256.strip().lower()
    return {"ok": ok, "path": str(path), "sha256": actual,
            "message": "校验通过，可按人工提供的安装说明更新。" if ok else "校验失败，不要安装此文件。"}
