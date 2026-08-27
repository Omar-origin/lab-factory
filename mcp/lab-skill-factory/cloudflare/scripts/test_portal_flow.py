#!/usr/bin/env python3
"""End-to-end test for account, team-seat and referral portal flows."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path
import sys

MCP_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MCP_DIR))
from lease_crypto import create_device_key, verify_lease


BASE = os.environ.get("LAB_WORKER_TEST_URL", "http://127.0.0.1:8787").rstrip("/")


def call(method: str, path: str, payload: dict | None = None, headers: dict | None = None):
    request = urllib.request.Request(
        BASE + path,
        data=None if payload is None else json.dumps(payload, separators=(",", ":")).encode(),
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            body = json.loads(raw) if response.headers.get_content_type() == "application/json" else raw
            return response.status, body, response.headers
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read()), error.headers


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def register(email: str, invite_code: str = "") -> tuple[str, str]:
    password = "PortalTest-" + uuid.uuid4().hex[:12]
    status, started, _ = call("POST", "/api/auth/register/start", {"email": email, "password": password, "invite_code": invite_code, "turnstile_token": "dev-turnstile"})
    check(status == 200 and started.get("dev_code"), "development registration challenge failed")
    status, verified, headers = call("POST", "/api/auth/register/verify", {
        "email": email,
        "password": password,
        "challenge_id": started["challenge_id"],
        "code": started["dev_code"],
        "invite_code": invite_code,
    })
    check(status == 200 and verified["user"]["email"] == email, "registration verification failed")
    cookie = headers.get("Set-Cookie", "").split(";", 1)[0]
    check(cookie.startswith("lf_session="), "session cookie was not issued")
    return cookie, password


def login(email: str, password: str) -> str:
    status, logged_in, headers = call("POST", "/api/auth/login", {"email": email, "password": password, "turnstile_token": "dev-turnstile"})
    check(status == 200 and logged_in["user"]["email"] == email, "password login failed")
    return headers.get("Set-Cookie", "").split(";", 1)[0]


def main() -> int:
    admin = os.environ.get("LAB_CONTROL_ADMIN_TOKEN", "")
    check(len(admin) >= 32, "LAB_CONTROL_ADMIN_TOKEN is required")
    suffix = uuid.uuid4().hex[:10]
    status, weak, _ = call("POST", "/api/auth/register/start", {"email": f"weak-{suffix}@example.test", "password": "password", "turnstile_token": "dev-turnstile"})
    check(status == 400 and weak["error"]["code"] == "WEAK_PASSWORD", "weak registration password was accepted")
    admin_headers = {"Authorization": f"Bearer {admin}"}
    status, bootstrap, _ = call("POST", "/admin/bootstrap-invites", {"role": "owner", "max_uses": 1, "valid_days": 1}, admin_headers)
    check(status == 201 and bootstrap["invite"]["code"].startswith("LFA-"), "owner bootstrap invite failed")
    owner_email = f"owner-{suffix}@example.test"
    owner_cookie, owner_password = register(owner_email, bootstrap["invite"]["code"])
    status, _, _ = call("POST", "/api/auth/login", {"email": owner_email, "password": "WrongPass-123", "turnstile_token": "dev-turnstile"})
    check(status == 401, "wrong password was accepted")
    owner_cookie = login(owner_email, owner_password)
    locked_email = f"locked-{suffix}@example.test"
    _, locked_password = register(locked_email)
    for _ in range(5):
        status, _, _ = call("POST", "/api/auth/login", {"email": locked_email, "password": "WrongPass-123", "turnstile_token": "dev-turnstile"})
        check(status == 401, "wrong password did not count as a failed login")
    status, locked, _ = call("POST", "/api/auth/login", {"email": locked_email, "password": locked_password, "turnstile_token": "dev-turnstile"})
    check(status == 429 and locked["error"]["code"] == "LOGIN_LOCKED", "password failure lockout did not activate")
    status, owner, _ = call("GET", "/api/me", headers={"Cookie": owner_cookie})
    check(status == 200 and len(owner["referral_code"]) == 5 and owner["user"]["role"] == "owner" and owner["admin_access"], "owner role or referral code was not allocated")

    status, created_invite, _ = call("POST", "/api/control/invites", {"role": "distributor_admin", "max_uses": 1, "valid_days": 7}, {"Cookie": owner_cookie})
    check(status == 201 and created_invite["invite"]["code"].startswith("LFA-"), "distributor admin invite creation failed")
    distributor_cookie, _ = register(f"distributor-{suffix}@example.test", created_invite["invite"]["code"])
    status, distributor_session, _ = call("GET", "/api/control/session", headers={"Cookie": distributor_cookie})
    check(status == 200 and distributor_session["user"]["role"] == "distributor_admin" and not distributor_session["permissions"]["manage_roles"], "distributor role boundary is wrong")
    status, forbidden, _ = call("GET", "/api/control/invites", headers={"Cookie": distributor_cookie})
    check(status == 403 and forbidden["error"]["code"] == "OWNER_REQUIRED", "distributor could access owner invite management")
    status, forbidden_key, _ = call("POST", "/api/control/keys", {"plan": "permanent"}, {"Cookie": distributor_cookie})
    check(status == 403 and forbidden_key["error"]["code"] == "OWNER_REQUIRED", "distributor could directly generate keys")
    status, direct_team, _ = call("POST", "/api/control/keys", {"plan": "team", "label": "portal direct issue"}, {"Cookie": owner_cookie})
    check(status == 201 and len(direct_team["activation_keys"]) == 5 and len(set(direct_team["activation_keys"])) == 5, "owner direct team-key generation failed")

    invited_cookie, _ = register(f"invited-{suffix}@example.test", owner["referral_code"])
    status, cancellable, _ = call("POST", "/api/orders", {"payment_provider": "alipay", "plan": "experience"}, {"Cookie": invited_cookie})
    check(status == 201, "cancellable order creation failed")
    cancel_id = cancellable["order"]["id"]
    status, cancelled, _ = call("POST", f"/api/orders/{cancel_id}/cancel", {}, {"Cookie": invited_cookie})
    check(status == 200 and cancelled["order"]["effective_status"] == "cancelled", "customer order cancellation failed")
    status, _, _ = call("POST", f"/api/orders/{cancel_id}/hide", {}, {"Cookie": invited_cookie})
    check(status == 200, "customer order hiding failed")

    status, experience, _ = call("POST", "/api/orders", {"payment_provider": "alipay", "plan": "experience"}, {"Cookie": invited_cookie})
    check(status == 201 and experience["order"]["amount_cents"] == 990, "experience order creation failed")
    experience_headers = {"X-Order-Token": experience["status_token"]}
    status, _, _ = call("POST", "/api/order/payment", {"payment_reference": f"experience-{suffix}", "paid_at": "2026-08-25T11:00"}, experience_headers)
    check(status == 200, "experience payment submission failed")
    status, _, _ = call("POST", f"/admin/orders/{experience['order']['id']}/confirm-and-deliver", {"reason": "promotion source"}, admin_headers)
    check(status == 200, "experience order delivery failed")

    status, discounted_config, _ = call("GET", "/api/checkout/config", headers={"Cookie": invited_cookie})
    discount_by_plan = {item["id"]: item["promotion_discount_cents"] for item in discounted_config["plans"]}
    checkout_by_plan = {item["id"]: item["checkout_amount_cents"] for item in discounted_config["plans"]}
    check(status == 200 and discount_by_plan == {"experience": 0, "permanent": 990, "team": 990}, "upgrade discount was not shown on both higher plans")
    check(checkout_by_plan["permanent"] == 4000 and checkout_by_plan["team"] == 18910, "discounted upgrade prices are wrong")
    status, reserved, _ = call("POST", "/api/orders", {"payment_provider": "alipay", "plan": "permanent"}, {"Cookie": invited_cookie})
    check(status == 201 and reserved["order"]["amount_cents"] == 4000 and reserved["order"]["promotion_discount_cents"] == 990, "permanent promotion reservation failed")
    status, _, _ = call("POST", f"/api/orders/{reserved['order']['id']}/cancel", {}, {"Cookie": invited_cookie})
    check(status == 200, "promotion reservation cancellation failed")

    status, created, _ = call("POST", "/api/orders", {"payment_provider": "alipay", "plan": "team"}, {"Cookie": invited_cookie})
    check(status == 201 and created["order"]["amount_cents"] == 18910 and created["order"]["promotion_discount_cents"] == 990, "team upgrade discount failed")
    token = created["status_token"]
    order_id = created["order"]["id"]
    order_headers = {"X-Order-Token": token}
    status, _, _ = call("POST", "/api/order/payment", {"payment_reference": f"team-{suffix}", "paid_at": "2026-08-25T12:00"}, order_headers)
    check(status == 200, "team payment submission failed")
    status, delivered, _ = call("POST", f"/admin/orders/{order_id}/confirm-and-deliver", {"reason": "portal flow test"}, {"Authorization": f"Bearer {admin}"})
    check(status == 200 and delivered["order"]["status"] == "delivered", "team order delivery failed")
    status, public_order, _ = call("GET", "/api/order", headers=order_headers)
    keys = public_order["order"].get("activation_keys", [])
    check(status == 200 and len(keys) == 5 and len(set(keys)) == 5, "team order did not deliver five independent keys")
    device = create_device_key()
    status, activation, _ = call("POST", "/api/activate", {"activation_key": keys[0], "install_id": f"team-install-{suffix}", "device_public_key": device["public_key"]})
    public_record = json.loads((MCP_DIR / "lease_public_key.json").read_text())
    payload = verify_lease(activation["lease"], public_record, install_id=f"team-install-{suffix}", product_id="lab-factory-1")
    check(status == 200 and payload["plan"] == "team" and payload["features"]["skill_condensation"], "team key activation failed")

    status, restored_config, _ = call("GET", "/api/checkout/config", headers={"Cookie": invited_cookie})
    check(status == 200 and all(item["promotion_discount_cents"] == 0 for item in restored_config["plans"]), "upgrade prices did not return to normal after redemption")
    status, full_price, _ = call("POST", "/api/orders", {"payment_provider": "alipay", "plan": "permanent"}, {"Cookie": invited_cookie})
    check(status == 201 and full_price["order"]["amount_cents"] == 4990, "higher plan did not return to full price")
    call("POST", f"/api/orders/{full_price['order']['id']}/cancel", {}, {"Cookie": invited_cookie})

    status, dashboard, _ = call("GET", "/api/dashboard", headers={"Cookie": invited_cookie})
    check(status == 200 and any(item["plan"] == "team" and item["seat_count"] == 5 for item in dashboard["entitlements"]) and len([item for item in dashboard["keys"] if item["plan"] == "team"]) == 5, "team entitlement dashboard is wrong")
    status, referrals, _ = call("GET", "/api/referrals", headers={"Cookie": owner_cookie})
    check(status == 200 and referrals["stats"]["invite_count"] == 1, "invited account was not attributed")
    check(any(item["plan"] == "team" and item["basis_cents"] == 18910 and item["amount_cents"] == 3782 for item in referrals["entries"]), "20 percent commission is wrong after promotion")

    status, refunded, _ = call("POST", f"/admin/orders/{order_id}/refund", {"reason": "portal refund test"}, {"Authorization": f"Bearer {admin}"})
    check(status == 200 and refunded["order"]["status"] == "refunded", "team refund failed")
    status, referrals, _ = call("GET", "/api/referrals", headers={"Cookie": owner_cookie})
    check(status == 200 and any(item["plan"] == "team" and item["status"] == "reversed" for item in referrals["entries"]), "refund did not reverse commission")
    status, withdrawals, _ = call("GET", "/admin/withdrawals", headers={"Authorization": f"Bearer {admin}"})
    check(status == 200 and isinstance(withdrawals["withdrawals"], list), "admin withdrawal ledger failed")

    status, metric, _ = call("POST", "/api/metrics/view", {"route": "/plans"})
    check(status == 202 and metric["ok"], "page-view metric failed")
    status, overview, _ = call("GET", "/api/control/overview?days=30", headers={"Cookie": owner_cookie})
    check(status == 200 and overview["traffic_available"] and overview["registrations"] >= 3, "owner analytics overview failed")
    status, key_search, _ = call("GET", "/api/control/keys?plan=team&status=refunded", headers={"Cookie": owner_cookie})
    check(status == 200 and len(key_search["keys"]) >= 5 and all(item["plan"] == "team" and item["status"] == "refunded" for item in key_search["keys"]), "key plan/status filtering failed")
    status, users, _ = call("GET", "/api/control/users?role=distributor_admin", headers={"Cookie": owner_cookie})
    check(status == 200 and any(item["role"] == "distributor_admin" for item in users["users"]), "owner user-role listing failed")

    routes = ("/dashboard", "/plans", "/referrals", "/showcase", "/docs", "/account", "/orders", "/login", "/register")
    for route in routes:
        status, page, _ = call("GET", route)
        check(status == 200 and isinstance(page, bytes) and b"Lab Factory" in page, f"portal route failed: {route}")
    status, root_page, _ = call("GET", "/")
    check(status == 200 and isinstance(root_page, bytes) and "成果会说话".encode() in root_page, "root domain did not redirect to public showcase")
    control_routes = ("/control/overview", "/control/keys", "/control/orders", "/control/users", "/control/invites", "/control/withdrawals")
    for route in control_routes:
        status, page, _ = call("GET", route, headers={"Cookie": owner_cookie})
        check(status == 200 and isinstance(page, bytes) and b"Lab Factory" in page, f"control route failed: {route}")

    print(json.dumps({"ok": True, "team_keys": len(keys), "direct_team_keys": len(direct_team["activation_keys"]), "commission_cents": 3782, "upgrade_discount_cents": 990, "routes": len(routes) + len(control_routes), "password_login": True, "rbac": True, "analytics": True, "order_lifecycle": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
