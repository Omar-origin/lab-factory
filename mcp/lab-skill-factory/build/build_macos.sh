#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
MCP_DIR="$ROOT_DIR/mcp/lab-skill-factory"
DIST_DIR="${DIST_DIR:-$MCP_DIR/dist/macos}"
APP_NAME="${APP_NAME:-lab-factory}"
RUNTIME_SKILL_ROOT="$ROOT_DIR/skills/lab-skill-factory"
STAGED_RUNTIME_ROOT="$MCP_DIR/build/release-runtime/lab-skill-factory"
RELEASE_BUILD="${RELEASE_BUILD:-0}"

if [[ "$RELEASE_BUILD" == "1" && -z "${CODESIGN_IDENTITY:-}" ]]; then
  echo "RELEASE_BUILD=1 requires CODESIGN_IDENTITY; refusing to create an unsigned release artifact." >&2
  exit 2
fi

mkdir -p "$DIST_DIR"
python3 "$MCP_DIR/scripts/stage_release_runtime.py" --source "$RUNTIME_SKILL_ROOT" --output "$STAGED_RUNTIME_ROOT"

python3 -m pip install pyinstaller -r "$MCP_DIR/runtime-requirements.txt"

pyinstaller \
  --clean \
  --optimize 2 \
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
  --add-data "$STAGED_RUNTIME_ROOT:skills/lab-skill-factory" \
  --add-data "$MCP_DIR/license_public_key.json:." \
  --add-data "$MCP_DIR/lease_public_key.json:." \
  "$MCP_DIR/cli.py"

if [[ -n "${CODESIGN_IDENTITY:-}" ]]; then
  codesign --force --timestamp --options runtime --sign "$CODESIGN_IDENTITY" "$DIST_DIR/$APP_NAME"
fi

if [[ "$RELEASE_BUILD" == "1" ]]; then
  codesign --verify --deep --strict --verbose=2 "$DIST_DIR/$APP_NAME"
fi

python3 "$MCP_DIR/scripts/test_release_security.py" --binary "$DIST_DIR/$APP_NAME"

if [[ -n "${NOTARIZE_ZIP:-}" ]]; then
  ditto -c -k --keepParent "$DIST_DIR/$APP_NAME" "$DIST_DIR/$APP_NAME.zip"
  echo "Created $DIST_DIR/$APP_NAME.zip"
  echo "Submit with: xcrun notarytool submit '$DIST_DIR/$APP_NAME.zip' --keychain-profile <profile> --wait"
fi

echo "Built: $DIST_DIR/$APP_NAME"
