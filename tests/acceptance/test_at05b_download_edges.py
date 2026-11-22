"""Additional unit and integration tests for VideoDownloadManager edge cases."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.downloader import (
    VideoDownloadManager,
    _YtdlpLogger,
    DownloadCancelledError,
)
from src.models import BookmarkItem, ItemStatus, RunConfig


def test_at05_7_ytdlp_logger():
    """Verify _YtdlpLogger warnings and errors route to on_log callback."""
    logs = []
    logger = _YtdlpLogger(tweet_id="12345", on_log=lambda lvl, msg: logs.append((lvl, msg)))
    logger.debug("ignore me")
    logger.info("ignore me too")
    logger.warning("network glitch")
    logger.error("fatal download error")

    assert len(logs) == 2
    assert logs[0][0] == "WARN"
    assert "network glitch" in logs[0][1]
    assert logs[1][0] == "ERROR"
    assert "fatal download error" in logs[1][1]


def test_at05_8_download_manager_failure_and_wait_all(tmp_path):
    """Verify download_single error handling and wait_all completion across thread pool."""
    run_cfg = RunConfig(profile_path="", output_dir=str(tmp_path), concurrency=2)
    manager = VideoDownloadManager(config=run_cfg)

    item1 = BookmarkItem(tweet_id="8801", author_handle="fail_user", has_video=True)
    item2 = BookmarkItem(tweet_id="8802", author_handle="ok_user", has_video=True)

    class MockYDLWithError:
        def __init__(self, opts):
            self.opts = opts
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def extract_info(self, url, download=True):
            if "8801" in url:
                raise RuntimeError("Video unavailable / DRM protected")
            return {
                "id": "8802",
                "ext": "mp4",
                "width": 1280,
                "height": 720,
                "duration": 45.0,
                "_filename": str(tmp_path / "8802.mp4"),
            }
        def prepare_filename(self, info):
            return str(tmp_path / f"{info['id']}.mp4")

    with patch("yt_dlp.YoutubeDL", MockYDLWithError):
        fut1 = manager.submit(item1)
        fut2 = manager.submit(item2)
        results = manager.wait_all()

    assert len(results) == 2
    res_fail = next(r for r in results if r.tweet_id == "8801")
    res_ok = next(r for r in results if r.tweet_id == "8802")

    assert res_fail.status == ItemStatus.FAILED
    assert "DRM protected" in res_fail.error_message

    assert res_ok.status == ItemStatus.COMPLETE
    assert res_ok.resolution == "720p"
    assert res_ok.duration_seconds == 45.0
