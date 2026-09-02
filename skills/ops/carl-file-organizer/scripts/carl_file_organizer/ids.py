"""Stable identifiers shared by planner, executor, server and undo.

subject_id identifies a file or directory as it was observed (path + kind +
size + mtime). action_id identifies one proposed operation on that subject.
Both are truncated SHA-256 hex digests; any change to the underlying file
invalidates the id, which is how tampering and drift are detected.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def subject_id(path: Path, kind: str, size: int, modified_ns: int) -> str:
    real = os.path.realpath(str(path))
    material = f"{real}\0{kind}\0{size}\0{modified_ns}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]


def action_id(subject: str, kind: str, destination_portable: str | None) -> str:
    material = f"{subject}\0{kind}\0{destination_portable or ''}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]
