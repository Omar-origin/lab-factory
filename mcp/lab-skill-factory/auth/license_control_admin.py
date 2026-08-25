#!/usr/bin/env python3
"""Seller CLI for the Lab Factory license control plane."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shlex
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lease_crypto import create_lease_issuer


def create_control_env(
    output: Path,
    *,
    lease_private_key: Path,
    db_path: Path,
    alipay_qr_path: Path,
    support_contact: str,
    force: bool = False,
) -> dict[str, Any]:
    output = output.expanduser().resolve()
    if output.exists() and not force:
        raise FileExistsError("control environment already exists; use --force only for intentional secret rotation")
    values = {
        "LAB_CONTROL_ADMIN_TOKEN": secrets.token_urlsafe(48),
        "LAB_CONTROL_KEY_PEPPER": secrets.token_urlsafe(48),
        "LAB_CONTROL_TOKEN_SECRET": secrets.token_urlsafe(48),
        "LAB_CONTROL_LEASE_PRIVATE_KEY": str(lease_private_key.expanduser().resolve()),
        "LAB_CONTROL_DB": str(db_path.expanduser().resolve()),
        "LAB_CONTROL_ALIPAY_QR_PATH": str(alipay_qr_path.expanduser().resolve()),
        "LAB_CONTROL_ALIPAY_INSTRUCTIONS": "使用支付宝扫描经营码，并按订单金额付款",
        "LAB_CONTROL_SUPPORT_CONTACT": support_contact,
        "LAB_CONTROL_PRICE_CENTS": "990",
        "LAB_CONTROL_PERMANENT_PRICE_CENTS": "4990",
        "LAB_CONTROL_REFUND_DAYS": "7",
        "LAB_CONTROL_HOST": "127.0.0.1",
        "LAB_CONTROL_PORT": "8765",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text("\n".join(f"export {key}={shlex.quote(value)}" for key, value in values.items()) + "\n", encoding="utf-8")
    if os.name != "nt":
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
    os.replace(temporary, output)
    return {
        "ok": True,
        "environment_path": str(output),
        "warning": "配置包含管理员 Token 和数据库密钥，只能保存在卖家设备；不要提交、截图或发送。",
    }


def call_api(base_url: str, admin_token: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not base_url:
        raise ValueError("set LAB_CONTROL_API_URL or pass --api-url")
    if len(admin_token) < 32:
        raise ValueError("set a strong LAB_CONTROL_ADMIN_TOKEN or pass --admin-token")
    body = None if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=body,
        headers={"Authorization": f"Bearer {admin_token}", "Accept": "application/json", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            error = parsed.get("error", {})
            detail = error.get("message") or detail
        except (json.JSONDecodeError, AttributeError):
            pass
        raise RuntimeError(f"control API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"cannot reach control API: {exc}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("control API returned a non-object response")
    return result


def add_reason(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("key_id")
    parser.add_argument("--reason", default="")


def main() -> int:
    parser = argparse.ArgumentParser(description="Lab Factory online license control")
    parser.add_argument("--api-url", default=os.environ.get("LAB_CONTROL_API_URL", ""))
    parser.add_argument("--admin-token", default=os.environ.get("LAB_CONTROL_ADMIN_TOKEN", ""))
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-lease-issuer", help="Create the rotatable online lease signing key pair")
    init.add_argument("--private-key", type=Path, required=True)
    init.add_argument("--public-key", type=Path, default=ROOT / "lease_public_key.json")
    init.add_argument("--force", action="store_true")

    init_config = sub.add_parser("init-control-config", help="Create a private local control-plane environment file")
    init_config.add_argument("--output", type=Path, required=True)
    init_config.add_argument("--lease-private-key", type=Path, required=True)
    init_config.add_argument("--db", type=Path, required=True)
    init_config.add_argument("--alipay-qr", type=Path, required=True)
    init_config.add_argument("--support-contact", default="售后QQ群：923937311")
    init_config.add_argument("--force", action="store_true")

    keys = sub.add_parser("keys", help="Create, inspect, refund, ban, or reset activation keys")
    key_sub = keys.add_subparsers(dest="key_action", required=True)
    create = key_sub.add_parser("create", help="Create a key; plaintext is returned exactly once")
    create.add_argument("--label", default="")
    create.add_argument("--customer-ref", default="")
    create.add_argument("--refund-days", type=int, choices=[3, 7], default=7)
    create.add_argument("--plan", choices=["experience", "permanent"], default="permanent")
    list_parser = key_sub.add_parser("list", help="List keys and whether each one has been used")
    list_parser.add_argument("--status", choices=["unused", "active", "refund_requested", "refunded", "banned"])
    list_parser.add_argument("--limit", type=int, default=100)
    show = key_sub.add_parser("show", help="Show one key and its audit history")
    show.add_argument("key_id")
    sent = key_sub.add_parser("mark-sent", help="Record that the plaintext key was sent")
    sent.add_argument("key_id")
    for action, help_text in (
        ("ban", "Ban a key; no new lease will be issued"),
        ("refund", "Complete a refund and revoke the key"),
        ("restore", "Undo a mistaken ban or reject a refund request"),
        ("reset-binding", "Clear the old installation binding for a replacement"),
    ):
        action_parser = key_sub.add_parser(action, help=help_text)
        add_reason(action_parser)

    orders = sub.add_parser("orders", help="Inspect and process purchase-page orders")
    order_sub = orders.add_subparsers(dest="order_action", required=True)
    order_list = order_sub.add_parser("list", help="List purchase orders")
    order_list.add_argument("--status", choices=[
        "payment_pending", "payment_submitted", "payment_rejected", "paid",
        "key_issued", "delivered", "refund_requested", "refunded",
    ])
    order_list.add_argument("--limit", type=int, default=100)
    order_show = order_sub.add_parser("show", help="Show one order and its audit history")
    order_show.add_argument("order_id")
    order_purge = order_sub.add_parser("purge-personal-data", help="Delete expired contact and payment-verification fields")
    order_purge.add_argument("--retention-days", type=int, default=90)
    for action, help_text in (
        ("confirm-and-deliver", "Confirm payment and automatically deliver the order key"),
        ("confirm-payment", "Confirm a manually verified payment"),
        ("reject-payment", "Reject an unverifiable payment claim"),
        ("issue", "Issue the order activation key; plaintext appears once"),
        ("deliver", "Record that the activation key was sent"),
        ("refund", "Record original-route refund and revoke the key"),
    ):
        action_parser = order_sub.add_parser(action, help=help_text)
        action_parser.add_argument("order_id")
        action_parser.add_argument("--reason", default="")

    args = parser.parse_args()
    try:
        if args.command == "init-lease-issuer":
            result = create_lease_issuer(args.private_key.expanduser(), args.public_key.expanduser(), force=args.force)
            result["warning"] = "在线租约私钥可轮换，但只能放在中控 Secret/受限文件中；正式许可证私钥仍不得上传。"
        elif args.command == "init-control-config":
            result = create_control_env(
                args.output,
                lease_private_key=args.lease_private_key,
                db_path=args.db,
                alipay_qr_path=args.alipay_qr,
                support_contact=args.support_contact,
                force=args.force,
            )
        elif args.command == "orders":
            if args.order_action == "list":
                query = {"limit": str(args.limit)}
                if args.status:
                    query["status"] = args.status
                result = call_api(args.api_url, args.admin_token, "GET", "/admin/orders?" + urllib.parse.urlencode(query))
            elif args.order_action == "show":
                result = call_api(args.api_url, args.admin_token, "GET", f"/admin/orders/{args.order_id}")
            elif args.order_action == "purge-personal-data":
                result = call_api(
                    args.api_url, args.admin_token, "POST", "/admin/orders/purge-personal-data",
                    {"retention_days": args.retention_days},
                )
            else:
                result = call_api(
                    args.api_url, args.admin_token, "POST",
                    f"/admin/orders/{args.order_id}/{args.order_action}",
                    {"reason": args.reason},
                )
        elif args.key_action == "create":
            result = call_api(args.api_url, args.admin_token, "POST", "/admin/keys", {
                "label": args.label,
                "customer_ref": args.customer_ref,
                "refund_days": args.refund_days,
                "plan": args.plan,
            })
        elif args.key_action == "list":
            query = {"limit": str(args.limit)}
            if args.status:
                query["status"] = args.status
            result = call_api(args.api_url, args.admin_token, "GET", "/admin/keys?" + urllib.parse.urlencode(query))
        elif args.key_action == "show":
            result = call_api(args.api_url, args.admin_token, "GET", f"/admin/keys/{args.key_id}")
        elif args.key_action == "mark-sent":
            result = call_api(args.api_url, args.admin_token, "POST", f"/admin/keys/{args.key_id}/mark-sent", {})
        else:
            result = call_api(
                args.api_url,
                args.admin_token,
                "POST",
                f"/admin/keys/{args.key_id}/{args.key_action}",
                {"reason": args.reason},
            )
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
