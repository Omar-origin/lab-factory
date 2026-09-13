#!/usr/bin/env python3
"""Create the minimal optimized runtime payload used by frozen releases."""

from __future__ import annotations

import argparse
import py_compile
import shutil
from pathlib import Path


SCRIPT_NAMES = (
    "apply_fill_map.py",
    "extract_docx_outline.py",
    "inspect_lab_materials.py",
    "scaffold_subject_skill.py",
    "v2_engine.py",
    "native_blocks.py",
    "validate_fill_map.py",
    "validate_scaffolded_skill.py",
    "validate_skill_spec.py",
)
ASSET_NAMES = (
    "content-package-v3.schema.json",
    "content-package-v2.schema.json",
    "requirements-summary-v2.schema.json",
    "section-plan-v2.schema.json",
    "style-card-v2.schema.json",
    "template-profile-v2.schema.json",
    "writing-profile-v2.schema.json",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = Path(args.source).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    allowed_root = (Path(__file__).resolve().parent.parent / "build" / "release-runtime").resolve()
    if allowed_root not in output.parents:
        raise ValueError(f"release staging output must be inside {allowed_root}")
    if output.exists():
        shutil.rmtree(output)
    (output / "scripts").mkdir(parents=True)
    (output / "assets").mkdir()
    (output / "references").mkdir()

    for name in SCRIPT_NAMES:
        source_file = source / "scripts" / name
        destination = output / "scripts" / f"{name}c"
        py_compile.compile(
            str(source_file),
            cfile=str(destination),
            dfile=f"skills/lab-skill-factory/scripts/{name}",
            doraise=True,
            optimize=2,
        )
    for name in ASSET_NAMES:
        shutil.copyfile(source / "assets" / name, output / "assets" / name)
    shutil.copyfile(source / "references" / "v2-workflow.md", output / "references" / "v2-workflow.md")
    shutil.copyfile(source / "references" / "native-media-v3.md", output / "references" / "native-media-v3.md")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
