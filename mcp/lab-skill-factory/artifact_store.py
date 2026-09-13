"""Local file receipts. Model assertions are never a substitute for file verification."""

from __future__ import annotations
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path


class ArtifactError(ValueError):
    pass


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".receipt-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def receipt_path(workspace, object_id):
    if not re.fullmatch(r"artifact_[0-9a-f]{64}", str(object_id)):
        raise ArtifactError("Invalid registered artifact ID")
    return (
        Path(workspace).resolve() / "lab-factory" / "artifacts" / (object_id + ".json")
    )


def register(workspace, path, kind="draft"):
    root = Path(workspace).resolve()
    path = Path(path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ArtifactError("Artifact must be an existing file inside workspace")
    sha = digest(path)
    # Path is part of the ID: equal content at a different path is a different receipt.
    relative = str(path.relative_to(root))
    object_id = (
        "artifact_" + hashlib.sha256((relative + "\n" + sha).encode()).hexdigest()
    )
    record = {
        "object_id": object_id,
        "sha256": sha,
        "relative_path": relative,
        "kind": kind,
    }
    target = receipt_path(root, object_id)
    if target.exists():
        return verify(root, object_id, sha)
    write(target, record)
    return record


def verify(workspace, object_id, sha=None, require_audit=False):
    root = Path(workspace).resolve()
    try:
        record = json.loads(receipt_path(root, object_id).read_text())
    except (OSError, ValueError) as e:
        raise ArtifactError("Artifact is not registered") from e
    path = (root / record["relative_path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ArtifactError("Registered artifact is missing or outside workspace")
    if (
        record.get("object_id") != object_id
        or digest(path) != record.get("sha256")
        or (sha and sha != record["sha256"])
    ):
        raise ArtifactError(
            "Artifact changed: regenerate audits and request a new review"
        )
    if require_audit:
        audit = record.get("audit", {})
        if audit.get("sha256") != record["sha256"] or audit.get("status") != "pass":
            raise ArtifactError("No passing local audit bound to this file")
        for dependency in audit.get("dependencies", []):
            verify(root, dependency["object_id"], dependency["sha256"])
    return record


def certify(workspace, record, audit):
    verify(workspace, record["object_id"], record["sha256"])
    record = dict(record, audit=dict(audit, sha256=record["sha256"]))
    write(receipt_path(workspace, record["object_id"]), record)
    return record
