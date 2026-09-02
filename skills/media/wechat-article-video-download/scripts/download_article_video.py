#!/usr/bin/env python3
"""Download one public embedded video from a WeChat Official Account article."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import parse, request


ARTICLE_HOST = "mp.weixin.qq.com"
MEDIA_HOST = "mpvideo.qpic.cn"
DOM_EXPRESSION = (
    'JSON.stringify(Array.from(document.querySelectorAll("video"))'
    '.map((v,i)=>({index:i+1,src:v.currentSrc||v.src||""})))'
)


class DownloadError(RuntimeError):
    """Expected, user-facing workflow failure."""


def validate_https_url(value: str, expected_host: str, label: str) -> str:
    parsed = parse.urlparse(value)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != expected_host:
        raise DownloadError(f"{label} must be an https://{expected_host}/ URL")
    return value


def run_browser(session: str, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["agent-browser", "--session", session, *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except FileNotFoundError as exc:
        raise DownloadError("agent-browser is required but was not found") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        # Do not expose captured output: an eval response may contain signed URLs.
        raise DownloadError(f"browser step failed: {args[0]}") from exc
    return completed.stdout.strip()


def parse_videos(raw: str) -> List[Dict[str, Any]]:
    try:
        value: Any = json.loads(raw)
        if isinstance(value, str):
            value = json.loads(value)
    except json.JSONDecodeError as exc:
        raise DownloadError("browser returned invalid video metadata") from exc
    if not isinstance(value, list):
        raise DownloadError("browser returned an unexpected video list")
    return [item for item in value if isinstance(item, dict)]


def discover_media_url(article_url: str, index: int, session: str) -> str:
    run_browser(session, "open", article_url)
    videos: List[Dict[str, Any]] = []
    for attempt in range(3):
        videos = parse_videos(run_browser(session, "eval", DOM_EXPRESSION))
        if len(videos) >= index and videos[index - 1].get("src"):
            break
        if attempt < 2:
            run_browser(session, "wait", "1000")

    if len(videos) < index:
        raise DownloadError(
            f"article exposes {len(videos)} video element(s); index {index} is unavailable"
        )
    media_url = str(videos[index - 1].get("src") or "")
    if not media_url:
        raise DownloadError(f"video {index} has no public media URL")
    return validate_https_url(media_url, MEDIA_HOST, "media URL")


def public_video_id(media_url: str) -> Optional[str]:
    values = parse.parse_qs(parse.urlparse(media_url).query).get("vid", [])
    if values and values[0].startswith("wxv_"):
        return values[0]
    return None


def choose_output(explicit: Optional[str], media_url: str, index: int) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser()
    else:
        video_id = public_video_id(media_url) or f"index-{index}"
        candidate = Path.home() / "Downloads" / f"wechat-video-{video_id}.mp4"
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve()


def has_mp4_header(path: Path) -> bool:
    with path.open("rb") as handle:
        header = handle.read(32)
    return len(header) >= 12 and header[4:8] == b"ftyp"


def download_media(media_url: str, destination: Path, force: bool) -> Dict[str, Any]:
    if destination.exists() and not force:
        raise DownloadError(f"output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    byte_count = 0
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{destination.name}.", suffix=".part",
            dir=str(destination.parent), delete=False
        ) as temporary:
            temp_path = Path(temporary.name)
            media_request = request.Request(
                media_url,
                headers={
                    "Referer": "https://mp.weixin.qq.com/",
                    "User-Agent": "Mozilla/5.0",
                },
            )
            with request.urlopen(media_request, timeout=90) as response:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    temporary.write(chunk)
                    digest.update(chunk)
                    byte_count += len(chunk)

        if byte_count == 0 or temp_path is None:
            raise DownloadError("download returned an empty file")
        if not has_mp4_header(temp_path):
            raise DownloadError("downloaded content is not a valid MP4 container")
        os.replace(str(temp_path), str(destination))
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    return {
        "path": str(destination),
        "bytes": byte_count,
        "sha256": digest.hexdigest(),
        "mp4_header_valid": True,
    }


def probe_media(path: Path) -> Dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return {"available": False}
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-show_entries",
                "format=duration,size:stream=index,codec_type,codec_name,width,height",
                "-of", "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        result = json.loads(completed.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {"available": True, "valid": False}
    return {"available": True, "valid": True, "result": result}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download one embedded MP4 from a public WeChat article."
    )
    parser.add_argument("article_url", help="Public mp.weixin.qq.com article URL")
    parser.add_argument("--index", type=int, default=1, help="1-based video index")
    parser.add_argument("--output", help="Destination .mp4 path")
    parser.add_argument("--force", action="store_true", help="Replace the exact output path")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    session = f"wechat-video-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    try:
        if args.index < 1:
            raise DownloadError("--index must be 1 or greater")
        article_url = validate_https_url(args.article_url, ARTICLE_HOST, "article URL")
        try:
            media_url = discover_media_url(article_url, args.index, session)
        finally:
            try:
                run_browser(session, "close")
            except DownloadError:
                pass

        output = choose_output(args.output, media_url, args.index)
        receipt = download_media(media_url, output, args.force)
        receipt["video_index"] = args.index
        receipt["video_id"] = public_video_id(media_url)
        receipt["ffprobe"] = probe_media(output)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0
    except DownloadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
