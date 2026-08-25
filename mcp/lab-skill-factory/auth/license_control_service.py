#!/usr/bin/env python3
"""Lab Factory license control plane with one-install binding and signed 24-hour leases."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
CONTROL_UI_DIR = Path(__file__).resolve().parent / "control_ui"
PURCHASE_UI_DIR = Path(__file__).resolve().parent / "purchase_ui"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lease_crypto import (
    PLAN_EXPERIENCE, PLAN_PERMANENT, issue_lease, load_private_record, parse_utc,
    validate_device_public_key, verify_device_message,
)
from payment_providers import ManualPaymentProvider, PaddlePaymentProvider, PaymentProvider


KEY_STATES = {"unused", "active", "refund_requested", "refunded", "banned"}
ORDER_STATES = {
    "payment_pending", "payment_submitted", "payment_rejected", "paid",
    "key_issued", "delivered", "refund_requested", "refunded",
}
PUBLIC_ACTIVE_STATES = {"active"}
LICENSE_PLANS = {PLAN_EXPERIENCE, PLAN_PERMANENT}
MAX_BODY_BYTES = 32 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def secret_hmac(secret: str, value: str) -> str:
    return hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def normalize_activation_key(value: str) -> str:
    return value.strip().upper().replace(" ", "")


def generate_activation_key() -> str:
    encoded = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
    return "LF-" + "-".join(encoded[index:index + 4] for index in range(0, len(encoded), 4))


def activation_key_from_bytes(value: bytes) -> str:
    encoded = base64.b32encode(value[:20]).decode("ascii").rstrip("=")
    return "LF-" + "-".join(encoded[index:index + 4] for index in range(0, len(encoded), 4))


def bounded_text(value: Any, field: str, maximum: int, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ControlError(400, "INVALID_FIELD", f"{field} must be a string")
    result = value.strip()
    if required and not result:
        raise ControlError(400, "MISSING_FIELD", f"{field} is required")
    if len(result) > maximum:
        raise ControlError(400, "INVALID_FIELD", f"{field} is too long")
    return result


class ControlError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


class ControlStore:
    def __init__(
        self,
        db_path: Path,
        *,
        key_pepper: str,
        token_secret: str,
        lease_private_key: Path,
        product_id: str = "lab-factory-1",
        lease_hours: int = 24,
        price_cents: int = 990,
        permanent_price_cents: int = 4990,
        refund_days: int = 7,
        payment_providers: dict[str, PaymentProvider] | None = None,
        support_contact: str = "",
    ) -> None:
        if len(key_pepper) < 32 or len(token_secret) < 32:
            raise ValueError("key pepper and token secret must each contain at least 32 characters")
        if lease_hours != 24:
            raise ValueError("commercial policy currently requires an exact 24-hour lease")
        self.db_path = db_path
        self.key_pepper = key_pepper
        self.token_secret = token_secret
        self.lease_private_key = lease_private_key
        self.product_id = product_id
        self.lease_hours = lease_hours
        if price_cents < 1:
            raise ValueError("price_cents must be positive")
        if refund_days not in {3, 7}:
            raise ValueError("refund_days must be 3 or 7")
        self.price_cents = price_cents
        if permanent_price_cents < 1:
            raise ValueError("permanent_price_cents must be positive")
        self.permanent_price_cents = permanent_price_cents
        self.refund_days = refund_days
        self.payment_providers = payment_providers or {}
        self.support_contact = support_contact[:200]
        load_private_record(lease_private_key)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()
        if os.name != "nt":
            self.db_path.chmod(0o600)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        conn.execute("pragma busy_timeout = 10000")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                pragma journal_mode = wal;
                create table if not exists license_keys (
                  id text primary key,
                  key_hash text not null unique,
                  key_suffix text not null,
                  status text not null check(status in ('unused','active','refund_requested','refunded','banned')),
                  label text not null default '',
                  customer_ref text not null default '',
                  refund_days integer not null check(refund_days in (3,7)),
                  product_id text not null,
                  created_at text not null,
                  sent_at text,
                  activated_at text,
                  refund_deadline text,
                  install_id text,
                  device_public_key text,
                  activation_token_hash text,
                  last_seen_at text,
                  revoked_at text,
                  revoke_reason text not null default ''
                  ,plan text not null default 'permanent' check(plan in ('experience','permanent'))
                  ,usage_limit integer check(usage_limit is null or usage_limit = 3)
                );
                create unique index if not exists unique_activation_token
                  on license_keys(activation_token_hash) where activation_token_hash is not null;
                create table if not exists request_nonces (
                  nonce text primary key,
                  license_key_id text not null references license_keys(id),
                  used_at text not null,
                  expires_at text not null
                );
                create table if not exists audit_events (
                  id text primary key,
                  license_key_id text references license_keys(id),
                  event text not null,
                  actor text not null,
                  reason text not null default '',
                  metadata_json text not null default '{}',
                  created_at text not null
                );
                create index if not exists license_keys_status_created on license_keys(status, created_at desc);
                create index if not exists audit_key_created on audit_events(license_key_id, created_at desc);
                create table if not exists usage_events (
                  id text primary key,
                  license_key_id text not null references license_keys(id),
                  usage_id text not null,
                  used_at text not null,
                  unique(license_key_id, usage_id)
                );
                create index if not exists usage_key_used on usage_events(license_key_id, used_at desc);
                create table if not exists orders (
                  id text primary key,
                  status_token_hash text not null unique,
                  status text not null check(status in ('payment_pending','payment_submitted','payment_rejected','paid','key_issued','delivered','refund_requested','refunded')),
                  product_id text not null,
                  amount_cents integer not null,
                  currency text not null,
                  payment_provider text not null,
                  contact text not null default '',
                  payment_reference text not null default '',
                  payment_claimed_at text,
                  refund_days integer not null check(refund_days in (3,7)),
                  license_key_id text references license_keys(id),
                  created_at text not null,
                  updated_at text not null,
                  paid_at text,
                  delivered_at text,
                  refund_requested_at text,
                  refunded_at text,
                  admin_reason text not null default ''
                  ,plan text not null default 'experience' check(plan in ('experience','permanent'))
                );
                create table if not exists order_audit_events (
                  id text primary key,
                  order_id text not null references orders(id),
                  event text not null,
                  actor text not null,
                  reason text not null default '',
                  metadata_json text not null default '{}',
                  created_at text not null
                );
                create index if not exists orders_status_created on orders(status, created_at desc);
                create index if not exists order_audit_created on order_audit_events(order_id, created_at desc);
                """
            )
            order_columns = {str(row[1]) for row in conn.execute("pragma table_info(orders)")}
            if "delivery_key_version" not in order_columns:
                conn.execute("alter table orders add column delivery_key_version text not null default ''")
            if "plan" not in order_columns:
                conn.execute("alter table orders add column plan text not null default 'experience'")
            key_columns = {str(row[1]) for row in conn.execute("pragma table_info(license_keys)")}
            if "plan" not in key_columns:
                conn.execute("alter table license_keys add column plan text not null default 'permanent'")
            if "usage_limit" not in key_columns:
                conn.execute("alter table license_keys add column usage_limit integer")

    def _key_hash(self, activation_key: str) -> str:
        normalized = normalize_activation_key(activation_key)
        return secret_hmac(self.key_pepper, normalized)

    def _order_activation_key(self, order_id: str) -> str:
        digest = hmac.new(
            self.key_pepper.encode("utf-8"),
            f"order-delivery:v1:{order_id}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return activation_key_from_bytes(digest)

    @staticmethod
    def _order_license_key_id(order_id: str) -> str:
        digest = hashlib.sha256(f"order-license:v1:{order_id}".encode("utf-8")).hexdigest()
        return "lfkey_" + digest[:32]

    def _activation_token(self, row: sqlite3.Row, install_id: str, public_key: str) -> str:
        material = f"{row['id']}\n{install_id}\n{public_key}"
        digest = hmac.new(self.token_secret.encode("utf-8"), material.encode("utf-8"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def _audit(
        self,
        conn: sqlite3.Connection,
        key_id: str | None,
        event: str,
        actor: str,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        conn.execute(
            "insert into audit_events(id,license_key_id,event,actor,reason,metadata_json,created_at) values(?,?,?,?,?,?,?)",
            (
                "lfaudit_" + uuid.uuid4().hex,
                key_id,
                event,
                actor,
                reason[:500],
                json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":")),
                utc_now(),
            ),
        )

    def _order_audit(
        self,
        conn: sqlite3.Connection,
        order_id: str,
        event: str,
        actor: str,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        conn.execute(
            "insert into order_audit_events(id,order_id,event,actor,reason,metadata_json,created_at) values(?,?,?,?,?,?,?)",
            (
                "lfoaudit_" + uuid.uuid4().hex,
                order_id,
                event,
                actor,
                reason[:500],
                json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":")),
                utc_now(),
            ),
        )

    def _insert_key(
        self,
        conn: sqlite3.Connection,
        *,
        label: str,
        customer_ref: str,
        refund_days: int,
        plan: str = PLAN_PERMANENT,
    ) -> tuple[str, str]:
        if plan not in LICENSE_PLANS:
            raise ControlError(400, "INVALID_PLAN", "plan must be experience or permanent")
        activation_key = generate_activation_key()
        key_id, created_at = "lfkey_" + uuid.uuid4().hex, utc_now()
        conn.execute(
            """insert into license_keys
            (id,key_hash,key_suffix,status,label,customer_ref,refund_days,product_id,created_at,plan,usage_limit)
            values(?,?,?,'unused',?,?,?,?,?,?,?)""",
            (
                key_id,
                self._key_hash(activation_key),
                activation_key[-4:],
                bounded_text(label, "label", 120),
                bounded_text(customer_ref, "customer_ref", 120),
                refund_days,
                self.product_id,
                created_at,
                plan,
                3 if plan == PLAN_EXPERIENCE else None,
            ),
        )
        self._audit(conn, key_id, "key_created", "admin", metadata={"refund_days": refund_days, "plan": plan})
        return activation_key, key_id

    @staticmethod
    def _public_row(row: sqlite3.Row) -> dict[str, Any]:
        hidden = {"key_hash", "activation_token_hash", "device_public_key"}
        value = {key: row[key] for key in row.keys() if key not in hidden}
        value["used"] = row["status"] != "unused" or bool(row["activated_at"])
        value["bound"] = bool(row["install_id"])
        return value

    def create_key(self, *, label: str = "", customer_ref: str = "", refund_days: int = 7,
                   plan: str = PLAN_PERMANENT) -> dict[str, Any]:
        if refund_days not in {3, 7}:
            raise ControlError(400, "INVALID_REFUND_DAYS", "refund_days must be 3 or 7")
        with self.connection() as conn:
            with conn:
                activation_key, key_id = self._insert_key(
                    conn, label=label, customer_ref=customer_ref, refund_days=refund_days, plan=plan
                )
        return {
            "ok": True,
            "activation_key": activation_key,
            "warning": "明文密钥只返回这一次，请立即通过你的私密渠道发送给用户。",
            "key": self.get_key(key_id),
        }

    def get_key(self, key_id: str) -> dict[str, Any]:
        with self.connection() as conn:
            row = conn.execute("select * from license_keys where id = ?", (key_id,)).fetchone()
            if not row:
                raise ControlError(404, "KEY_NOT_FOUND", "license key not found")
            events = conn.execute(
                "select id,event,actor,reason,metadata_json,created_at from audit_events where license_key_id = ? order by created_at desc limit 100",
                (key_id,),
            ).fetchall()
        value = self._public_row(row)
        value["audit_events"] = [
            {
                "id": event["id"], "event": event["event"], "actor": event["actor"],
                "reason": event["reason"], "metadata": json.loads(event["metadata_json"]),
                "created_at": event["created_at"],
            }
            for event in events
        ]
        return value

    def list_keys(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if status and status not in KEY_STATES:
            raise ControlError(400, "INVALID_STATUS", "unknown license-key status")
        limit = max(1, min(limit, 500))
        query, values = "select * from license_keys", []
        if status:
            query += " where status = ?"
            values.append(status)
        query += " order by created_at desc limit ?"
        values.append(limit)
        with self.connection() as conn:
            rows = conn.execute(query, values).fetchall()
        return [self._public_row(row) for row in rows]

    def mark_sent(self, key_id: str) -> dict[str, Any]:
        with self.connection() as conn:
            with conn:
                row = conn.execute("select * from license_keys where id = ?", (key_id,)).fetchone()
                if not row:
                    raise ControlError(404, "KEY_NOT_FOUND", "license key not found")
                if not row["sent_at"]:
                    conn.execute("update license_keys set sent_at = ? where id = ?", (utc_now(), key_id))
                    self._audit(conn, key_id, "key_sent", "admin")
        return {"ok": True, "key": self.get_key(key_id)}

    def activate(self, activation_key: str, install_id: str, public_key: str) -> dict[str, Any]:
        activation_key = bounded_text(activation_key, "activation_key", 128, required=True)
        install_id = bounded_text(install_id, "install_id", 96, required=True)
        public_key = bounded_text(public_key, "device_public_key", 128, required=True)
        try:
            validate_device_public_key(public_key)
        except Exception as exc:
            raise ControlError(400, "INVALID_DEVICE_KEY", "installation public key is invalid") from exc
        now = datetime.now(timezone.utc).replace(microsecond=0)
        conn = self.connect()
        try:
            conn.execute("begin immediate")
            row = conn.execute("select * from license_keys where key_hash = ?", (self._key_hash(activation_key),)).fetchone()
            if not row:
                raise ControlError(404, "INVALID_KEY", "activation key is invalid")
            if row["status"] in {"banned", "refunded", "refund_requested"}:
                raise ControlError(403, "KEY_BLOCKED", f"activation key is {row['status']}")
            if row["status"] == "active":
                if row["install_id"] != install_id or not hmac.compare_digest(str(row["device_public_key"]), public_key):
                    raise ControlError(409, "KEY_ALREADY_USED", "activation key is already bound to another installation")
            elif row["status"] == "unused":
                deadline = now + timedelta(days=int(row["refund_days"]))
                conn.execute(
                    """update license_keys set status='active',activated_at=?,refund_deadline=?,install_id=?,
                    device_public_key=?,last_seen_at=?,revoked_at=null,revoke_reason='' where id=? and status='unused'""",
                    (now.isoformat(), deadline.isoformat(), install_id, public_key, now.isoformat(), row["id"]),
                )
                if conn.total_changes < 1:
                    raise ControlError(409, "ACTIVATION_RACE", "activation was claimed by another request")
                self._audit(conn, row["id"], "key_activated", "client", metadata={"install_id": install_id})
                row = conn.execute("select * from license_keys where id = ?", (row["id"],)).fetchone()
            token = self._activation_token(row, install_id, public_key)
            hashed_token = token_hash(token)
            conn.execute(
                "update license_keys set activation_token_hash=?,last_seen_at=? where id=?",
                (hashed_token, now.isoformat(), row["id"]),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        with self.connection() as usage_conn:
            usage_count = int(usage_conn.execute(
                "select count(*) from usage_events where license_key_id=?", (row["id"],)
            ).fetchone()[0])
        lease = issue_lease(
            self.lease_private_key,
            license_key_id=str(row["id"]),
            install_id=install_id,
            product_id=self.product_id,
            now=now,
            lease_hours=self.lease_hours,
            plan=str(row["plan"]), usage_limit=row["usage_limit"], usage_count=usage_count,
        )
        return {
            "ok": True,
            "status": "active",
            "activation_token": token,
            "lease": lease,
            "refund_deadline": row["refund_deadline"],
            "refund_days": row["refund_days"],
        }

    def _authenticated_request(self, payload: dict[str, Any], expected_action: str,
                               extra_fields: set[str] | None = None) -> tuple[sqlite3.Row, dict[str, Any]]:
        token = bounded_text(payload.get("activation_token"), "activation_token", 128, required=True)
        message = payload.get("proof")
        signature = payload.get("signature")
        if not isinstance(message, dict) or not isinstance(signature, str):
            raise ControlError(400, "MISSING_PROOF", "signed installation proof is required")
        required = {"action", "activation_token", "install_id", "timestamp", "nonce"} | (extra_fields or set())
        if set(message) != required or message.get("action") != expected_action or message.get("activation_token") != token:
            raise ControlError(400, "INVALID_PROOF", "installation proof does not match request")
        install_id = bounded_text(message.get("install_id"), "install_id", 96, required=True)
        nonce = bounded_text(message.get("nonce"), "nonce", 128, required=True)
        try:
            timestamp = parse_utc(bounded_text(message.get("timestamp"), "timestamp", 64, required=True))
        except (ValueError, TypeError) as exc:
            raise ControlError(400, "INVALID_TIMESTAMP", "proof timestamp is invalid") from exc
        now = datetime.now(timezone.utc)
        if abs((now - timestamp).total_seconds()) > 300:
            raise ControlError(401, "STALE_PROOF", "installation proof is outside the five-minute window")
        with self.connection() as conn:
            row = conn.execute(
                "select * from license_keys where activation_token_hash = ?",
                (token_hash(token),),
            ).fetchone()
        if not row or row["install_id"] != install_id:
            raise ControlError(401, "INVALID_TOKEN", "activation token or installation does not match")
        try:
            verify_device_message(str(row["device_public_key"]), message, signature)
        except Exception as exc:
            raise ControlError(401, "INVALID_SIGNATURE", "installation signature is invalid") from exc
        return row, {"message": message, "nonce": nonce, "now": now.replace(microsecond=0)}

    def _consume_nonce(self, conn: sqlite3.Connection, row: sqlite3.Row, nonce: str, now: datetime) -> None:
        conn.execute("delete from request_nonces where expires_at <= ?", (now.isoformat(),))
        try:
            conn.execute(
                "insert into request_nonces(nonce,license_key_id,used_at,expires_at) values(?,?,?,?)",
                (nonce, row["id"], now.isoformat(), (now + timedelta(minutes=10)).isoformat()),
            )
        except sqlite3.IntegrityError as exc:
            raise ControlError(409, "REPLAYED_PROOF", "installation proof nonce was already used") from exc

    def refresh(self, payload: dict[str, Any]) -> dict[str, Any]:
        row, proof = self._authenticated_request(payload, "refresh")
        if row["status"] not in PUBLIC_ACTIVE_STATES:
            raise ControlError(403, "KEY_BLOCKED", f"license key is {row['status']}")
        with self.connection() as conn:
            with conn:
                self._consume_nonce(conn, row, proof["nonce"], proof["now"])
                conn.execute("update license_keys set last_seen_at=? where id=?", (proof["now"].isoformat(), row["id"]))
                self._audit(conn, row["id"], "lease_refreshed", "client")
        with self.connection() as usage_conn:
            usage_count = int(usage_conn.execute(
                "select count(*) from usage_events where license_key_id=?", (row["id"],)
            ).fetchone()[0])
        lease = issue_lease(
            self.lease_private_key,
            license_key_id=str(row["id"]),
            install_id=str(row["install_id"]),
            product_id=self.product_id,
            now=proof["now"],
            lease_hours=self.lease_hours,
            plan=str(row["plan"]), usage_limit=row["usage_limit"], usage_count=usage_count,
        )
        return {"ok": True, "status": "active", "lease": lease}

    def consume_usage(self, payload: dict[str, Any]) -> dict[str, Any]:
        row, proof = self._authenticated_request(payload, "consume_usage", {"usage_id"})
        if row["status"] not in PUBLIC_ACTIVE_STATES:
            raise ControlError(403, "KEY_BLOCKED", f"license key is {row['status']}")
        usage_id = bounded_text(proof["message"].get("usage_id"), "usage_id", 128, required=True)
        charged = False
        conn = self.connect()
        try:
            conn.execute("begin immediate")
            existing = conn.execute(
                "select id from usage_events where license_key_id=? and usage_id=?", (row["id"], usage_id)
            ).fetchone()
            count = int(conn.execute(
                "select count(*) from usage_events where license_key_id=?", (row["id"],)
            ).fetchone()[0])
            if not existing:
                limit = row["usage_limit"]
                if limit is not None and count >= int(limit):
                    raise ControlError(403, "USAGE_LIMIT_REACHED", "experience license has used all three reports")
                conn.execute(
                    "insert into usage_events(id,license_key_id,usage_id,used_at) values(?,?,?,?)",
                    ("lfusage_" + uuid.uuid4().hex, row["id"], usage_id, proof["now"].isoformat()),
                )
                count += 1
                charged = True
                self._audit(conn, row["id"], "usage_consumed", "client", metadata={"usage_id": usage_id, "usage_count": count})
            self._consume_nonce(conn, row, proof["nonce"], proof["now"])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        lease = issue_lease(
            self.lease_private_key, license_key_id=str(row["id"]), install_id=str(row["install_id"]),
            product_id=self.product_id, now=proof["now"], lease_hours=self.lease_hours,
            plan=str(row["plan"]), usage_limit=row["usage_limit"], usage_count=count,
        )
        limit = row["usage_limit"]
        return {"ok": True, "status": "active", "charged": charged, "usage_count": count,
                "remaining_uses": None if limit is None else max(0, int(limit) - count), "lease": lease}

    def request_refund(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._authenticated_request(payload, "refund_request")
        raise ControlError(
            409,
            "SELF_SERVICE_REFUND_UNAVAILABLE",
            "数字化商品交付后不提供自助无理由退款。重复付款、无法激活或重大功能故障请联系售后QQ群 923937311 处理。",
        )

    def admin_action(self, key_id: str, action: str, reason: str = "") -> dict[str, Any]:
        reason = bounded_text(reason, "reason", 500)
        now = utc_now()
        conn = self.connect()
        try:
            conn.execute("begin immediate")
            row = conn.execute("select * from license_keys where id=?", (key_id,)).fetchone()
            if not row:
                raise ControlError(404, "KEY_NOT_FOUND", "license key not found")
            current = str(row["status"])
            if action == "ban":
                if current != "banned":
                    conn.execute(
                        "update license_keys set status='banned',revoked_at=?,revoke_reason=? where id=?",
                        (now, reason or "policy violation", key_id),
                    )
                    self._audit(conn, key_id, "key_banned", "admin", reason or "policy violation")
            elif action == "refund":
                if current != "refunded":
                    if current not in {"active", "refund_requested", "banned"}:
                        raise ControlError(409, "INVALID_STATE", f"refund cannot be completed from {current}")
                    conn.execute(
                        "update license_keys set status='refunded',revoked_at=?,revoke_reason=? where id=?",
                        (now, reason or "refund completed", key_id),
                    )
                    self._audit(conn, key_id, "refund_completed", "admin", reason or "refund completed")
            elif action == "restore":
                if current not in {"banned", "refund_requested"}:
                    raise ControlError(409, "INVALID_STATE", f"key cannot be restored from {current}")
                target = "active" if row["install_id"] else "unused"
                conn.execute(
                    "update license_keys set status=?,revoked_at=null,revoke_reason='' where id=?",
                    (target, key_id),
                )
                self._audit(conn, key_id, "key_restored", "admin", reason, {"status": target})
            elif action == "reset-binding":
                if current not in {"active", "banned"}:
                    raise ControlError(409, "INVALID_STATE", f"binding cannot be reset from {current}")
                conn.execute(
                    """update license_keys set status='unused',activated_at=null,refund_deadline=null,install_id=null,
                    device_public_key=null,activation_token_hash=null,last_seen_at=null,revoked_at=null,revoke_reason='' where id=?""",
                    (key_id,),
                )
                self._audit(conn, key_id, "binding_reset", "admin", reason or "installation replacement")
            else:
                raise ControlError(404, "UNKNOWN_ACTION", "unknown admin action")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return {"ok": True, "key": self.get_key(key_id)}

    def checkout_config(self) -> dict[str, Any]:
        return {
            "ok": True,
            "product": {
                "id": self.product_id,
                "name": "Lab Factory 抢先体验",
                "amount_cents": self.price_cents,
                "currency": "CNY",
                "refund_days": self.refund_days,
                "self_service_refunds": False,
                "refund_policy": "数字化商品密钥交付后原则上不支持无理由退款；重复付款、无法激活且无法修复、重大功能缺陷或法律另有规定的情形，请联系售后人工处理。",
                "entitlement": "体验版可生成 3 份报告，不包含 Skill 凝练",
            },
            "plans": [
                {"id": PLAN_EXPERIENCE, "name": "体验版", "amount_cents": self.price_cents,
                 "usage_limit": 3, "skill_condensation": False},
                {"id": PLAN_PERMANENT, "name": "永久版", "amount_cents": self.permanent_price_cents,
                 "usage_limit": None, "skill_condensation": True},
            ],
            "payment_providers": [provider.public_config() for provider in self.payment_providers.values()],
            "support_contact": self.support_contact,
            "delivery_commitment": "人工核款确认后，订单页自动显示激活密钥",
        }

    @staticmethod
    def _mask_contact(contact: str) -> str:
        if len(contact) <= 4:
            return "••••" if contact else ""
        return contact[:2] + "••••" + contact[-2:]

    def _order_row(self, conn: sqlite3.Connection, order_id: str) -> sqlite3.Row:
        row = conn.execute("select * from orders where id=?", (order_id,)).fetchone()
        if not row:
            raise ControlError(404, "ORDER_NOT_FOUND", "order not found")
        return row

    def _order_value(self, row: sqlite3.Row, *, public: bool) -> dict[str, Any]:
        hidden = {"status_token_hash"}
        value = {key: row[key] for key in row.keys() if key not in hidden}
        if public:
            value["contact"] = self._mask_contact(str(row["contact"]))
            value.pop("admin_reason", None)
        if row["license_key_id"]:
            with self.connection() as conn:
                key = conn.execute(
                    "select status,key_suffix,refund_deadline,activated_at from license_keys where id=?",
                    (row["license_key_id"],),
                ).fetchone()
            if key:
                value["license"] = {
                    "status": key["status"],
                    "key_suffix": key["key_suffix"],
                    "refund_deadline": key["refund_deadline"],
                    "activated_at": key["activated_at"],
                }
        if public and row["status"] == "delivered" and row["delivery_key_version"] == "derived-v1":
            value["activation_key"] = self._order_activation_key(str(row["id"]))
        return value

    def create_order(self, *, contact: str, payment_provider: str, plan: str = PLAN_EXPERIENCE) -> dict[str, Any]:
        contact = bounded_text(contact, "contact", 160, required=True)
        payment_provider = bounded_text(payment_provider, "payment_provider", 40, required=True)
        provider = self.payment_providers.get(payment_provider)
        plan = bounded_text(plan, "plan", 32, required=True)
        if plan not in LICENSE_PLANS:
            raise ControlError(400, "INVALID_PLAN", "plan must be experience or permanent")
        if not provider or not provider.public_config().get("available"):
            raise ControlError(400, "PAYMENT_PROVIDER_UNAVAILABLE", "selected payment provider is unavailable")
        order_id = "lforder_" + uuid.uuid4().hex
        status_token = secrets.token_urlsafe(32)
        now = utc_now()
        with self.connection() as conn:
            with conn:
                conn.execute(
                    """insert into orders
                    (id,status_token_hash,status,product_id,amount_cents,currency,payment_provider,contact,refund_days,created_at,updated_at,plan)
                    values(?,?,'payment_pending',?,?,?,?,?,?,?,?,?)""",
                    (
                        order_id, token_hash(status_token), self.product_id,
                        self.price_cents if plan == PLAN_EXPERIENCE else self.permanent_price_cents, "CNY",
                        payment_provider, contact, self.refund_days, now, now, plan,
                    ),
                )
                self._order_audit(conn, order_id, "order_created", "customer", metadata={"provider": payment_provider, "plan": plan})
        return {
            "ok": True,
            "status_token": status_token,
            "status_url": f"/buy#order={status_token}",
            "order": self.get_order_by_token(status_token),
        }

    def _order_by_token(self, conn: sqlite3.Connection, status_token: str) -> sqlite3.Row:
        status_token = bounded_text(status_token, "status_token", 128, required=True)
        row = conn.execute("select * from orders where status_token_hash=?", (token_hash(status_token),)).fetchone()
        if not row:
            raise ControlError(404, "ORDER_NOT_FOUND", "order token is invalid")
        return row

    def get_order_by_token(self, status_token: str) -> dict[str, Any]:
        with self.connection() as conn:
            row = self._order_by_token(conn, status_token)
        return self._order_value(row, public=True)

    def submit_payment(self, status_token: str, *, reference: str, paid_at: str) -> dict[str, Any]:
        reference = bounded_text(reference, "payment_reference", 120, required=True)
        paid_at = bounded_text(paid_at, "paid_at", 64, required=True)
        conn = self.connect()
        try:
            conn.execute("begin immediate")
            row = self._order_by_token(conn, status_token)
            provider = self.payment_providers.get(str(row["payment_provider"]))
            if not provider:
                raise ControlError(409, "PAYMENT_PROVIDER_UNAVAILABLE", "payment provider is no longer available")
            try:
                provider.validate_submission(reference, paid_at)
            except ValueError as exc:
                raise ControlError(400, "INVALID_PAYMENT_SUBMISSION", str(exc)) from exc
            current = str(row["status"])
            if current == "payment_submitted":
                if row["payment_reference"] != reference or row["payment_claimed_at"] != paid_at:
                    raise ControlError(409, "PAYMENT_ALREADY_SUBMITTED", "payment details were already submitted")
            elif current not in {"payment_pending", "payment_rejected"}:
                raise ControlError(409, "INVALID_STATE", f"payment cannot be submitted from {current}")
            else:
                now = utc_now()
                conn.execute(
                    """update orders set status='payment_submitted',payment_reference=?,payment_claimed_at=?,
                    updated_at=?,admin_reason='' where id=?""",
                    (reference, paid_at, now, row["id"]),
                )
                self._order_audit(conn, row["id"], "payment_submitted", "customer", metadata={"paid_at": paid_at})
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return {"ok": True, "order": self.get_order_by_token(status_token)}

    def request_order_refund(self, status_token: str, *, reason: str = "") -> dict[str, Any]:
        bounded_text(reason, "reason", 500)
        with self.connection() as conn:
            self._order_by_token(conn, status_token)
        raise ControlError(
            409,
            "SELF_SERVICE_REFUND_UNAVAILABLE",
            "数字化商品交付后不提供自助无理由退款。重复付款、无法激活或重大功能故障请联系售后QQ群 923937311 处理。",
        )

    def list_orders(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if status and status not in ORDER_STATES:
            raise ControlError(400, "INVALID_STATUS", "unknown order status")
        limit = max(1, min(limit, 500))
        query, values = "select * from orders", []
        if status:
            query += " where status=?"
            values.append(status)
        query += " order by created_at desc limit ?"
        values.append(limit)
        with self.connection() as conn:
            rows = conn.execute(query, values).fetchall()
        return [self._order_value(row, public=False) for row in rows]

    def get_order(self, order_id: str) -> dict[str, Any]:
        with self.connection() as conn:
            row = self._order_row(conn, order_id)
            events = conn.execute(
                "select id,event,actor,reason,metadata_json,created_at from order_audit_events where order_id=? order by created_at desc limit 100",
                (order_id,),
            ).fetchall()
        value = self._order_value(row, public=False)
        value["audit_events"] = [
            {
                "id": event["id"], "event": event["event"], "actor": event["actor"],
                "reason": event["reason"], "metadata": json.loads(event["metadata_json"]),
                "created_at": event["created_at"],
            }
            for event in events
        ]
        return value

    def admin_order_action(self, order_id: str, action: str, reason: str = "") -> dict[str, Any]:
        reason = bounded_text(reason, "reason", 500)
        plaintext_key = ""
        conn = self.connect()
        try:
            conn.execute("begin immediate")
            row = self._order_row(conn, order_id)
            current, now = str(row["status"]), utc_now()
            if action == "confirm-and-deliver":
                if current == "delivered" and row["delivery_key_version"] == "derived-v1":
                    pass
                elif current != "payment_submitted":
                    raise ControlError(409, "INVALID_STATE", f"order cannot be auto-delivered from {current}")
                else:
                    plaintext_key = self._order_activation_key(order_id)
                    key_id = self._order_license_key_id(order_id)
                    conn.execute(
                        """insert into license_keys
                        (id,key_hash,key_suffix,status,label,customer_ref,refund_days,product_id,created_at,sent_at,plan,usage_limit)
                        values(?,?,?,'unused','购买页自动发货',?,?,?,?,?,?,?)""",
                        (
                            key_id, self._key_hash(plaintext_key), plaintext_key[-4:], order_id,
                            int(row["refund_days"]), self.product_id, now, now,
                            str(row["plan"]), 3 if row["plan"] == PLAN_EXPERIENCE else None,
                        ),
                    )
                    conn.execute(
                        """update orders set status='delivered',paid_at=?,delivered_at=?,updated_at=?,admin_reason='',
                        license_key_id=?,delivery_key_version='derived-v1' where id=? and status='payment_submitted'""",
                        (now, now, now, key_id, order_id),
                    )
                    self._audit(conn, key_id, "key_created", "admin", "semi-automatic order delivery", {"refund_days": row["refund_days"], "plan": row["plan"]})
                    self._audit(conn, key_id, "key_sent", "system", "displayed on authenticated order page")
                    self._order_audit(conn, order_id, "payment_confirmed", "admin", reason)
                    self._order_audit(conn, order_id, "key_issued", "system", "semi-automatic delivery", {"license_key_id": key_id})
                    self._order_audit(conn, order_id, "order_delivered", "system", "activation key available on authenticated order page")
            elif action == "confirm-payment":
                if current in {"paid", "key_issued", "delivered", "refund_requested", "refunded"}:
                    pass
                elif current != "payment_submitted":
                    raise ControlError(409, "INVALID_STATE", f"payment cannot be confirmed from {current}")
                else:
                    conn.execute("update orders set status='paid',paid_at=?,updated_at=?,admin_reason='' where id=?", (now, now, order_id))
                    self._order_audit(conn, order_id, "payment_confirmed", "admin", reason)
            elif action == "reject-payment":
                if current == "payment_rejected":
                    pass
                elif current != "payment_submitted":
                    raise ControlError(409, "INVALID_STATE", f"payment cannot be rejected from {current}")
                else:
                    conn.execute(
                        "update orders set status='payment_rejected',updated_at=?,admin_reason=? where id=?",
                        (now, reason or "payment could not be verified", order_id),
                    )
                    self._order_audit(conn, order_id, "payment_rejected", "admin", reason or "payment could not be verified")
            elif action == "issue":
                if current in {"key_issued", "delivered", "refund_requested", "refunded"}:
                    pass
                elif current != "paid":
                    raise ControlError(409, "INVALID_STATE", f"key cannot be issued from {current}")
                else:
                    plaintext_key, key_id = self._insert_key(
                        conn, label="购买页订单", customer_ref=order_id, refund_days=int(row["refund_days"]), plan=str(row["plan"])
                    )
                    conn.execute(
                        "update orders set status='key_issued',license_key_id=?,updated_at=? where id=?",
                        (key_id, now, order_id),
                    )
                    self._order_audit(conn, order_id, "key_issued", "admin", metadata={"license_key_id": key_id})
            elif action == "deliver":
                if current == "delivered":
                    pass
                elif current != "key_issued":
                    raise ControlError(409, "INVALID_STATE", f"order cannot be delivered from {current}")
                else:
                    conn.execute("update orders set status='delivered',delivered_at=?,updated_at=? where id=?", (now, now, order_id))
                    if row["license_key_id"]:
                        key = conn.execute("select sent_at from license_keys where id=?", (row["license_key_id"],)).fetchone()
                        if key and not key["sent_at"]:
                            conn.execute("update license_keys set sent_at=? where id=?", (now, row["license_key_id"]))
                            self._audit(conn, row["license_key_id"], "key_sent", "admin", "via order delivery")
                    self._order_audit(conn, order_id, "order_delivered", "admin", reason)
            elif action == "refund":
                if current == "refunded":
                    pass
                elif current not in {"paid", "key_issued", "delivered", "refund_requested"}:
                    raise ControlError(409, "INVALID_STATE", f"refund cannot be completed from {current}")
                else:
                    conn.execute(
                        "update orders set status='refunded',refunded_at=?,updated_at=?,admin_reason=? where id=?",
                        (now, now, reason or "original-route refund completed", order_id),
                    )
                    if row["license_key_id"]:
                        conn.execute(
                            "update license_keys set status='refunded',revoked_at=?,revoke_reason=? where id=?",
                            (now, reason or "original-route refund completed", row["license_key_id"]),
                        )
                        self._audit(conn, row["license_key_id"], "refund_completed", "admin", reason or "original-route refund completed")
                    self._order_audit(conn, order_id, "refund_completed", "admin", reason or "original-route refund completed")
            else:
                raise ControlError(404, "UNKNOWN_ACTION", "unknown order action")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        result = {"ok": True, "order": self.get_order(order_id)}
        if plaintext_key and action != "confirm-and-deliver":
            result.update({
                "activation_key": plaintext_key,
                "warning": "明文密钥只返回这一次，请发送后立即标记订单已交付。",
            })
        return result

    def purge_expired_order_personal_data(self, retention_days: int = 90) -> dict[str, Any]:
        if retention_days < 30 or retention_days > 365:
            raise ControlError(400, "INVALID_RETENTION", "retention_days must be between 30 and 365")
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).replace(microsecond=0).isoformat()
        with self.connection() as conn:
            with conn:
                rows = conn.execute(
                    """select id from orders where (contact!='' or payment_reference!='' or payment_claimed_at is not null)
                    and ((status in ('delivered','refunded') and coalesce(refunded_at,delivered_at,updated_at)<=?)
                    or (status in ('payment_pending','payment_rejected') and created_at<=?))""",
                    (cutoff, cutoff),
                ).fetchall()
                for row in rows:
                    conn.execute(
                        "update orders set contact='',payment_reference='',payment_claimed_at=null,updated_at=? where id=?",
                        (utc_now(), row["id"]),
                    )
                    self._order_audit(conn, row["id"], "personal_data_purged", "admin", metadata={"retention_days": retention_days})
        return {"ok": True, "purged_orders": len(rows), "cutoff": cutoff}


class Handler(BaseHTTPRequestHandler):
    store: ControlStore
    admin_token: str
    payment_assets: dict[str, Path] = {}

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_static(self, path: Path, content_type: str) -> None:
        if not path.is_file() or path.parent not in {CONTROL_UI_DIR, PURCHASE_UI_DIR}:
            raise ControlError(404, "NOT_FOUND", "not found")
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self'; object-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_payment_asset(self, provider_id: str) -> None:
        path = self.payment_assets.get(provider_id)
        if not path or not path.is_file():
            raise ControlError(404, "PAYMENT_ASSET_NOT_FOUND", "payment asset is not configured")
        content_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
        content_type = content_types.get(path.suffix.lower())
        if not content_type:
            raise ControlError(415, "UNSUPPORTED_PAYMENT_ASSET", "payment asset must be PNG, JPEG, or WebP")
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "private, max-age=300")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ControlError(400, "INVALID_LENGTH", "invalid Content-Length") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise ControlError(413, "BODY_TOO_LARGE", "request body is too large")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8") if length else "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ControlError(400, "INVALID_JSON", "request body must be a JSON object") from exc
        if not isinstance(value, dict):
            raise ControlError(400, "INVALID_JSON", "request body must be a JSON object")
        return value

    def require_admin(self) -> None:
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not self.admin_token or not hmac.compare_digest(supplied, self.admin_token):
            raise ControlError(401, "ADMIN_AUTH_REQUIRED", "valid administrator token required")

    def require_order_token(self) -> str:
        token = self.headers.get("X-Order-Token", "").strip()
        if not token:
            raise ControlError(401, "ORDER_TOKEN_REQUIRED", "order token is required")
        return token

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlsplit(self.path)
            if parsed.path in {"/", "/buy", "/buy/"}:
                self.send_static(PURCHASE_UI_DIR / "index.html", "text/html; charset=utf-8")
                return
            if parsed.path == "/buy/purchase.css":
                self.send_static(PURCHASE_UI_DIR / "purchase.css", "text/css; charset=utf-8")
                return
            if parsed.path == "/buy/purchase.js":
                self.send_static(PURCHASE_UI_DIR / "purchase.js", "text/javascript; charset=utf-8")
                return
            if parsed.path == "/payment-assets/alipay":
                self.send_payment_asset("alipay")
                return
            if parsed.path in {"/admin", "/admin/"}:
                self.send_static(CONTROL_UI_DIR / "index.html", "text/html; charset=utf-8")
                return
            if parsed.path == "/admin/control.css":
                self.send_static(CONTROL_UI_DIR / "control.css", "text/css; charset=utf-8")
                return
            if parsed.path == "/admin/control.js":
                self.send_static(CONTROL_UI_DIR / "control.js", "text/javascript; charset=utf-8")
                return
            if parsed.path == "/health":
                self.send_json(200, {"ok": True, "service": "lab-factory-license-control", "time": utc_now()})
                return
            if parsed.path == "/api/checkout/config":
                self.send_json(200, self.store.checkout_config())
                return
            if parsed.path == "/api/order":
                self.send_json(200, {"ok": True, "order": self.store.get_order_by_token(self.require_order_token())})
                return
            if parsed.path == "/admin/orders":
                self.require_admin()
                query = parse_qs(parsed.query)
                status = query.get("status", [None])[0]
                limit = int(query.get("limit", ["100"])[0])
                self.send_json(200, {"ok": True, "orders": self.store.list_orders(status, limit)})
                return
            if parsed.path.startswith("/admin/orders/"):
                self.require_admin()
                order_id = parsed.path.removeprefix("/admin/orders/").strip("/")
                if "/" in order_id:
                    raise ControlError(404, "NOT_FOUND", "not found")
                self.send_json(200, {"ok": True, "order": self.store.get_order(order_id)})
                return
            if parsed.path == "/admin/keys":
                self.require_admin()
                query = parse_qs(parsed.query)
                status = query.get("status", [None])[0]
                limit = int(query.get("limit", ["100"])[0])
                self.send_json(200, {"ok": True, "keys": self.store.list_keys(status, limit)})
                return
            if parsed.path.startswith("/admin/keys/"):
                self.require_admin()
                key_id = parsed.path.removeprefix("/admin/keys/").strip("/")
                if "/" in key_id:
                    raise ControlError(404, "NOT_FOUND", "not found")
                self.send_json(200, {"ok": True, "key": self.store.get_key(key_id)})
                return
            raise ControlError(404, "NOT_FOUND", "not found")
        except ControlError as exc:
            self.send_json(exc.status, {"ok": False, "error": {"code": exc.code, "message": str(exc)}})
        except Exception:
            self.send_json(500, {"ok": False, "error": {"code": "INTERNAL_ERROR", "message": "internal server error"}})

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlsplit(self.path)
            payload = self.read_json()
            if parsed.path == "/api/orders":
                result = self.store.create_order(
                    contact=bounded_text(payload.get("contact"), "contact", 160, required=True),
                    payment_provider=bounded_text(payload.get("payment_provider"), "payment_provider", 40, required=True),
                    plan=bounded_text(payload.get("plan", PLAN_EXPERIENCE), "plan", 32, required=True),
                )
                self.send_json(201, result)
                return
            if parsed.path == "/api/order/payment":
                self.send_json(200, self.store.submit_payment(
                    self.require_order_token(),
                    reference=bounded_text(payload.get("payment_reference"), "payment_reference", 120, required=True),
                    paid_at=bounded_text(payload.get("paid_at"), "paid_at", 64, required=True),
                ))
                return
            if parsed.path == "/api/order/refund":
                self.send_json(200, self.store.request_order_refund(
                    self.require_order_token(),
                    reason=bounded_text(payload.get("reason"), "reason", 500),
                ))
                return
            if parsed.path == "/api/activate":
                result = self.store.activate(
                    str(payload.get("activation_key", "")),
                    str(payload.get("install_id", "")),
                    str(payload.get("device_public_key", "")),
                )
                self.send_json(200, result)
                return
            if parsed.path == "/api/lease/refresh":
                self.send_json(200, self.store.refresh(payload))
                return
            if parsed.path == "/api/usage/consume":
                self.send_json(200, self.store.consume_usage(payload))
                return
            if parsed.path == "/api/refunds/request":
                self.send_json(200, self.store.request_refund(payload))
                return
            if parsed.path == "/admin/keys":
                self.require_admin()
                result = self.store.create_key(
                    label=bounded_text(payload.get("label"), "label", 120),
                    customer_ref=bounded_text(payload.get("customer_ref"), "customer_ref", 120),
                    refund_days=int(payload.get("refund_days", 7)),
                    plan=bounded_text(payload.get("plan", PLAN_PERMANENT), "plan", 32, required=True),
                )
                self.send_json(201, result)
                return
            if parsed.path == "/admin/orders/purge-personal-data":
                self.require_admin()
                self.send_json(200, self.store.purge_expired_order_personal_data(int(payload.get("retention_days", 90))))
                return
            if parsed.path.startswith("/admin/orders/"):
                self.require_admin()
                parts = parsed.path.strip("/").split("/")
                if len(parts) != 4 or parts[:2] != ["admin", "orders"]:
                    raise ControlError(404, "NOT_FOUND", "not found")
                self.send_json(200, self.store.admin_order_action(
                    parts[2], parts[3], bounded_text(payload.get("reason"), "reason", 500)
                ))
                return
            if parsed.path.startswith("/admin/keys/"):
                self.require_admin()
                parts = parsed.path.strip("/").split("/")
                if len(parts) != 4 or parts[:2] != ["admin", "keys"]:
                    raise ControlError(404, "NOT_FOUND", "not found")
                key_id, action = parts[2], parts[3]
                if action == "mark-sent":
                    result = self.store.mark_sent(key_id)
                else:
                    result = self.store.admin_action(
                        key_id,
                        action,
                        bounded_text(payload.get("reason"), "reason", 500),
                    )
                self.send_json(200, result)
                return
            raise ControlError(404, "NOT_FOUND", "not found")
        except ControlError as exc:
            self.send_json(exc.status, {"ok": False, "error": {"code": exc.code, "message": str(exc)}})
        except (TypeError, ValueError) as exc:
            self.send_json(400, {"ok": False, "error": {"code": "INVALID_REQUEST", "message": str(exc)}})
        except Exception:
            self.send_json(500, {"ok": False, "error": {"code": "INTERNAL_ERROR", "message": "internal server error"}})


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Lab Factory license control plane")
    parser.add_argument("--host", default=os.environ.get("LAB_CONTROL_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LAB_CONTROL_PORT", "8765")))
    parser.add_argument("--db", default=os.environ.get("LAB_CONTROL_DB", "lab-license-control.sqlite3"))
    parser.add_argument("--lease-private-key", default=os.environ.get("LAB_CONTROL_LEASE_PRIVATE_KEY", ""))
    parser.add_argument("--admin-token", default=os.environ.get("LAB_CONTROL_ADMIN_TOKEN", ""))
    parser.add_argument("--key-pepper", default=os.environ.get("LAB_CONTROL_KEY_PEPPER", ""))
    parser.add_argument("--token-secret", default=os.environ.get("LAB_CONTROL_TOKEN_SECRET", ""))
    parser.add_argument("--product-id", default=os.environ.get("LAB_FACTORY_PRODUCT_ID", "lab-factory-1"))
    parser.add_argument("--price-cents", type=int, default=int(os.environ.get("LAB_CONTROL_PRICE_CENTS", "990")))
    parser.add_argument("--permanent-price-cents", type=int, default=int(os.environ.get("LAB_CONTROL_PERMANENT_PRICE_CENTS", "4990")))
    parser.add_argument("--refund-days", type=int, choices=[3, 7], default=int(os.environ.get("LAB_CONTROL_REFUND_DAYS", "7")))
    parser.add_argument("--support-contact", default=os.environ.get("LAB_CONTROL_SUPPORT_CONTACT", "售后QQ群：923937311"))
    args = parser.parse_args()
    if not args.admin_token or len(args.admin_token) < 32:
        parser.error("--admin-token / LAB_CONTROL_ADMIN_TOKEN must contain at least 32 characters")
    if not args.lease_private_key:
        parser.error("--lease-private-key / LAB_CONTROL_LEASE_PRIVATE_KEY is required")
    if len(args.key_pepper) < 32:
        parser.error("--key-pepper / LAB_CONTROL_KEY_PEPPER must contain at least 32 characters")
    if len(args.token_secret) < 32:
        parser.error("--token-secret / LAB_CONTROL_TOKEN_SECRET must contain at least 32 characters")
    alipay_qr_path_value = os.environ.get("LAB_CONTROL_ALIPAY_QR_PATH", "").strip()
    alipay_qr_path = Path(alipay_qr_path_value).expanduser().resolve() if alipay_qr_path_value else None
    if alipay_qr_path and (not alipay_qr_path.is_file() or alipay_qr_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}):
        parser.error("LAB_CONTROL_ALIPAY_QR_PATH must point to an existing PNG, JPEG, or WebP file")
    payment_providers: dict[str, PaymentProvider] = {
        "alipay": ManualPaymentProvider(
            "alipay", "支付宝经营码",
            os.environ.get("LAB_CONTROL_ALIPAY_URL", ""),
            os.environ.get("LAB_CONTROL_ALIPAY_INSTRUCTIONS", ""),
            "/payment-assets/alipay" if alipay_qr_path else "",
        ),
        "wechat": ManualPaymentProvider(
            "wechat", "微信经营收款",
            os.environ.get("LAB_CONTROL_WECHAT_URL", ""),
            os.environ.get("LAB_CONTROL_WECHAT_INSTRUCTIONS", ""),
        ),
        "paddle": PaddlePaymentProvider(),
    }
    Handler.store = ControlStore(
        Path(args.db).expanduser().resolve(),
        key_pepper=args.key_pepper,
        token_secret=args.token_secret,
        lease_private_key=Path(args.lease_private_key).expanduser().resolve(),
        product_id=args.product_id,
        price_cents=args.price_cents,
        permanent_price_cents=args.permanent_price_cents,
        refund_days=args.refund_days,
        payment_providers=payment_providers,
        support_contact=args.support_contact,
    )
    Handler.admin_token = args.admin_token
    Handler.payment_assets = {"alipay": alipay_qr_path} if alipay_qr_path else {}
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Lab Factory license control listening on http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
