from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "skills"
    / "media"
    / "wechat-article-video-download"
    / "scripts"
    / "download_article_video.py"
)
SPEC = importlib.util.spec_from_file_location("wechat_video_download", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.stream = io.BytesIO(payload)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)


class WeChatVideoDownloadTests(unittest.TestCase):
    def test_url_validation_rejects_wrong_hosts_and_http(self) -> None:
        with self.assertRaises(MODULE.DownloadError):
            MODULE.validate_https_url("https://example.com/article", MODULE.ARTICLE_HOST, "article URL")
        with self.assertRaises(MODULE.DownloadError):
            MODULE.validate_https_url("http://mp.weixin.qq.com/article", MODULE.ARTICLE_HOST, "article URL")

    def test_parse_videos_accepts_agent_browser_string_wrapping(self) -> None:
        videos = [{"index": 1, "src": "https://mpvideo.qpic.cn/video.mp4?vid=wxv_1"}]
        raw = json.dumps(json.dumps(videos))
        self.assertEqual(MODULE.parse_videos(raw), videos)

    def test_download_is_atomic_and_receipt_omits_signed_url(self) -> None:
        payload = b"\x00\x00\x00\x18ftypmp42" + b"demo-payload"
        signed_url = "https://mpvideo.qpic.cn/video.mp4?sig=redacted&vid=wxv_1"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "video.mp4"
            with mock.patch.object(
                MODULE.request, "urlopen", return_value=FakeResponse(payload)
            ):
                receipt = MODULE.download_media(signed_url, output, force=False)

            self.assertEqual(output.read_bytes(), payload)
            self.assertEqual(receipt["bytes"], len(payload))
            self.assertEqual(receipt["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertTrue(receipt["mp4_header_valid"])
            self.assertNotIn("sig", json.dumps(receipt))
            self.assertEqual(list(Path(directory).glob("*.part")), [])

    def test_existing_output_requires_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "video.mp4"
            output.write_bytes(b"existing")
            with self.assertRaises(MODULE.DownloadError):
                MODULE.download_media(
                    "https://mpvideo.qpic.cn/video.mp4", output, force=False
                )
            self.assertEqual(output.read_bytes(), b"existing")

    def test_invalid_mp4_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "video.mp4"
            with mock.patch.object(
                MODULE.request, "urlopen", return_value=FakeResponse(b"not-an-mp4")
            ):
                with self.assertRaises(MODULE.DownloadError):
                    MODULE.download_media(
                        "https://mpvideo.qpic.cn/video.mp4", output, force=False
                    )
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(directory).glob("*.part")), [])

    def test_public_video_id_only_accepts_wechat_ids(self) -> None:
        self.assertEqual(
            MODULE.public_video_id(
                "https://mpvideo.qpic.cn/video.mp4?sig=redacted&vid=wxv_123"
            ),
            "wxv_123",
        )
        self.assertIsNone(
            MODULE.public_video_id("https://mpvideo.qpic.cn/video.mp4?vid=other")
        )


if __name__ == "__main__":
    unittest.main()
