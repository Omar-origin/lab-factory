#!/usr/bin/env python3
"""End-to-end regression tests for online key binding, leases, refunds, and bans."""

from __future__ import annotations

import json
import os
import base64
import sqlite3
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

MCP_DIR = Path(__file__).resolve().parent.parent
AUTH_DIR = MCP_DIR / "auth"
sys.path.insert(0, str(MCP_DIR))
sys.path.insert(0, str(AUTH_DIR))

import commercial_client as client
import server
from lease_crypto import create_device_key, create_lease_issuer, issue_lease, sign_device_message, utc_now, verify_lease
from license_control_service import ControlError, ControlStore, Handler
from license_control_admin import create_control_env
from payment_providers import ManualPaymentProvider, PaddlePaymentProvider


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def expect_control_error(code: str, operation) -> None:
    try:
        operation()
    except ControlError as exc:
        check(exc.code == code, f"expected {code}, received {exc.code}")
        return
    raise AssertionError(f"expected ControlError {code}")


def post(url: str, payload: dict, token: str = "", order_token: str = "") -> tuple[int, dict]:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    if order_token:
        headers["X-Order-Token"] = order_token
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def signed_payload(credential: dict, device_key: dict, install_id: str, action: str, nonce: str, **signed_fields) -> dict:
    proof = {
        "action": action,
        "activation_token": credential["activation_token"],
        "install_id": install_id,
        "timestamp": utc_now(),
        "nonce": nonce,
        **signed_fields,
    }
    return {
        "activation_token": credential["activation_token"],
        "proof": proof,
        "signature": sign_device_message(device_key, proof),
    }


