#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
MCP_DIR="$ROOT_DIR/mcp/lab-skill-factory"
DIST_DIR="${DIST_DIR:-$MCP_DIR/dist/macos}"
APP_NAME="${APP_NAME:-lab-factory}"

mkdir -p "$DIST_DIR"

python3 -m pip install pyinstaller -r "$MCP_DIR/runtime-requirements.txt"

pyinstaller \
  --clean \
  --onefile \
  --name "$APP_NAME" \
  --distpath "$DIST_DIR" \
  --workpath "$MCP_DIR/build/pyinstaller-work" \
  --specpath "$MCP_DIR/build" \
  --hidden-import docx \
  --hidden-import lxml \
  --hidden-import cryptography \
  --hidden-import keyring.backends.macOS \
  --collect-data docx \
  --add-data "$ROOT_DIR/skills/lab-skill-factory:skills/lab-skill-factory" \
  --add-data "$MCP_DIR/scripts:scripts" \
  --add-data "$MCP_DIR/evals:evals" \
  --add-data "$MCP_DIR/install.py:." \
  --add-data "$MCP_DIR/license_public_key.json:." \
  --add-data "$MCP_DIR/lease_public_key.json:." \
  "$MCP_DIR/cli.py"

if [[ -n "${CODESIGN_IDENTITY:-}" ]]; then
  codesign --force --timestamp --options runtime --sign "$CODESIGN_IDENTITY" "$DIST_DIR/$APP_NAME"
fi

if [[ -n "${NOTARIZE_ZIP:-}" ]]; then
  ditto -c -k --keepParent "$DIST_DIR/$APP_NAME" "$DIST_DIR/$APP_NAME.zip"
  echo "Created $DIST_DIR/$APP_NAME.zip"
  echo "Submit with: xcrun notarytool submit '$DIST_DIR/$APP_NAME.zip' --keychain-profile <profile> --wait"
fi

echo "Built: $DIST_DIR/$APP_NAME"
