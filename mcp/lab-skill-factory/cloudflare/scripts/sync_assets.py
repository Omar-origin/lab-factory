#!/usr/bin/env python3
"""Sync shared purchase/admin UI and the ignored payment QR into Worker assets."""

from __future__ import annotations

import shutil
from pathlib import Path


CLOUDFLARE = Path(__file__).resolve().parent.parent
MCP_DIR = CLOUDFLARE.parent


def copy_group(source: Path, target: Path, names: list[str]) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy2(source / name, target / name)


def main() -> int:
    copy_group(MCP_DIR / "auth" / "purchase_ui", CLOUDFLARE / "public" / "buy", ["index.html", "purchase.css", "purchase.js"])
    copy_group(MCP_DIR / "auth" / "control_ui", CLOUDFLARE / "public" / "admin", ["index.html", "control.css", "control.js"])
    qr_source = MCP_DIR / "private" / "payment" / "alipay-business-code.png"
    if not qr_source.is_file():
        raise FileNotFoundError(f"private Alipay payment asset is missing: {qr_source}")
    qr_target = CLOUDFLARE / "public" / "payment-assets" / "alipay.png"
    qr_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(qr_source, qr_target)
    print("Worker assets synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