def main() -> int:
    tests = 0
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        lease_private, lease_public = root / "lease-private.json", root / "lease-public.json"
        create_lease_issuer(lease_private, lease_public)
        alipay_qr = root / "alipay.png"
        alipay_qr.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF/gL+X8p7WQAAAABJRU5ErkJggg=="))
        control_env = root / "control.env"
        env_result = create_control_env(
            control_env,
            lease_private_key=lease_private,
            db_path=root / "control.sqlite3",
            alipay_qr_path=alipay_qr,
            support_contact="售后QQ群：923937311",
        )
        env_text = control_env.read_text()
        tests += 1
        check(env_result["ok"] and "LAB_CONTROL_ADMIN_TOKEN" in env_text and "923937311" in env_text, "private control environment was not created")
        if os.name != "nt":
            check((control_env.stat().st_mode & 0o077) == 0, "control environment permissions are not private")
        check("LAB_CONTROL_ADMIN_TOKEN" not in json.dumps(env_result), "control secret leaked into command result")
        public_record = json.loads(lease_public.read_text())
        store = ControlStore(
            root / "control.sqlite3",
            key_pepper="pepper-" + "p" * 40,
            token_secret="token-" + "t" * 40,
            lease_private_key=lease_private,
            payment_providers={
                "alipay": ManualPaymentProvider("alipay", "支付宝经营码", instructions="使用经营码付款", qr_image_url="/payment-assets/alipay"),
                "wechat": ManualPaymentProvider("wechat", "微信经营收款", instructions="联系卖家获取经营码"),
                "paddle": PaddlePaymentProvider(),
            },
            support_contact="support@example.test",
        )
        Handler.store = store
        Handler.admin_token = "admin-" + "a" * 40
        Handler.payment_assets = {"alipay": alipay_qr}
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{httpd.server_port}"

        with urllib.request.urlopen(base_url + "/admin", timeout=5) as response:
            control_html = response.read().decode("utf-8")
            control_csp = response.headers.get("Content-Security-Policy", "")
        tests += 1
        check("密钥中控台" in control_html and "frame-ancestors 'none'" in control_csp, "seller control UI or security headers are missing")

        with urllib.request.urlopen(base_url + "/buy", timeout=5) as response:
            purchase_html = response.read().decode("utf-8")
            purchase_csp = response.headers.get("Content-Security-Policy", "")
        tests += 1
        check("成果会说话" in purchase_html and "数字化软件服务" in purchase_html and "frame-ancestors 'none'" in purchase_csp, "purchase UI, refund policy, or security headers are missing")

        with urllib.request.urlopen(base_url + "/payment-assets/alipay", timeout=5) as response:
            qr_body = response.read()
            qr_type = response.headers.get("Content-Type", "")
        tests += 1
        check(qr_body == alipay_qr.read_bytes() and qr_type == "image/png", "private Alipay QR asset was not served safely")

        with urllib.request.urlopen(base_url + "/api/checkout/config", timeout=5) as response:
            checkout = json.loads(response.read())
        tests += 1
        check(checkout["product"]["amount_cents"] == 990 and checkout["support_contact"] == "support@example.test", "checkout configuration is wrong")
        check([(item["id"], item["amount_cents"]) for item in checkout["plans"]] == [("experience", 990), ("permanent", 4990)], "checkout plans are wrong")
        check("不支持无理由退款" in checkout["product"]["refund_policy"], "checkout refund policy is missing")
        check(checkout["product"]["self_service_refunds"] is False, "self-service refund capability was exposed")
        check(next(item for item in checkout["payment_providers"] if item["id"] == "alipay")["qr_image_url"] == "/payment-assets/alipay", "Alipay QR was not exposed through provider config")
        check(not next(item for item in checkout["payment_providers"] if item["id"] == "paddle")["available"], "Paddle was exposed before webhook support")

        order_status, order_created = post(base_url + "/api/orders", {"contact": "buyer@example.test", "payment_provider": "alipay"})
        tests += 1
        check(order_status == 201 and order_created["order"]["status"] == "payment_pending" and order_created["order"]["plan"] == "experience", "public experience order creation failed")
        order_token = order_created["status_token"]
        with sqlite3.connect(root / "control.sqlite3") as conn:
            serialized_orders = " ".join(str(value) for row in conn.execute("select * from orders") for value in row)
        check(order_token not in serialized_orders, "raw order token was stored in SQLite")

        payment_status, payment_body = post(
            base_url + "/api/order/payment",
            {"payment_reference": "trade-001", "paid_at": "2026-08-22T10:30"},
            order_token=order_token,
        )
        tests += 1
        check(payment_status == 200 and payment_body["order"]["status"] == "payment_submitted", "payment submission failed")
        repeated_status, repeated_body = post(
            base_url + "/api/order/payment",
            {"payment_reference": "trade-001", "paid_at": "2026-08-22T10:30"},
            order_token=order_token,
        )
        check(repeated_status == 200 and repeated_body["order"]["status"] == "payment_submitted", "payment submission is not idempotent")

        order_id = order_created["order"]["id"]
        delivered = store.admin_order_action(order_id, "confirm-and-deliver", "verified in merchant record")
        store.admin_order_action(order_id, "confirm-and-deliver", "duplicate retry")
        tests += 1
        check(delivered["order"]["status"] == "delivered" and "activation_key" not in delivered, "semi-automatic delivery failed")
        public_order = store.get_order_by_token(order_token)
        order_activation_key = public_order.get("activation_key", "")
        tests += 1
        check(order_activation_key.startswith("LF-") and order_activation_key.endswith(public_order["license"]["key_suffix"]), "authenticated order lookup did not reveal its key")
        with store.connection() as conn:
            linked_key_count = conn.execute("select count(*) from license_keys where customer_ref=?", (order_id,)).fetchone()[0]
            serialized_delivery = " ".join(
                str(value)
                for table in ("orders", "license_keys")
                for row in conn.execute(f"select * from {table}")
                for value in row
            )
        check(linked_key_count == 1, "duplicate order issue created multiple keys")
        check(order_activation_key not in serialized_delivery, "raw automatically delivered key was stored in SQLite")
        order_device = create_device_key()
        store.activate(order_activation_key, "install_order", order_device["public_key"])
        tests += 1
        check(store.get_order(order_id)["status"] == "delivered", "order delivery state changed unexpectedly")
        refund_status, refund_body = post(base_url + "/api/order/refund", {"reason": "changed mind"}, order_token=order_token)
        tests += 1
        check(refund_status == 409 and refund_body["error"]["code"] == "SELF_SERVICE_REFUND_UNAVAILABLE", "order-page self-service refund was not rejected")
        check(store.get_order(order_id)["status"] == "delivered", "rejected refund request changed the order")
        refunded_order = store.admin_order_action(order_id, "refund", "original-route refund completed")
        tests += 1
        check(refunded_order["order"]["status"] == "refunded" and refunded_order["order"]["license"]["status"] == "refunded", "refund did not revoke linked key")
        with store.connection() as conn:
            with conn:
                old = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
                conn.execute("update orders set refunded_at=?,updated_at=? where id=?", (old, old, order_id))
        purged = store.purge_expired_order_personal_data(90)
        tests += 1
        check(purged["purged_orders"] == 1 and store.get_order(order_id)["contact"] == "", "expired personal order data was not purged")

        invalid_request = urllib.request.Request(base_url + "/api/order", headers={"X-Order-Token": "forged-token"})
        try:
            urllib.request.urlopen(invalid_request, timeout=5)
            invalid_status = 200
        except urllib.error.HTTPError as exc:
            invalid_status = exc.code
        tests += 1
        check(invalid_status == 404, "forged order token was accepted")

        unauthorized_orders = urllib.request.Request(base_url + "/admin/orders", headers={"Authorization": "Bearer wrong"})
        try:
            urllib.request.urlopen(unauthorized_orders, timeout=5)
            unauthorized_status = 200
        except urllib.error.HTTPError as exc:
            unauthorized_status = exc.code
        tests += 1
        check(unauthorized_status == 401, "admin order endpoint accepted bad token")

        client.APP_DIR = root / "client"
        client.DEVICE_FILE = client.APP_DIR / "device.json"
        client.PREFERENCES_FILE = client.APP_DIR / "preferences.json"
        client.LICENSE_METADATA_FILE = client.APP_DIR / "license.json"
        client.TELEMETRY_LOG = client.APP_DIR / "telemetry.jsonl"
        client.FEEDBACK_LOG = client.APP_DIR / "feedback.jsonl"
        client.LEASE_PUBLIC_KEY_FILE = lease_public
        client._ONLINE_REFRESH_ATTEMPTED = False
        os.environ["LAB_FACTORY_CREDENTIAL_BACKEND"] = "file"
        os.environ["LAB_FACTORY_CONTROL_URL"] = base_url

        refund_guidance = server.tool_request_refund({})
        tests += 1
        check(refund_guidance["status"] == "AFTER_SALES_REQUIRED" and "923937311" in refund_guidance["message"], "MCP refund tool did not return after-sales guidance")

        created = store.create_key(label="three-day", customer_ref="order-1", refund_days=3)
        activation_key, key_id = created["activation_key"], created["key"]["id"]
        tests += 1
        check(activation_key.startswith("LF-") and activation_key.endswith(created["key"]["key_suffix"]), "key generation failed")

        with sqlite3.connect(root / "control.sqlite3") as conn:
            serialized = " ".join(str(value) for row in conn.execute("select * from license_keys") for value in row)
        tests += 1
        check(activation_key not in serialized, "raw activation key was stored in SQLite")

        activated = client.activate_key(activation_key, True, "1.0", base_url)
        tests += 1
        check(activated["activated"] and activated["mode"] == "online_lease", "client activation failed")

        active_row = store.get_key(key_id)
        tests += 1
        check(active_row["status"] == "active" and active_row["used"] and active_row["bound"], "central status did not show used")
        check(active_row["refund_days"] == 3 and active_row["refund_deadline"], "refund policy was not attached")

        other = create_device_key()
        expect_control_error("KEY_ALREADY_USED", lambda: store.activate(activation_key, "install_other", other["public_key"]))
        tests += 1
        expect_control_error("INVALID_DEVICE_KEY", lambda: store.activate("not-a-real-key", "install_bad", "not-a-public-key"))
        tests += 1

        credential = client.CredentialStore().get()
        check(bool(credential), "online credential was not stored")
        refreshed, lease_payload = client.refresh_online_lease(credential)
        tests += 1
        check(lease_payload["license_key_id"] == key_id, "signed refresh lease has wrong key id")
        check(lease_payload["plan"] == "permanent" and lease_payload["features"]["skill_condensation"], "existing permanent key lost its entitlement")

        experience = store.create_key(label="experience", refund_days=7, plan="experience")
        experience_device = create_device_key()
        experience_activation = store.activate(
            experience["activation_key"], "install_experience", experience_device["public_key"]
        )
        experience_payload = verify_lease(
            experience_activation["lease"], public_record,
            install_id="install_experience", product_id="lab-factory-1",
        )
        tests += 1
        check(experience_payload["plan"] == "experience" and experience_payload["usage_limit"] == 3, "experience plan was not signed into the lease")
        check(not experience_payload["features"]["skill_condensation"], "experience key unexpectedly unlocked skill condensation")
        last_usage = None
        for index in range(1, 4):
            last_usage = store.consume_usage(signed_payload(
                experience_activation, experience_device, "install_experience", "consume_usage",
                f"experience-use-{index}", usage_id=f"report:{index}",
            ))
            check(last_usage["charged"] and last_usage["usage_count"] == index, "experience usage was not charged exactly once")
        repeat_payload = signed_payload(
            experience_activation, experience_device, "install_experience", "consume_usage",
            "experience-repeat", usage_id="report:1",
        )
        repeat_status, repeat_body = post(base_url + "/api/usage/consume", repeat_payload)
        repeated_usage = repeat_body
        tests += 1
        check(repeat_status == 200 and not repeated_usage["charged"] and repeated_usage["usage_count"] == 3 and repeated_usage["remaining_uses"] == 0, "usage retry was not idempotent")
        fourth_status, fourth_body = post(base_url + "/api/usage/consume", signed_payload(
            experience_activation, experience_device, "install_experience", "consume_usage",
            "experience-fourth", usage_id="report:4",
        ))
        check(fourth_status == 403 and fourth_body["error"]["code"] == "USAGE_LIMIT_REACHED", "fourth experience use was not blocked")
        tests += 1
        original_activation_status = server.activation_status
        try:
            server.activation_status = lambda: {"activated": True, "plan": "experience", "features": {"skill_condensation": False}}
            try:
                server.require_feature("skill_condensation")
                feature_blocked = False
            except server.ToolError as exc:
                feature_blocked = exc.code == "FEATURE_NOT_INCLUDED"
        finally:
            server.activation_status = original_activation_status
        check(feature_blocked, "experience key was not blocked from skill condensation")
        tests += 1

        device_record = client.installation_key()
        replay = signed_payload(refreshed, device_record, client.install_id(), "refresh", "fixed-replay-nonce")
        store.refresh(replay)
        expect_control_error("REPLAYED_PROOF", lambda: store.refresh(replay))
        tests += 1

        forged = signed_payload(refreshed, other, client.install_id(), "refresh", "forged-signature-nonce")
        expect_control_error("INVALID_SIGNATURE", lambda: store.refresh(forged))
        tests += 1

        status_code, body = post(base_url + "/admin/keys", {"refund_days": 7}, "wrong-token")
        tests += 1
        check(status_code == 401 and body["error"]["code"] == "ADMIN_AUTH_REQUIRED", "admin endpoint accepted bad token")

        refund_result = client.request_refund()
        tests += 1
        check(refund_result["status"] == "AFTER_SALES_REQUIRED", "refund command did not return after-sales guidance")
        restored = store.refresh(signed_payload(refreshed, device_record, client.install_id(), "refresh", "still-active-after-guidance"))
        tests += 1
        check(restored["ok"], "after-sales guidance unexpectedly blocked the key")

        store.admin_action(key_id, "ban", "policy violation")
        client._ONLINE_REFRESH_ATTEMPTED = False
        blocked = client.activation_status(refresh=True)
        tests += 1
        check(not blocked["activated"] and blocked["error_code"] == "KEY_BLOCKED", "client did not honor central ban")

        store.admin_action(key_id, "restore", "mistaken ban")
        client._ONLINE_REFRESH_ATTEMPTED = False
        check(client.activation_status(refresh=True)["activated"], "restored client did not recover")
        store.admin_action(key_id, "ban", "prepare replacement")
        reset = store.admin_action(key_id, "reset-binding", "one allowed replacement")
        tests += 1
        check(reset["key"]["status"] == "unused" and not reset["key"]["bound"], "binding reset failed")

        seven = store.create_key(label="seven-day", refund_days=7)
        seven_device = create_device_key()
        seven_activation = store.activate(seven["activation_key"], "install_seven", seven_device["public_key"])
        tests += 1
        check(seven_activation["refund_days"] == 7, "seven-day refund policy failed")

        with store.connection() as conn:
            with conn:
                conn.execute(
                    "update license_keys set refund_deadline=? where id=?",
                    ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), seven["key"]["id"]),
                )
        expired_refund = signed_payload(seven_activation, seven_device, "install_seven", "refund_request", "expired-refund")
        expect_control_error("SELF_SERVICE_REFUND_UNAVAILABLE", lambda: store.request_refund(expired_refund))
        tests += 1

        valid_lease = issue_lease(
            lease_private,
            license_key_id=seven["key"]["id"],
            install_id="install_seven",
            product_id="lab-factory-1",
        )
        tampered = json.loads(json.dumps(valid_lease))
        tampered["payload"]["install_id"] = "install_attacker"
        tamper_rejected = False
        try:
            verify_lease(tampered, public_record, install_id="install_attacker", product_id="lab-factory-1")
        except Exception:
            tamper_rejected = True
        check(tamper_rejected, "tampered lease was accepted")
        tests += 1

        expired_lease = issue_lease(
            lease_private,
            license_key_id=seven["key"]["id"],
            install_id="install_seven",
            product_id="lab-factory-1",
            now=datetime.now(timezone.utc) - timedelta(hours=25),
        )
        expiry_rejected = False
        try:
            verify_lease(expired_lease, public_record, install_id="install_seven", product_id="lab-factory-1")
        except Exception:
            expiry_rejected = True
        check(expiry_rejected, "expired lease was accepted")
        tests += 1

        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        client._ONLINE_REFRESH_ATTEMPTED = False
        offline = client.activation_status(refresh=True)
        tests += 1
        check(
            offline["activated"] and offline["mode"] == "online_lease_offline_window",
            f"valid offline window was not honored: {offline}",
        )

        events = store.get_key(key_id)["audit_events"]
        event_names = {event["event"] for event in events}
        tests += 1
        check({"key_created", "key_activated", "key_banned", "key_restored", "binding_reset"} <= event_names, "audit history is incomplete")

    print(json.dumps({"ok": True, "tests": tests}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
