"""Qt background worker threads coordinating extraction and yt-dlp downloads."""

from __future__ import annotations

import copy
import tempfile
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from src.downloader import VideoDownloadManager
from src.extractor import AuthenticationError, BookmarkExtractor
from src.firefox_profile import export_netscape_cookies, extract_x_cookies
from src.models import BookmarkItem, ItemStatus, RunConfig, RunStats


class ExtractionWorker(QThread):
    """Runs Firefox bookmark extraction and concurrent yt-dlp downloads off the UI thread."""

    log_message = Signal(str, str)
    item_added = Signal(object)
    item_updated = Signal(object)
    stats_updated = Signal(object)
    status_changed = Signal(str)
    anchor_candidate_ready = Signal(object)
    run_finished = Signal(bool, str, object)

    def __init__(self, config: RunConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.cancel_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()

    def request_stop(self) -> None:
        """Signal extraction and active downloads to abort gracefully."""
        self.cancel_event.set()
        self.pause_event.set()

    def set_paused(self, paused: bool) -> None:
        """Pause or resume both scrolling and download workers."""
        if paused:
            self.pause_event.clear()
        else:
            self.pause_event.set()

    def run(self) -> None:
        stats = RunStats()
        stats_lock = threading.Lock()
        queued_items: list[BookmarkItem] = []
        terminal_counted: set[str] = set()
        download_manager: Optional[VideoDownloadManager] = None

        def emit_stats() -> None:
            with stats_lock:
                snapshot = copy.copy(stats)
            self.stats_updated.emit(snapshot)

        def on_log(level: str, msg: str) -> None:
            self.log_message.emit(level, msg)

        def on_item(item: BookmarkItem) -> None:
            with stats_lock:
                stats.scanned += 1
                if item.status == ItemStatus.SKIPPED_NO_VIDEO:
                    stats.skipped_no_video += 1
                elif item.status == ItemStatus.SKIPPED_OUT_OF_RANGE:
                    stats.skipped_date += 1
                elif item.has_video:
                    stats.videos_found += 1
            self.item_added.emit(item)
            emit_stats()

        def on_item_updated(item: BookmarkItem) -> None:
            if item.status in (
                ItemStatus.COMPLETE,
                ItemStatus.FAILED,
                ItemStatus.SKIPPED_ARCHIVE,
            ):
                with stats_lock:
                    if item.tweet_id not in terminal_counted:
                        terminal_counted.add(item.tweet_id)
                        if item.status == ItemStatus.COMPLETE:
                            stats.downloaded += 1
                        elif item.status == ItemStatus.FAILED:
                            stats.failed += 1
                        elif item.status == ItemStatus.SKIPPED_ARCHIVE:
                            stats.skipped_archive += 1
            self.item_updated.emit(item)
            emit_stats()

        def on_video_queued(item: BookmarkItem) -> None:
            queued_items.append(item)
            if download_manager is not None:
                download_manager.submit(item)

        try:
            with tempfile.TemporaryDirectory(prefix="xitter_run_") as tmp_dir:
                cookie_file: Optional[Path] = None
                cookies = []
                if self.config.profile_path:
                    cookies = extract_x_cookies(Path(self.config.profile_path))
                    if cookies:
                        cookie_file = export_netscape_cookies(
                            cookies, Path(tmp_dir) / "cookies.txt"
                        )
                        on_log(
                            "INFO",
                            f"Loaded {len(cookies)} X/Twitter cookies from Firefox profile.",
                        )
                    else:
                        on_log(
                            "WARN",
                            "No active X/Twitter cookies found in selected profile.",
                        )

                if not self.config.scan_only:
                    download_manager = VideoDownloadManager(
                        config=self.config,
                        cookie_file=cookie_file,
                        on_log=on_log,
                        on_item_updated=on_item_updated,
                        cancel_event=self.cancel_event,
                        pause_event=self.pause_event,
                    )

                extractor = BookmarkExtractor(
                    config=self.config,
                    cookies=cookies,
                    on_log=on_log,
                    on_item=on_item,
                    on_video_queued=on_video_queued,
                    on_status=lambda msg: self.status_changed.emit(msg),
                    cancel_event=self.cancel_event,
                    pause_event=self.pause_event,
                )

                ext_stats, refreshed_cookies = extractor.run()
                with stats_lock:
                    stats.stop_reason = ext_stats.stop_reason
                    stats.candidate_new_anchor = ext_stats.candidate_new_anchor

                if download_manager is not None and refreshed_cookies:
                    updated_cookie_file = export_netscape_cookies(
                        refreshed_cookies, Path(tmp_dir) / "cookies.txt"
                    )
                    download_manager.set_cookie_file(updated_cookie_file)

                if download_manager is not None:
                    if queued_items and not self.cancel_event.is_set():
                        self.status_changed.emit("Finishing active video downloads...")
                        on_log(
                            "INFO",
                            f"Scan finished ({stats.stop_reason}). Waiting for {len(queued_items)} download(s)...",
                        )
                    download_manager.wait_all()

                    # Reconcile exact final tally from queued items
                    with stats_lock:
                        stats.downloaded = sum(
                            1 for it in queued_items if it.status == ItemStatus.COMPLETE
                        )
                        stats.failed = sum(
                            1 for it in queued_items if it.status == ItemStatus.FAILED
                        )
                        stats.skipped_archive = sum(
                            1
                            for it in queued_items
                            if it.status == ItemStatus.SKIPPED_ARCHIVE
                        )

                emit_stats()

                was_cancelled = self.cancel_event.is_set()
                if (
                    not was_cancelled
                    and not self.config.scan_only
                    and stats.candidate_new_anchor is not None
                ):
                    self.anchor_candidate_ready.emit(stats.candidate_new_anchor)

                summary = stats.stop_reason or "Run finished"
                if was_cancelled:
                    self.status_changed.emit("Stopped")
                    self.run_finished.emit(False, "Run stopped by user.", stats)
                else:
                    self.status_changed.emit("Idle")
                    self.run_finished.emit(True, summary, stats)

        except AuthenticationError as exc:
            on_log("ERROR", str(exc))
            self.status_changed.emit("Auth Error")
            self.run_finished.emit(False, str(exc), stats)
        except Exception as exc:
            on_log("ERROR", f"Unexpected worker error: {exc}")
            self.status_changed.emit("Error")
            self.run_finished.emit(False, str(exc), stats)


class SingleDownloadWorker(QThread):
    """Downloads or retries a single bookmark video item via yt-dlp."""

    log_message = Signal(str, str)
    item_updated = Signal(object)
    finished_one = Signal(bool, object)

    def __init__(self, config: RunConfig, item: BookmarkItem, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.item = item

    def run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xitter_retry_") as tmp_dir:
            cookie_file: Optional[Path] = None
            if self.config.profile_path:
                cookies = extract_x_cookies(Path(self.config.profile_path))
                if cookies:
                    cookie_file = export_netscape_cookies(
                        cookies, Path(tmp_dir) / "cookies.txt"
                    )

            manager = VideoDownloadManager(
                config=self.config,
                cookie_file=cookie_file,
                on_log=lambda lvl, msg: self.log_message.emit(lvl, msg),
                on_item_updated=lambda it: self.item_updated.emit(it),
            )
            try:
                result = manager.download_single(self.item)
            finally:
                manager.wait_all()

            ok = result.status in (ItemStatus.COMPLETE, ItemStatus.SKIPPED_ARCHIVE)
            self.finished_one.emit(ok, result)
