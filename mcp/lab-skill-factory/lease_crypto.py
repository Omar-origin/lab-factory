"""Cryptographic formats for installation-bound, short-lived online leases."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


LEASE_FORMAT = "lab-factory-online-lease"
LEASE_VERSION = 1
LEASE_KEY_FORMAT = "lab-factory-lease-signing-key"
LEASE_PUBLIC_KEY_FORMAT = "lab-factory-lease-public-key"
DEVICE_KEY_FORMAT = "lab-factory-installation-key"
DEFAULT_LEASE_HOURS = 24
DEFAULT_REFRESH_HOURS = 6
PLAN_EXPERIENCE = "experience"
PLAN_PERMANENT = "permanent"
VALID_PLANS = {PLAN_EXPERIENCE, PLAN_PERMANENT}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_utc(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _write_json(path: Path, value: dict[str, Any], *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if private and os.name != "nt":
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
    os.replace(temporary, path)


def create_lease_issuer(private_path: Path, public_path: Path, *, force: bool = False) -> dict[str, Any]:
    if not force and (private_path.exists() or public_path.exists()):
        raise FileExistsError("lease signing key already exists; use --force only for intentional rotation")
    private_key = Ed25519PrivateKey.generate()
    private_raw = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = "lfleasepk_" + hashlib.sha256(public_raw).hexdigest()[:16]
    _write_json(private_path, {
        "format": LEASE_KEY_FORMAT,
        "version": LEASE_VERSION,
        "key_id": key_id,
        "private_key": b64encode(private_raw),
        "created_at": utc_now(),
    }, private=True)
    _write_json(public_path, {
        "format": LEASE_PUBLIC_KEY_FORMAT,
        "version": LEASE_VERSION,
        "key_id": key_id,
        "public_key": b64encode(public_raw),
    })
    return {"ok": True, "key_id": key_id, "private_key_path": str(private_path), "public_key_path": str(public_path)}


def load_private_record(path: Path) -> tuple[str, Ed25519PrivateKey]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("format") != LEASE_KEY_FORMAT or value.get("version") != LEASE_VERSION:
        raise ValueError("unsupported lease signing private key")
    return str(value["key_id"]), Ed25519PrivateKey.from_private_bytes(b64decode(str(value["private_key"])))


def create_device_key() -> dict[str, Any]:
    private_key = Ed25519PrivateKey.generate()
    private_raw = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {
        "format": DEVICE_KEY_FORMAT,
        "version": LEASE_VERSION,
        "private_key": b64encode(private_raw),
        "public_key": b64encode(public_raw),
        "created_at": utc_now(),
    }


def sign_device_message(device_record: dict[str, Any], message: dict[str, Any]) -> str:
    if device_record.get("format") != DEVICE_KEY_FORMAT or device_record.get("version") != LEASE_VERSION:
        raise ValueError("invalid installation key record")
    key = Ed25519PrivateKey.from_private_bytes(b64decode(str(device_record["private_key"])))
    return b64encode(key.sign(canonical_json(message)))


def verify_device_message(public_key: str, message: dict[str, Any], signature: str) -> None:
    Ed25519PublicKey.from_public_bytes(b64decode(public_key)).verify(
        b64decode(signature), canonical_json(message),
    )


def validate_device_public_key(public_key: str) -> None:
    raw = b64decode(public_key)
    if len(raw) != 32:
        raise ValueError("installation public key must contain exactly 32 bytes")
    Ed25519PublicKey.from_public_bytes(raw)


def issue_lease(
    private_path: Path,
    *,
    license_key_id: str,
    install_id: str,
    product_id: str,
    now: datetime | None = None,
    lease_hours: int = DEFAULT_LEASE_HOURS,
    plan: str = PLAN_PERMANENT,
    usage_limit: int | None = None,
    usage_count: int = 0,
) -> dict[str, Any]:
    if plan not in VALID_PLANS:
        raise ValueError("unsupported license plan")
    if plan == PLAN_EXPERIENCE and usage_limit != 3:
        raise ValueError("experience licenses must have exactly three uses")
    if plan == PLAN_PERMANENT:
        usage_limit = None
    if usage_count < 0 or (usage_limit is not None and usage_count > usage_limit):
        raise ValueError("invalid usage counters")
    issued = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    key_id, private_key = load_private_record(private_path)
    payload = {
        "format": LEASE_FORMAT,
        "version": LEASE_VERSION,
        "lease_id": "lflease_" + uuid.uuid4().hex,
        "license_key_id": license_key_id,
        "install_id": install_id,
        "product_id": product_id,
        "status": "active",
        "issued_at": issued.isoformat(),
        "refresh_after": (issued + timedelta(hours=DEFAULT_REFRESH_HOURS)).isoformat(),
        "expires_at": (issued + timedelta(hours=lease_hours)).isoformat(),
        "issuer_key_id": key_id,
        "plan": plan,
        "usage_limit": usage_limit,
        "usage_count": usage_count,
        "features": {"skill_condensation": plan == PLAN_PERMANENT},
    }
    return {"payload": payload, "signature": b64encode(private_key.sign(canonical_json(payload)))}


def verify_lease(
    envelope: dict[str, Any],
    public_record: dict[str, Any],
    *,
    install_id: str,
    product_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    payload, signature = envelope.get("payload"), envelope.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature, str):
        raise ValueError("lease must contain payload and signature")
    required = {
        "format", "version", "lease_id", "license_key_id", "install_id", "product_id", "status",
        "issued_at", "refresh_after", "expires_at", "issuer_key_id",
    }
    entitlement_fields = {"plan", "usage_limit", "usage_count", "features"}
    if not required.issubset(payload) or set(payload) - required - entitlement_fields or payload.get("format") != LEASE_FORMAT or payload.get("version") != LEASE_VERSION:
        raise ValueError("invalid or unsupported lease")
    if public_record.get("format") != LEASE_PUBLIC_KEY_FORMAT or public_record.get("version") != LEASE_VERSION:
        raise ValueError("this build has no valid embedded lease public key")
    if payload.get("issuer_key_id") != public_record.get("key_id"):
        raise ValueError("lease was signed by a different online issuer")
    Ed25519PublicKey.from_public_bytes(b64decode(str(public_record["public_key"]))).verify(
        b64decode(signature), canonical_json(payload),
    )
    if payload.get("install_id") != install_id or payload.get("product_id") != product_id:
        raise ValueError("lease belongs to another installation or product")
    if payload.get("status") != "active":
        raise ValueError("lease is not active")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if parse_utc(str(payload["issued_at"])) > current + timedelta(minutes=5):
        raise ValueError("lease issue time is in the future")
    if parse_utc(str(payload["expires_at"])) <= current:
        raise ValueError("online lease expired; reconnect to refresh authorization")
    # Version-1 leases issued before plans existed are existing permanent licenses.
    if not entitlement_fields.intersection(payload):
        payload = dict(payload, plan=PLAN_PERMANENT, usage_limit=None, usage_count=0,
                       features={"skill_condensation": True})
    elif not entitlement_fields.issubset(payload):
        raise ValueError("lease entitlement fields are incomplete")
    plan = payload.get("plan")
    limit, count, features = payload.get("usage_limit"), payload.get("usage_count"), payload.get("features")
    if plan not in VALID_PLANS or not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ValueError("lease entitlement is invalid")
    if not isinstance(features, dict) or set(features) != {"skill_condensation"} or not isinstance(features["skill_condensation"], bool):
        raise ValueError("lease feature entitlement is invalid")
    if plan == PLAN_EXPERIENCE:
        if limit != 3 or count > limit or features["skill_condensation"]:
            raise ValueError("experience lease entitlement is invalid")
    elif limit is not None or not features["skill_condensation"]:
        raise ValueError("permanent lease entitlement is invalid")
    return payload
