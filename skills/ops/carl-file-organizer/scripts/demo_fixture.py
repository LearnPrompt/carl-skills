#!/usr/bin/env python3
"""Build a fake, throwaway "Downloads"-like directory for CI smoke tests,
manual command walkthroughs, and documentation screenshots.

Zero third-party dependencies. Every path and filename here is invented;
nothing about it should ever resemble a real user's machine or files.

Usage (paths are relative to this skill folder, and the target is yours to pick):
    python3 scripts/demo_fixture.py <target_dir> [--now ISO] [--partitions zh|en]
    python3 scripts/organize.py plan <target_dir> --lang zh

Nothing outside <target_dir> is written, and <target_dir> is created if missing.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------


def _parse_now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


_UTIME_SUPPORTS_SYMLINKS = os.utime in os.supports_follow_symlinks


def set_mtime(path: Path, when: datetime, *, is_symlink: bool = False) -> None:
    ts = when.timestamp()
    if is_symlink:
        if _UTIME_SUPPORTS_SYMLINKS:
            os.utime(path, (ts, ts), follow_symlinks=False)
        # else: leave the symlink's own mtime alone (platform can't set it).
        return
    os.utime(path, (ts, ts))


# ---------------------------------------------------------------------------
# small content writers
# ---------------------------------------------------------------------------


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_repeated_bytes(path: Path, size: int, pattern: bytes = b"GN-demo-") -> None:
    """Write `size` real (non-sparse) bytes, cheaply, without pulling in any
    third-party dependency."""
    path.parent.mkdir(parents=True, exist_ok=True)
    chunk = (pattern * (65536 // len(pattern) + 1))[:65536]
    with path.open("wb") as fh:
        written = 0
        while written < size:
            take = min(len(chunk), size - written)
            fh.write(chunk[:take])
            written += take


def write_sparse_file(path: Path, size: int) -> None:
    """Create a file that *reports* `size` bytes but only consumes disk
    space for the one block actually written (a sparse file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        if size > 0:
            fh.seek(size - 1)
            fh.write(b"\0")
        else:
            fh.truncate(0)


def make_symlink(link_path: Path, target_name: str) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.exists() or link_path.is_symlink():
        link_path.unlink()
    link_path.symlink_to(target_name)


# ---------------------------------------------------------------------------
# fixture assembly
# ---------------------------------------------------------------------------

PARTITION_NAMES = {
    "zh": {
        "inbox": "00_收件箱",
        "library_pdf": "20_知识库/文档资料/PDF",
    },
    "en": {
        "inbox": "00_Inbox",
        "library_pdf": "20_Library/Documents/PDF",
    },
}


def build(target: Path, now: datetime, partitions: str) -> None:
    target.mkdir(parents=True, exist_ok=True)
    ago = lambda **kw: now - timedelta(**kw)  # noqa: E731

    # -- settled documents (past the document aging window) -----------------
    write_text(target / "quarterly-report.pdf", "%PDF-1.4\n% demo placeholder\n")
    set_mtime(target / "quarterly-report.pdf", ago(days=5))

    docs = {
        "notes.md": "# Demo notes\n\nJust placeholder text.\n",
        "slides.pptx": "PK\x03\x04 demo placeholder pptx bytes\n",
        "data.csv": "col_a,col_b\n1,2\n3,4\n",
        "readme.txt": "This is a placeholder readme for the demo fixture.\n",
    }
    for name, content in docs.items():
        write_text(target / name, content)
        set_mtime(target / name, ago(days=3))

    # -- fresh, still inside the aging window --------------------------------
    write_text(target / "fresh-draft.md", "# Draft\n\nStill warm.\n")
    set_mtime(target / "fresh-draft.md", ago(hours=1))

    write_bytes(target / "just-downloaded.zip", b"PK\x05\x06" + b"\x00" * 18)
    set_mtime(target / "just-downloaded.zip", ago(hours=2))

    # -- image / video / web page (settled) ----------------------------------
    media = {
        "photo.png": b"\x89PNG\r\n\x1a\n" + b"demo-placeholder-bytes",
        "screenshot.jpg": b"\xff\xd8\xff\xe0" + b"demo-placeholder-bytes",
        "clip.mp4": b"\x00\x00\x00\x18ftypmp42" + b"demo-placeholder-bytes",
        "page.html": b"<!doctype html><title>demo</title><p>placeholder</p>",
    }
    for name, data in media.items():
        write_bytes(target / name, data)
        set_mtime(target / name, ago(days=3))

    # -- cold archives / installers (past the 7-day archive window) ---------
    write_bytes(target / "old-tool.zip", b"PK\x05\x06" + b"\x00" * 18)
    set_mtime(target / "old-tool.zip", ago(days=10))

    write_repeated_bytes(target / "installer.dmg", 2 * 1024 * 1024)
    set_mtime(target / "installer.dmg", ago(days=12))

    # -- paired archive + extracted directory --------------------------------
    write_bytes(target / "Archive.zip", b"PK\x05\x06" + b"\x00" * 18)
    set_mtime(target / "Archive.zip", ago(days=3))

    write_text(target / "Archive" / "readme-inside.txt", "Extracted placeholder file one.\n")
    write_text(target / "Archive" / "data-inside.txt", "Extracted placeholder file two.\n")
    for p in (target / "Archive" / "readme-inside.txt", target / "Archive" / "data-inside.txt"):
        set_mtime(p, ago(days=3))
    set_mtime(target / "Archive", ago(days=3))

    # -- duplicates -----------------------------------------------------------
    same_content = "Invoice placeholder, both copies are byte-identical.\n"
    write_text(target / "invoice.pdf", same_content)
    write_text(target / "invoice (1).pdf", same_content)
    set_mtime(target / "invoice.pdf", ago(days=3))
    set_mtime(target / "invoice (1).pdf", ago(days=3))

    write_bytes(target / "export.png", b"\x89PNG\r\n\x1a\n" + b"export-A-placeholder")
    write_bytes(target / "export_1.png", b"\x89PNG\r\n\x1a\n" + b"export-B-different-bytes")
    set_mtime(target / "export.png", ago(days=3))
    set_mtime(target / "export_1.png", ago(days=3))

    # -- sensitive naming (content is placeholder, never a real credential) --
    write_text(target / "api-credential.txt", "PLACEHOLDER_NOT_A_REAL_CREDENTIAL\n")
    write_text(
        target / "server.pem",
        "-----BEGIN PLACEHOLDER-----\nthis is not a real certificate\n-----END PLACEHOLDER-----\n",
    )
    write_text(target / "prod.env", "EXAMPLE_KEY=placeholder-not-real\n")
    for name in ("api-credential.txt", "server.pem", "prod.env"):
        set_mtime(target / name, ago(days=2))

    # -- a project-shaped directory -------------------------------------------
    proj = target / "my-project"
    write_text(proj / "package.json", '{"name": "demo-project", "version": "0.0.0"}\n')
    write_text(proj / "src" / "index.js", "console.log('demo');\n")
    write_text(proj / "node_modules" / "left-pad" / "index.js", "module.exports = function leftPad() {};\n")
    write_text(proj / ".git" / "HEAD", "ref: refs/heads/main\n")
    for p in (
        proj / "package.json",
        proj / "src" / "index.js",
        proj / "node_modules" / "left-pad" / "index.js",
        proj / ".git" / "HEAD",
        proj / "src",
        proj / "node_modules" / "left-pad",
        proj / "node_modules",
        proj / ".git",
        proj,
    ):
        set_mtime(p, ago(days=2))

    # -- a worktree-shaped directory (.git is a *file*, not a directory) -----
    worktree = target / "my-project-worktree-fix"
    write_text(worktree / ".git", "gitdir: /tmp/example/.git/worktrees/fix\n")
    set_mtime(worktree / ".git", ago(days=2))
    set_mtime(worktree, ago(days=2))

    # -- one big (sparse) file -------------------------------------------------
    write_sparse_file(target / "big-video.mov", 600 * 1024 * 1024)
    set_mtime(target / "big-video.mov", ago(days=10))

    # -- unknown extension / no extension ---------------------------------------
    write_bytes(target / "mystery.blob", b"\x00\x01\x02demo-placeholder-bytes")
    set_mtime(target / "mystery.blob", ago(days=5))

    write_text(target / "README", "Placeholder file with no extension.\n")
    set_mtime(target / "README", ago(days=5))

    # -- hidden file + symlink ---------------------------------------------------
    write_bytes(target / ".DS_Store", b"\x00\x00\x00\x01Bud1demo-placeholder")
    set_mtime(target / ".DS_Store", ago(days=1))

    make_symlink(target / "link-to-notes.md", "notes.md")
    set_mtime(target / "link-to-notes.md", ago(days=3), is_symlink=True)

    # -- already-existing partition directories (established structure) -------
    names = PARTITION_NAMES[partitions]
    inbox = target / names["inbox"]
    inbox.mkdir(parents=True, exist_ok=True)
    set_mtime(inbox, ago(days=30))

    pdf_dir = target / names["library_pdf"]
    write_text(pdf_dir / "quarterly-report.pdf", "%PDF-1.4\n% already-filed placeholder copy\n")
    set_mtime(pdf_dir / "quarterly-report.pdf", ago(days=20))
    # walk the partition chain and set an established mtime on each level
    parts = names["library_pdf"].split("/")
    cur = target
    for part in parts:
        cur = cur / part
        set_mtime(cur, ago(days=30))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target_dir", type=Path, help="directory to fill with fixture files")
    parser.add_argument("--now", type=str, default=None, help="ISO 8601 timestamp to treat as 'now'")
    parser.add_argument(
        "--partitions",
        choices=("zh", "en"),
        default="zh",
        help="language for the pre-existing partition directory names (default: zh)",
    )
    args = parser.parse_args(argv)

    now = _parse_now(args.now)
    build(args.target_dir.resolve(), now, args.partitions)
    print(f"Demo fixture written to: {args.target_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
