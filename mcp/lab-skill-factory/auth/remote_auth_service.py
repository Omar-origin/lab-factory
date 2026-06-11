#!/usr/bin/env python3
"""Minimal remote activation service for Lab Skill Factory beta.

This is a small stdlib HTTP service for free beta testing. Put it behind HTTPS
in production (for example through Caddy, Nginx, Cloudflare Tunnel, or a PaaS).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def code_hash(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def parse_expiry(value: str | None) -> datetime | None:
    if not value:
        return None
    if len(value) == 10:
        value = f"{value}T23:59:59+00:00"
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class AuthStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                create table if not exists activation_codes (
                  code_hash text primary key,
                  label text,
                  expires_at text,
                  max_devices integer not null default 1,
                  created_at text not null
                );
                create table if not exists activations (
                  token text primary key,
                  code_hash text not null,
                  device_id text not null,
                  product_id text not null,
                  customer_id text,
                  status text not null,
                  activated_at text not null,
                  last_seen_at text not null,
                  unique(code_hash, device_id, product_id)
                );
                """
            )

    def create_code(self, activation_code: str, label: str | None, expires_at: str | None, max_devices: int) -> dict:
        hashed = code_hash(activation_code)
        with self.connection() as conn:
            conn.execute(
                """
                insert or replace into activation_codes
                (code_hash, label, expires_at, max_devices, created_at)
                values (?, ?, ?, ?, ?)
                """,
                (hashed, label, expires_at, max_devices, utc_now()),
            )
        return {"ok": True, "sha256": hashed, "label": label, "expires_at": expires_at, "max_devices": max_devices}

    def activate(self, activation_code: str, device_id: str, product_id: str, customer_id: str | None) -> dict:
        hashed = code_hash(activation_code)
        with self.connection() as conn:
            code = conn.execute("select * from activation_codes where code_hash = ?", (hashed,)).fetchone()
            if not code:
                return {"ok": False, "error": "invalid activation code"}
            expiry = parse_expiry(code["expires_at"])
            if expiry and expiry < datetime.now(timezone.utc):
                return {"ok": False, "error": "activation code expired"}
            existing = conn.execute(
                """
                select * from activations
                where code_hash = ? and device_id = ? and product_id = ? and status = 'ACTIVE'
                """,
                (hashed, device_id, product_id),
            ).fetchone()
            if existing:
                conn.execute("update activations set last_seen_at = ? where token = ?", (utc_now(), existing["token"]))
                return {"ok": True, "token": existing["token"], "expires_at": code["expires_at"]}
            count = conn.execute(
                """
                select count(distinct device_id) as count
                from activations
                where code_hash = ? and product_id = ? and status = 'ACTIVE'
                """,
                (hashed, product_id),
            ).fetchone()["count"]
            if count >= int(code["max_devices"]):
                return {"ok": False, "error": "device limit reached"}
            token = secrets.token_urlsafe(32)
            conn.execute(
                """
                insert into activations
                (token, code_hash, device_id, product_id, customer_id, status, activated_at, last_seen_at)
                values (?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
                """,
                (token, hashed, device_id, product_id, customer_id, utc_now(), utc_now()),
            )
            return {"ok": True, "token": token, "expires_at": code["expires_at"]}

    def verify(self, token: str, device_id: str, product_id: str) -> dict:
        with self.connection() as conn:
            row = conn.execute("select * from activations where token = ?", (token,)).fetchone()
            if not row:
                return {"ok": False, "error": "unknown token"}
            if row["status"] != "ACTIVE":
                return {"ok": False, "error": "license is not active"}
            if row["device_id"] != device_id or row["product_id"] != product_id:
                return {"ok": False, "error": "license does not match this device or product"}
            code = conn.execute("select * from activation_codes where code_hash = ?", (row["code_hash"],)).fetchone()
            if not code:
                return {"ok": False, "error": "activation code was removed"}
            expiry = parse_expiry(code["expires_at"])
            if expiry and expiry < datetime.now(timezone.utc):
                return {"ok": False, "error": "license expired"}
            conn.execute("update activations set last_seen_at = ? where token = ?", (utc_now(), token))
            return {
                "ok": True,
                "status": "ACTIVE",
                "label": code["label"],
                "expires_at": code["expires_at"],
                "last_seen_at": utc_now(),
            }


class Handler(BaseHTTPRequestHandler):
    store: AuthStore
    admin_token: str

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length).decode("utf-8") if length else "{}"
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def require_admin(self) -> bool:
        token = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not self.admin_token or token != self.admin_token:
            self.send_json(401, {"ok": False, "error": "admin token required"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self.send_json(200, {"ok": True, "service": "lab-skill-factory-auth", "time": utc_now()})
            return
        self.send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            payload = self.read_json()
            if self.path == "/activate":
                result = self.store.activate(
                    str(payload.get("activation_code", "")),
                    str(payload.get("device_id", "")),
                    str(payload.get("product_id", "")),
                    payload.get("customer_id") if isinstance(payload.get("customer_id"), str) else None,
                )
                self.send_json(200 if result.get("ok") else 400, result)
                return
            if self.path == "/verify":
                result = self.store.verify(
                    str(payload.get("token", "")),
                    str(payload.get("device_id", "")),
                    str(payload.get("product_id", "")),
                )
                self.send_json(200 if result.get("ok") else 403, result)
                return
            if self.path == "/admin/create-code":
                if not self.require_admin():
                    return
                result = self.store.create_code(
                    str(payload.get("activation_code", "")),
                    payload.get("label") if isinstance(payload.get("label"), str) else None,
                    payload.get("expires_at") if isinstance(payload.get("expires_at"), str) else None,
                    int(payload.get("max_devices", 1)),
                )
                self.send_json(200, result)
                return
            self.send_json(404, {"ok": False, "error": "not found"})
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Lab Skill Factory remote activation service.")
    parser.add_argument("--host", default=os.environ.get("LAB_AUTH_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LAB_AUTH_PORT", "8765")))
    parser.add_argument("--db", default=os.environ.get("LAB_AUTH_DB", "lab-auth.sqlite3"))
    parser.add_argument("--admin-token", default=os.environ.get("LAB_AUTH_ADMIN_TOKEN", ""))
    args = parser.parse_args()

    Handler.store = AuthStore(Path(args.db).expanduser().resolve())
    Handler.admin_token = args.admin_token
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Lab auth service listening on http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
