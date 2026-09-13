#!/usr/bin/env python3
"""Adversarial checks for a frozen Lab Factory release artifact."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


RUNTIME_FILES = {
    "skills/lab-skill-factory/scripts/apply_fill_map.pyc",
    "skills/lab-skill-factory/scripts/extract_docx_outline.pyc",
    "skills/lab-skill-factory/scripts/inspect_lab_materials.pyc",
    "skills/lab-skill-factory/scripts/scaffold_subject_skill.pyc",
    "skills/lab-skill-factory/scripts/v2_engine.pyc",
    "skills/lab-skill-factory/scripts/native_blocks.pyc",
    "skills/lab-skill-factory/scripts/validate_fill_map.pyc",
    "skills/lab-skill-factory/scripts/validate_scaffolded_skill.pyc",
    "skills/lab-skill-factory/scripts/validate_skill_spec.pyc",
    "skills/lab-skill-factory/assets/content-package-v2.schema.json",
    "skills/lab-skill-factory/assets/content-package-v3.schema.json",
    "skills/lab-skill-factory/assets/requirements-summary-v2.schema.json",
    "skills/lab-skill-factory/assets/section-plan-v2.schema.json",
    "skills/lab-skill-factory/assets/style-card-v2.schema.json",
    "skills/lab-skill-factory/assets/template-profile-v2.schema.json",
    "skills/lab-skill-factory/assets/writing-profile-v2.schema.json",
    "skills/lab-skill-factory/references/v2-workflow.md",
    "skills/lab-skill-factory/references/native-media-v3.md",
}


def run(command: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, env=env, check=False)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def archive_files(binary: Path) -> set[str]:
    result = run([sys.executable, "-m", "PyInstaller.utils.cliutils.archive_viewer", "-l", str(binary)])
    check(result.returncode == 0, f"cannot inspect PyInstaller archive: {result.stderr[-500:]}")
    found = set()
    for line in result.stdout.splitlines():
        match = re.search(r"'((?:skills/lab-skill-factory)/[^']+)'", line)
        if match:
            found.add(match.group(1))
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    args = parser.parse_args()
    binary = Path(args.binary).expanduser().resolve()
    check(binary.is_file(), f"release binary not found: {binary}")

    bundled = archive_files(binary)
    check(bundled == RUNTIME_FILES, f"release runtime allowlist mismatch: extra={sorted(bundled - RUNTIME_FILES)}, missing={sorted(RUNTIME_FILES - bundled)}")
    check(not any(path.endswith("/SKILL.md") or "/evals/" in path for path in bundled), "factory prompt or eval data leaked into release")

    with tempfile.TemporaryDirectory(prefix="lab-factory-release-security-") as temporary:
        root = Path(temporary)
        marker = root / "arbitrary-script-ran"
        probe = root / "probe.py"
        probe.write_text("from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('ran')\n", encoding="utf-8")
        attempt = run([str(binary), "--run-skill-script", str(probe), str(marker)])
        check(attempt.returncode != 0, "release still accepts the legacy arbitrary script flag")
        check(not marker.exists(), "release executed an arbitrary external Python script")

        fake_skill = root / "attacker-skill"
        fake_vendor = root / "attacker-vendor"
        env = os.environ.copy()
        env["LAB_FACTORY_SKILL_ROOT"] = str(fake_skill)
        env["LAB_FACTORY_VENDOR_DIR"] = str(fake_vendor)
        status = run([str(binary), "status"], env=env)
        check(status.returncode == 0, f"release status failed: {status.stderr[-500:]}")
        payload = json.loads(status.stdout)
        check(Path(payload["skill_root"]).resolve() != fake_skill.resolve(), "frozen release accepted an external skill root")
        check(Path(payload["vendor_dir"]).resolve() != fake_vendor.resolve(), "frozen release accepted an external vendor path")
        install_override = run([str(binary), "install", "--target", "codex", "--dry-run", "--skill-root", str(fake_skill)])
        check(install_override.returncode != 0, "release installer accepted --skill-root")

    test_command = run([str(binary), "test"])
    check(test_command.returncode != 0, "release exposes bundled development tests")
    print(json.dumps({"ok": True, "runtime_files": len(bundled), "arbitrary_script_blocked": True, "external_overrides_blocked": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
