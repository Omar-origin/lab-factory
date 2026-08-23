#!/usr/bin/env python3
"""End-to-end test for the Cloudflare commercial Worker."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

MCP_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MCP_DIR))

from lease_crypto import create_device_key, sign_device_message, utc_now, verify_lease


def call(base: str, method: str, path: str, payload: dict | None = None, headers: dict | None = None) -> tuple[int, dict | bytes]:
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            if response.headers.get_content_type().startswith("image/"):
                return response.status, raw
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    base = os.environ.get("LAB_WORKER_TEST_URL", "http://127.0.0.1:8787")
    admin = os.environ.get("LAB_CONTROL_ADMIN_TOKEN", "")
    check(len(admin) >= 32, "LAB_CONTROL_ADMIN_TOKEN is required")
    admin_headers = {"Authorization": f"Bearer {admin}"}
    tests = 0

    status, health = call(base, "GET", "/health")
    check(status == 200 and health["ok"], "health check failed")
    tests += 1
    status, config = call(base, "GET", "/api/checkout/config")
    check(status == 200 and [item["id"] for item in config["payment_providers"] if item["available"]] == ["alipay"], "checkout providers are wrong")
    check(config["support_contact"] == "售后QQ群：923937311", "support contact is wrong")
    tests += 1
    status, qr = call(base, "GET", "/payment-assets/alipay.png")
    check(status == 200 and isinstance(qr, bytes) and len(qr) > 1000, "Alipay QR asset failed")
    tests += 1

    status, created = call(base, "POST", "/api/orders", {"contact": "worker-test@example.test", "payment_provider": "alipay"})
    check(status == 201 and created["order"]["status"] == "payment_pending", "order creation failed")
    token = created["status_token"]
    order_id = created["order"]["id"]
    order_headers = {"X-Order-Token": token}
    tests += 1
    submission = {"payment_reference": "worker-test-trade", "paid_at": "2026-08-23T12:00"}
    status, submitted = call(base, "POST", "/api/order/payment", submission, order_headers)
    check(status == 200 and submitted["order"]["status"] == "payment_submitted", "payment submission failed")
    status, repeated = call(base, "POST", "/api/order/payment", submission, order_headers)
    check(status == 200 and repeated["order"]["status"] == "payment_submitted", "payment submission was not idempotent")
    tests += 1

    status, confirmed = call(base, "POST", f"/admin/orders/{order_id}/confirm-payment", {"reason": "worker test"}, admin_headers)
    check(status == 200 and confirmed["order"]["status"] == "paid", "payment confirmation failed")
    tests += 1
    status, issued = call(base, "POST", f"/admin/orders/{order_id}/issue", {}, admin_headers)
    check(status == 200 and issued["activation_key"].startswith("LF-"), "key issue failed")
    activation_key = issued["activation_key"]
    status, issued_again = call(base, "POST", f"/admin/orders/{order_id}/issue", {}, admin_headers)
    check(status == 200 and "activation_key" not in issued_again, "duplicate issue returned/generated plaintext")
    tests += 1
    status, delivered = call(base, "POST", f"/admin/orders/{order_id}/deliver", {"reason": "worker test delivery"}, admin_headers)
    check(status == 200 and delivered["order"]["status"] == "delivered", "delivery failed")
    tests += 1

    device = create_device_key()
    install_id = "install_worker_test"
    status, activated = call(base, "POST", "/api/activate", {
        "activation_key": activation_key,
        "install_id": install_id,
        "device_public_key": device["public_key"],
    })
    check(status == 200 and activated["status"] == "active", f"activation failed: {activated}")
    public_record = json.loads((MCP_DIR / "lease_public_key.json").read_text())
    verify_lease(activated["lease"], public_record, install_id=install_id, product_id="lab-factory-1")
    tests += 1

    proof = {"action": "refresh", "activation_token": activated["activation_token"], "install_id": install_id, "timestamp": utc_now(), "nonce": "worker-refresh-1"}
    status, refreshed = call(base, "POST", "/api/lease/refresh", {
        "activation_token": activated["activation_token"], "proof": proof, "signature": sign_device_message(device, proof),
    })
    check(status == 200 and refreshed["status"] == "active", f"lease refresh failed: {refreshed}")
    verify_lease(refreshed["lease"], public_record, install_id=install_id, product_id="lab-factory-1")
    tests += 1

    status, refund = call(base, "POST", "/api/order/refund", {"reason": "worker test refund"}, order_headers)
    check(status == 200 and refund["order"]["status"] == "refund_requested", "refund request failed")
    tests += 1
    blocked_proof = {"action": "refresh", "activation_token": activated["activation_token"], "install_id": install_id, "timestamp": utc_now(), "nonce": "worker-refresh-blocked"}
    status, blocked = call(base, "POST", "/api/lease/refresh", {
        "activation_token": activated["activation_token"], "proof": blocked_proof, "signature": sign_device_message(device, blocked_proof),
    })
    check(status == 403 and blocked["error"]["code"] == "KEY_BLOCKED", "refund did not block lease refresh")
    tests += 1
    status, refunded = call(base, "POST", f"/admin/orders/{order_id}/refund", {"reason": "test original-route refund"}, admin_headers)
    check(status == 200 and refunded["order"]["status"] == "refunded" and refunded["order"]["license"]["status"] == "refunded", "completed refund did not revoke key")
    tests += 1

    print(json.dumps({"ok": True, "tests": tests, "base_url": base}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
