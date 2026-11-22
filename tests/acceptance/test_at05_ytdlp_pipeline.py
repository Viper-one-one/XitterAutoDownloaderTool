"""AT-05: yt-dlp Download, FFmpeg Merge & Archive Pipeline Acceptance Tests."""

import threading
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from src.downloader import (
    VideoDownloadManager,
    check_dependencies,
    _format_speed,
    _format_eta,
    DownloadCancelledError,
)
from src.models import BookmarkItem, ItemStatus, MediaType, RunConfig


def test_at05_1_check_dependencies():
    """AT-05.1: Dependency diagnostics identify yt-dlp and ffmpeg runtime availability."""
    deps = check_dependencies()
    assert "yt_dlp" in deps
    assert deps["yt_dlp"][0] is True  # Installed in venv
    assert "ffmpeg" in deps
    assert deps["ffmpeg"][0] is True
    assert "7.0" in deps["ffmpeg"][1] or "ffmpeg" in deps["ffmpeg"][1]


def test_at05_2_speed_and_eta_formatting():
    """AT-05.2: Speed and ETA formatting strings conform to compact status display."""
    # Speed
    assert _format_speed(4194304) == "4.0 MB/s"
    assert _format_speed(512000) == "500 KB/s"
    assert _format_speed(0) == ""

    # ETA
    assert _format_eta(65) == "1:05"
    assert _format_eta(3665) == "1:01:05"
    assert _format_eta(None) == ""


def test_at05_3_ytdlp_options_and_cookie_forwarding(tmp_path):
    """AT-05.3: Ensure correct yt-dlp options, format selector, and cookie file are passed to YoutubeDL."""
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n.x.com TRUE / TRUE 2000000000 auth_token abc\n", encoding="utf-8")

    run_cfg = RunConfig(
        profile_path="",
        output_dir=str(tmp_path),
        filename_template="%(id)s.%(ext)s",
        format_selector="bestvideo+bestaudio/best",
        use_download_archive=True,
    )

    manager = VideoDownloadManager(config=run_cfg, cookie_file=cookie_file)
    item = BookmarkItem(
        tweet_id="50001",
        author_handle="uploader1",
        url="https://x.com/uploader1/status/50001",
        has_video=True,
    )

    captured_opts = {}

    class MockYDL:
        def __init__(self, opts):
            nonlocal captured_opts
            captured_opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def extract_info(self, url, download=True):
            return {
                "id": "50001",
                "ext": "mp4",
                "_filename": str(tmp_path / "50001.mp4"),
            }

    with patch("yt_dlp.YoutubeDL", MockYDL):
        res = manager.download_single(item)

    assert res.status == ItemStatus.COMPLETE
    assert captured_opts["cookiefile"] == str(cookie_file)
    assert captured_opts["format"] == "bestvideo+bestaudio/best"
    assert captured_opts["merge_output_format"] == "mp4"
    assert str(tmp_path / "%(id)s.%(ext)s") in captured_opts["outtmpl"]


def test_at05_4_archive_deduplication(tmp_path):
    """AT-05.4: Deduplication using download_archive.txt skips already downloaded tweets."""
    archive_file = tmp_path / "download_archive.txt"
    archive_file.write_text("twitter 18940192831\n", encoding="utf-8")

    run_cfg = RunConfig(
        profile_path="",
        output_dir=str(tmp_path),
        use_download_archive=True,
    )
    manager = VideoDownloadManager(config=run_cfg)

    # Item present in archive
    item_archived = BookmarkItem(
        tweet_id="18940192831",
        author_handle="techclips",
        url="https://x.com/techclips/status/18940192831",
        has_video=True,
        media_type=MediaType.VIDEO,
    )
    res = manager.download_single(item_archived)
    assert res.status == ItemStatus.SKIPPED_ARCHIVE
    assert res.progress == 100.0

    # Item not in archive
    assert not manager._is_in_archive("9999999999")


def test_at05_5_cancellation_during_download(tmp_path):
    """AT-05.5: Download cancellation immediately sets status to CANCELLED."""
    cancel_evt = threading.Event()
    cancel_evt.set()  # Cancelled before start

    run_cfg = RunConfig(profile_path="", output_dir=str(tmp_path))
    manager = VideoDownloadManager(config=run_cfg, cancel_event=cancel_evt)

    item = BookmarkItem(
        tweet_id="18940192832",
        author_handle="techclips",
        url="https://x.com/techclips/status/18940192832",
        has_video=True,
    )
    res = manager.download_single(item)
    assert res.status == ItemStatus.CANCELLED


def test_at05_6_progress_hook_callback_emission(tmp_path):
    """AT-05.6: Verify progress and postprocessor hooks accurately stream live speed and percentage to callbacks."""
    run_cfg = RunConfig(profile_path="", output_dir=str(tmp_path))
    updates: list[BookmarkItem] = []

    def on_update(it):
        # Record copy of state
        updates.append(BookmarkItem(
            tweet_id=it.tweet_id,
            progress=it.progress,
            status=it.status,
            speed_text=it.speed_text,
            eta_text=it.eta_text,
        ))

    manager = VideoDownloadManager(config=run_cfg, on_item_updated=on_update)
    item = BookmarkItem(
        tweet_id="60001",
        author_handle="creator",
        url="https://x.com/creator/status/60001",
        has_video=True,
    )

    class MockYDLProgress:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def extract_info(self, url, download=True):
            hook = self.opts["progress_hooks"][0]
            # Emit downloading at 50%
            hook({
                "status": "downloading",
                "downloaded_bytes": 5242880,
                "total_bytes": 10485760,
                "speed": 2097152,  # 2.0 MB/s
                "eta": 2.5,
            })
            # Emit finished hook
            hook({
                "status": "finished",
                "filename": str(tmp_path / "60001.mp4"),
            })
            return {
                "id": "60001",
                "ext": "mp4",
                "_filename": str(tmp_path / "60001.mp4"),
            }

    with patch("yt_dlp.YoutubeDL", MockYDLProgress):
        res = manager.download_single(item)

    assert res.status == ItemStatus.COMPLETE
    # Check that progress updates occurred
    downloading_updates = [u for u in updates if u.status == ItemStatus.DOWNLOADING and u.progress == 50.0]
    assert len(downloading_updates) >= 1
    assert downloading_updates[0].speed_text == "2.0 MB/s"
