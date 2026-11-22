"""AT-08: Background Worker Threads & Execution Lifecycle Acceptance Tests."""

import threading
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.worker import ExtractionWorker, SingleDownloadWorker
from src.models import BookmarkItem, ItemStatus, MediaType, RunConfig, RunStats, AnchorRecord


def test_at08_1_extraction_worker_lifecycle_success(tmp_path):
    """AT-08.1: Test ExtractionWorker runs through completion, signals stats and anchor candidate."""
    # Create fake cookies.sqlite
    profile_dir = tmp_path / "mock_profile"
    profile_dir.mkdir()
    (profile_dir / "cookies.sqlite").write_text("", encoding="utf-8")

    run_cfg = RunConfig(
        profile_path=str(profile_dir),
        output_dir=str(tmp_path / "out"),
        scan_only=True,
    )

    worker = ExtractionWorker(config=run_cfg)

    received_items = []
    received_logs = []
    received_status = []
    anchor_candidates = []
    finished_results = []

    worker.item_added.connect(received_items.append)
    worker.log_message.connect(lambda lvl, msg: received_logs.append((lvl, msg)))
    worker.status_changed.connect(received_status.append)
    worker.anchor_candidate_ready.connect(anchor_candidates.append)
    worker.run_finished.connect(lambda ok, summary, stats: finished_results.append((ok, summary, stats)))

    # Mock extract_x_cookies and export_netscape_cookies
    mock_cookies = [{"name": "auth_token", "value": "xyz", "domain": ".x.com"}]
    
    mock_stats = RunStats(
        scanned=3,
        videos_found=2,
        skipped_no_video=1,
        stop_reason="Reached bottom of bookmarks",
        candidate_new_anchor=AnchorRecord(tweet_id="999001", author_handle="mockauthor"),
    )

    class MockExtractor:
        def __init__(self, *args, **kwargs):
            self.on_item = kwargs.get("on_item")
            self.on_video_queued = kwargs.get("on_video_queued")

        def run(self):
            # Emit items
            it1 = BookmarkItem(tweet_id="999001", author_handle="mockauthor", has_video=True, media_type=MediaType.VIDEO)
            it2 = BookmarkItem(tweet_id="999002", author_handle="mockauthor", has_video=False, status=ItemStatus.SKIPPED_NO_VIDEO)
            if self.on_item:
                self.on_item(it1)
                self.on_item(it2)
            if self.on_video_queued:
                self.on_video_queued(it1)
            return mock_stats, mock_cookies

    with patch("src.worker.extract_x_cookies", return_value=mock_cookies), \
         patch("src.worker.export_netscape_cookies", return_value=tmp_path / "cookies.txt"), \
         patch("src.worker.BookmarkExtractor", MockExtractor):
        worker.run()

    assert len(finished_results) == 1
    ok, summary, final_stats = finished_results[0]
    assert ok is True
    assert final_stats.scanned == 2
    assert final_stats.videos_found == 1
    assert len(received_items) == 2


def test_at08_2_extraction_worker_cancellation(tmp_path):
    """AT-08.2: Test ExtractionWorker responds cleanly to request_stop."""
    run_cfg = RunConfig(
        profile_path="",
        output_dir=str(tmp_path / "out"),
        scan_only=True,
    )
    worker = ExtractionWorker(config=run_cfg)
    finished_results = []
    worker.run_finished.connect(lambda ok, summary, stats: finished_results.append((ok, summary, stats)))

    # Request stop before running
    worker.request_stop()
    assert worker.cancel_event.is_set()

    class MockExtractorAbort:
        def __init__(self, *args, **kwargs):
            pass
        def run(self):
            return RunStats(stop_reason="Cancelled"), []

    with patch("src.worker.BookmarkExtractor", MockExtractorAbort):
        worker.run()

    assert len(finished_results) == 1
    ok, summary, _ = finished_results[0]
    assert ok is False
    assert "stopped" in summary.lower()


def test_at08_3_single_download_worker(tmp_path):
    """AT-08.3: Test SingleDownloadWorker executes single-item retry and emits finished_one signal."""
    run_cfg = RunConfig(
        profile_path="",
        output_dir=str(tmp_path / "out"),
    )
    item = BookmarkItem(tweet_id="777001", author_handle="retro", has_video=True)
    worker = SingleDownloadWorker(config=run_cfg, item=item)

    finished_events = []
    worker.finished_one.connect(lambda ok, it: finished_events.append((ok, it)))

    class MockSingleDownloadManager:
        def __init__(self, *args, **kwargs):
            pass
        def download_single(self, it):
            it.status = ItemStatus.COMPLETE
            it.progress = 100.0
            return it
        def wait_all(self):
            pass

    with patch("src.worker.VideoDownloadManager", MockSingleDownloadManager):
        worker.run()

    assert len(finished_events) == 1
    ok, it = finished_events[0]
    assert ok is True
    assert it.status == ItemStatus.COMPLETE
    assert it.progress == 100.0
