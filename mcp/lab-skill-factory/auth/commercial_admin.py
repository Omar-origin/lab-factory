#!/usr/bin/env python3
"""Local issuer CLI. The private key and ledger never need to leave the seller's device."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline_license import create_issuer, issue_license, read_object, request_hash, utc_now, write_json


def append_ledger(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    if os.name != "nt":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except json.JSONDecodeError:
            continue
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Lab Factory offline license issuer")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-issuer", help="Create the seller-only private key and distributable public key")
    init.add_argument("--private-key", type=Path, required=True)
    init.add_argument("--public-key", type=Path, default=ROOT / "license_public_key.json")
    init.add_argument("--force", action="store_true")

    issue = sub.add_parser("issue-license", help="Sign one device request and write a .lflicense file")
    issue.add_argument("--private-key", type=Path, required=True)
    issue.add_argument("--request", type=Path, required=True)
    issue.add_argument("--output", type=Path, required=True)
    issue.add_argument("--channel-id", default="direct")
    issue.add_argument("--customer-ref", default="", help="Your own order note; do not use sensitive identity data")
    issue.add_argument("--replaces-license-id", default="")
    issue.add_argument("--ledger", type=Path)

    summary = sub.add_parser("summary", help="Show counts from the local append-only issuance ledger")
    summary.add_argument("--ledger", type=Path, required=True)

    note = sub.add_parser("add-note", help="Append a refund/replacement/support note; this cannot revoke an offline copy")
    note.add_argument("--ledger", type=Path, required=True)
    note.add_argument("--license-id", required=True)
    note.add_argument("--kind", choices=["replacement", "duplicate_payment", "unfixable_activation", "legal_requirement", "support"], required=True)
    note.add_argument("--note", default="")

    args = parser.parse_args()
    try:
        if args.command == "init-issuer":
            result = create_issuer(args.private_key.expanduser(), args.public_key.expanduser(), args.force)
            result["warning"] = "私钥只保存在你的设备和离线备份中；绝对不要发送给用户或提交到 Git。"
        elif args.command == "issue-license":
            request = read_object(args.request.expanduser())
            envelope = issue_license(request, args.private_key.expanduser(), args.channel_id, args.replaces_license_id)
            write_json(args.output.expanduser(), envelope)
            ledger = args.ledger.expanduser() if args.ledger else args.private_key.expanduser().with_name("license-ledger.jsonl")
            payload = envelope["payload"]
            append_ledger(ledger, {
                "event": "license_issued", "recorded_at": utc_now(), "license_id": payload["license_id"],
                "request_id": payload["request_id"], "request_sha256": request_hash(request),
                "install_id": payload["install_id"], "channel_id": payload["channel_id"],
                "customer_ref": args.customer_ref.strip(), "replaces_license_id": payload["replaces_license_id"],
            })
            result = {"ok": True, "license_id": payload["license_id"], "output": str(args.output), "ledger": str(ledger),
                      "next_step": "只把 .lflicense 文件发给对应用户；不要发送私钥文件。"}
        elif args.command == "summary":
            rows = read_ledger(args.ledger.expanduser())
            issued = [row for row in rows if row.get("event") == "license_issued"]
            channels: dict[str, int] = {}
            for row in issued:
                channel = str(row.get("channel_id") or "unknown")
                channels[channel] = channels.get(channel, 0) + 1
            result = {"ok": True, "issued": len(issued), "notes": len(rows) - len(issued), "channels": channels}
        else:
            append_ledger(args.ledger.expanduser(), {
                "event": "license_note", "recorded_at": utc_now(), "license_id": args.license_id,
                "kind": args.kind, "note": args.note,
            })
            result = {"ok": True, "license_id": args.license_id, "kind": args.kind,
                      "warning": "已记录本地台账；已发出的离线许可证无法远程吊销。"}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
