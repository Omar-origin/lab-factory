"""Ed25519 primitives and strict formats for offline Lab Factory licenses."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


PRODUCT_ID = "lab-factory-1"
ENTITLEMENT = "lab-factory-1.x-permanent"
TERMS_VERSION = "1.0"
REQUEST_FORMAT = "lab-factory-license-request"
LICENSE_FORMAT = "lab-factory-offline-license"
FORMAT_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def write_json(path: Path, value: Any, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if private and os.name != "nt":
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
    os.replace(temporary, path)


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def create_issuer(private_path: Path, public_path: Path, force: bool = False) -> dict[str, Any]:
    if not force and (private_path.exists() or public_path.exists()):
        raise FileExistsError("issuer key already exists; use --force only when intentionally rotating keys")
    private_key = Ed25519PrivateKey.generate()
    private_raw = private_key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public_raw = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = "lfpk_" + hashlib.sha256(public_raw).hexdigest()[:16]
    write_json(private_path, {
        "format": "lab-factory-issuer-private-key", "version": 1, "key_id": key_id,
        "private_key": b64encode(private_raw), "created_at": utc_now(),
    }, private=True)
    write_json(public_path, {
        "format": "lab-factory-license-public-key", "version": 1, "key_id": key_id,
        "public_key": b64encode(public_raw),
    })
    return {"ok": True, "key_id": key_id, "private_key_path": str(private_path), "public_key_path": str(public_path)}


def load_private_key(path: Path) -> tuple[str, Ed25519PrivateKey]:
    value = read_object(path)
    if value.get("format") != "lab-factory-issuer-private-key" or value.get("version") != 1:
        raise ValueError("unsupported issuer private-key file")
    return str(value["key_id"]), Ed25519PrivateKey.from_private_bytes(b64decode(str(value["private_key"])))


def validate_request(value: dict[str, Any]) -> dict[str, Any]:
    required = {"format", "version", "request_id", "product_id", "install_id", "platform", "architecture", "created_at"}
    if set(value) != required or value.get("format") != REQUEST_FORMAT or value.get("version") != FORMAT_VERSION:
        raise ValueError("invalid or unsupported license request")
    if value.get("product_id") != PRODUCT_ID:
        raise ValueError("license request belongs to another product")
    for field in required - {"version"}:
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError(f"license request field {field} must be a non-empty string")
    return value


def issue_license(
    request: dict[str, Any], private_path: Path, channel_id: str,
    replaces_license_id: str = "",
) -> dict[str, Any]:
    request = validate_request(request)
    key_id, private_key = load_private_key(private_path)
    payload = {
        "format": LICENSE_FORMAT, "version": FORMAT_VERSION,
        "license_id": "lflic_" + uuid.uuid4().hex,
        "request_id": request["request_id"], "product_id": PRODUCT_ID,
        "install_id": request["install_id"], "entitlement": ENTITLEMENT,
        "issued_at": utc_now(), "terms_version": TERMS_VERSION,
        "channel_id": channel_id.strip() or "direct",
        "replaces_license_id": replaces_license_id.strip(),
        "issuer_key_id": key_id,
    }
    return {"payload": payload, "signature": b64encode(private_key.sign(canonical_json(payload)))}


def verify_license(envelope: dict[str, Any], public_record: dict[str, Any]) -> dict[str, Any]:
    payload, signature = envelope.get("payload"), envelope.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature, str):
        raise ValueError("license file must contain payload and signature")
    required = {
        "format", "version", "license_id", "request_id", "product_id", "install_id", "entitlement",
        "issued_at", "terms_version", "channel_id", "replaces_license_id", "issuer_key_id",
    }
    if set(payload) != required or payload.get("format") != LICENSE_FORMAT or payload.get("version") != FORMAT_VERSION:
        raise ValueError("invalid or unsupported offline license")
    if payload.get("product_id") != PRODUCT_ID or payload.get("entitlement") != ENTITLEMENT:
        raise ValueError("license belongs to another product or entitlement")
    if public_record.get("format") != "lab-factory-license-public-key" or public_record.get("version") != 1:
        raise ValueError("this build has no valid embedded license public key")
    if payload.get("issuer_key_id") != public_record.get("key_id"):
        raise ValueError("license was signed by a different issuer key")
    Ed25519PublicKey.from_public_bytes(b64decode(str(public_record["public_key"]))).verify(
        b64decode(signature), canonical_json(payload),
    )
    return payload


def request_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()
