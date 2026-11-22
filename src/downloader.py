"""yt-dlp video download manager and runtime dependency diagnostics."""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Optional

import yt_dlp

from src.models import BookmarkItem, ItemStatus, RunConfig

LogCallback = Callable[[str, str], None]
ItemCallback = Callable[[BookmarkItem], None]


class DownloadCancelledError(Exception):
    """Raised inside yt-dlp hooks when the user stops a download run."""


def check_dependencies() -> dict[str, tuple[bool, str]]:
    """Verify availability of yt-dlp, ffmpeg, and Playwright Firefox."""
    results: dict[str, tuple[bool, str]] = {}

    # 1. yt-dlp
    try:
        ver = getattr(yt_dlp.version, "__version__", "unknown")
        results["yt_dlp"] = (True, f"yt-dlp {ver}")
    except Exception as exc:
        results["yt_dlp"] = (False, f"yt-dlp unavailable: {exc}")

    # 2. ffmpeg
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        results["ffmpeg"] = (False, "ffmpeg not found in PATH")
    else:
        try:
            proc = subprocess.run(
                [ffmpeg_bin, "-version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            first_line = (proc.stdout or proc.stderr or "").splitlines()[0].strip()
            results["ffmpeg"] = (
                proc.returncode == 0,
                first_line or f"ffmpeg ({ffmpeg_bin})",
            )
        except Exception as exc:
            results["ffmpeg"] = (False, f"ffmpeg check failed: {exc}")

    # 3. Playwright Firefox binary
    def _probe_playwright_firefox() -> tuple[bool, str]:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                exe = Path(p.firefox.executable_path)
                if exe.is_file():
                    return True, f"Firefox ready ({exe.parent.name})"
                return False, f"Firefox binary missing at {exe} (run 'playwright install firefox')"
        except Exception as exc:
            return False, f"Playwright Firefox check failed: {exc}"

    # Run inside a helper thread to avoid conflicts if called with an active asyncio loop.
    probe_holder: list[tuple[bool, str]] = []
    probe_thread = threading.Thread(
        target=lambda: probe_holder.append(_probe_playwright_firefox()),
        daemon=True,
    )
    probe_thread.start()
    probe_thread.join(timeout=15)
    results["playwright_firefox"] = (
        probe_holder[0] if probe_holder else (False, "Playwright Firefox probe timed out")
    )

    return results


def _format_speed(bps: Optional[float]) -> str:
    """Format bytes/second as compact human-readable transfer rate."""
    if not bps or bps <= 0:
        return ""
    if bps >= 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f} MB/s"
    if bps >= 1024:
        return f"{bps / 1024:.0f} KB/s"
    return f"{bps:.0f} B/s"


def _format_eta(seconds: Optional[float]) -> str:
    """Format ETA seconds as m:ss or h:mm:ss."""
    if seconds is None or seconds < 0:
        return ""
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class _YtdlpLogger:
    """Adapts yt-dlp logging output to the application log callback."""

    def __init__(self, tweet_id: str, on_log: LogCallback) -> None:
        self.tweet_id = tweet_id
        self.on_log = on_log

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        text = str(msg).strip()
        if text:
            self.on_log("WARN", f"[yt-dlp #{self.tweet_id}] {text}")

    def error(self, msg: str) -> None:
        text = str(msg).strip()
        if text:
            self.on_log("ERROR", f"[yt-dlp #{self.tweet_id}] {text}")


class VideoDownloadManager:
    """Concurrent yt-dlp downloader with progress, archive, and cancel support."""

    def __init__(
        self,
        config: RunConfig,
        cookie_file: Optional[Path] = None,
        on_log: Optional[LogCallback] = None,
        on_item_updated: Optional[ItemCallback] = None,
        cancel_event: Optional[threading.Event] = None,
        pause_event: Optional[threading.Event] = None,
    ) -> None:
        self.config = config
        self.cookie_file = Path(cookie_file) if cookie_file else None
        self.on_log = on_log or (lambda _lvl, _msg: None)
        self.on_item_updated = on_item_updated or (lambda _item: None)
        self.cancel_event = cancel_event or threading.Event()
        if pause_event is None:
            self.pause_event = threading.Event()
            self.pause_event.set()
        else:
            self.pause_event = pause_event

        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(config.concurrency)),
            thread_name_prefix="ytdlp_worker",
        )
        self._futures: list[Future[BookmarkItem]] = []

    def set_cookie_file(self, cookie_file: Optional[Path]) -> None:
        """Update the Netscape cookie file path for subsequent downloads."""
        with self._lock:
            self.cookie_file = Path(cookie_file) if cookie_file else None

    def _get_cookie_file(self) -> Optional[Path]:
        with self._lock:
            return self.cookie_file

    def _archive_path(self) -> Path:
        return Path(self.config.output_dir) / "download_archive.txt"

    def _is_in_archive(self, target_id: str) -> bool:
        """Check whether a post ID already exists in download_archive.txt."""
        if not self.config.use_download_archive:
            return False
        archive_file = self._archive_path()
        if not archive_file.is_file():
            return False
        try:
            with archive_file.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 2 and parts[-1] == target_id:
                        return True
        except OSError:
            pass
        return False

    def _target_tweet_id(self, item: BookmarkItem) -> str:
        """Extract the status ID from effective_download_url (for quoted target support)."""
        url = item.effective_download_url.rstrip("/").split("?")[0]
        last = url.rsplit("/", 1)[-1]
        return last if last.isdigit() else item.tweet_id

    def submit(self, item: BookmarkItem) -> Future[BookmarkItem]:
        """Queue a video bookmark item for background downloading."""
        future = self._executor.submit(self.download_single, item)
        with self._lock:
            self._futures.append(future)
        return future

    def download_single(self, item: BookmarkItem) -> BookmarkItem:
        """Download a single video bookmark via yt-dlp."""
        # Respect pause before starting
        while not self.pause_event.is_set():
            if self.cancel_event.is_set():
                item.status = ItemStatus.CANCELLED
                item.speed_text = ""
                item.eta_text = ""
                self.on_item_updated(item)
                return item
            time.sleep(0.15)

        if self.cancel_event.is_set():
            item.status = ItemStatus.CANCELLED
            item.speed_text = ""
            item.eta_text = ""
            self.on_item_updated(item)
            return item

        target_id = self._target_tweet_id(item)
        if self._is_in_archive(target_id):
            item.status = ItemStatus.SKIPPED_ARCHIVE
            item.progress = 100.0
            item.speed_text = ""
            item.eta_text = ""
            self.on_item_updated(item)
            self.on_log(
                "INFO",
                f"[SKIP] #{item.tweet_id} (@{item.author_handle}) already recorded in download_archive.txt",
            )
            return item

        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        final_filepath: Optional[str] = None
        last_emit_time = 0.0
        last_emit_pct = -1.0

        def check_pause_and_cancel() -> None:
            while not self.pause_event.is_set():
                if self.cancel_event.is_set():
                    raise DownloadCancelledError("Download cancelled by user")
                time.sleep(0.15)
            if self.cancel_event.is_set():
                raise DownloadCancelledError("Download cancelled by user")

        def progress_hook(data: dict[str, Any]) -> None:
            nonlocal final_filepath, last_emit_time, last_emit_pct
            check_pause_and_cancel()

            status = data.get("status")
            if status == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                downloaded = data.get("downloaded_bytes") or 0
                if total and total > 0:
                    pct = min(99.9, max(0.0, (float(downloaded) / float(total)) * 100.0))
                else:
                    pct = item.progress

                now = time.monotonic()
                if (now - last_emit_time) >= 0.15 or abs(pct - last_emit_pct) >= 1.5:
                    item.status = ItemStatus.DOWNLOADING
                    item.progress = pct
                    item.speed_text = _format_speed(data.get("speed"))
                    item.eta_text = _format_eta(data.get("eta"))
                    last_emit_time = now
                    last_emit_pct = pct
                    self.on_item_updated(item)
            elif status == "finished":
                if data.get("filename"):
                    final_filepath = str(data["filename"])
                item.progress = 100.0
                item.speed_text = ""
                item.eta_text = ""
                self.on_item_updated(item)

        def postprocessor_hook(data: dict[str, Any]) -> None:
            nonlocal final_filepath
            check_pause_and_cancel()
            pp_status = data.get("status")
            if pp_status in ("started", "processing"):
                item.status = ItemStatus.MERGING
                item.speed_text = ""
                item.eta_text = ""
                self.on_item_updated(item)
            elif pp_status == "finished":
                info_dict = data.get("info_dict") or {}
                fp = info_dict.get("filepath") or info_dict.get("_filename")
                if fp:
                    final_filepath = str(fp)

        item.status = ItemStatus.DOWNLOADING
        item.progress = 0.0
        item.error_message = ""
        self.on_item_updated(item)

        template = (self.config.filename_template or "").strip() or "%(uploader_id)s - %(upload_date)s - %(id)s.%(ext)s"
        ydl_opts: dict[str, Any] = {
            "outtmpl": str(output_dir / template),
            "format": (self.config.format_selector or "").strip()
            or "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": False,
            "noprogress": True,
            "retries": 3,
            "fragment_retries": 3,
            "concurrent_fragment_downloads": 3,
            "writeinfojson": bool(self.config.write_info_json),
            "writethumbnail": bool(self.config.write_thumbnail),
            "logger": _YtdlpLogger(item.tweet_id, self.on_log),
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [postprocessor_hook],
        }

        cookie_path = self._get_cookie_file()
        if cookie_path and cookie_path.is_file():
            ydl_opts["cookiefile"] = str(cookie_path)

        if self.config.use_download_archive:
            ydl_opts["download_archive"] = str(self._archive_path())

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(item.effective_download_url, download=True)

                if info is None:
                    # yt-dlp returns None when an entry is skipped by download_archive.
                    item.status = ItemStatus.SKIPPED_ARCHIVE
                    item.progress = 100.0
                    item.speed_text = ""
                    item.eta_text = ""
                    self.on_item_updated(item)
                    self.on_log(
                        "INFO",
                        f"[SKIP] #{item.tweet_id} (@{item.author_handle}) skipped by yt-dlp archive",
                    )
                    return item

                resolved_path = final_filepath
                if not resolved_path:
                    req = info.get("requested_downloads")
                    if isinstance(req, list) and req and isinstance(req[0], dict):
                        resolved_path = req[0].get("filepath")
                if not resolved_path:
                    try:
                        resolved_path = ydl.prepare_filename(info)
                    except Exception:
                        resolved_path = ""

                # Fill missing metadata when extracted via DOM fallback
                if not item.resolution and info.get("height"):
                    w = info.get("width")
                    h = info.get("height")
                    short_edge = min(w, h) if (w and h) else h
                    if short_edge:
                        item.resolution = f"{short_edge}p"
                if item.duration_seconds is None and info.get("duration") is not None:
                    try:
                        item.duration_seconds = float(info["duration"])
                    except (TypeError, ValueError):
                        pass

                item.saved_filepath = str(resolved_path or "")
                item.status = ItemStatus.COMPLETE
                item.progress = 100.0
                item.speed_text = ""
                item.eta_text = ""
                self.on_item_updated(item)
                filename_only = Path(item.saved_filepath).name if item.saved_filepath else item.tweet_id
                self.on_log(
                    "SUCCESS",
                    f"[DONE] #{item.tweet_id} (@{item.author_handle}) -> {filename_only}",
                )
        except DownloadCancelledError:
            item.status = ItemStatus.CANCELLED
            item.speed_text = ""
            item.eta_text = ""
            self.on_item_updated(item)
            self.on_log("WARN", f"[CANCEL] #{item.tweet_id} download cancelled")
        except Exception as exc:
            item.status = ItemStatus.FAILED
            item.error_message = str(exc).strip() or type(exc).__name__
            item.speed_text = ""
            item.eta_text = ""
            self.on_item_updated(item)
            self.on_log(
                "ERROR",
                f"[FAIL] #{item.tweet_id} (@{item.author_handle}): {item.error_message}",
            )

        return item

    def wait_all(self) -> list[BookmarkItem]:
        """Wait for all queued downloads to finish and shut down the thread pool."""
        with self._lock:
            pending = list(self._futures)

        completed: list[BookmarkItem] = []
        try:
            for fut in as_completed(pending):
                try:
                    completed.append(fut.result())
                except Exception:
                    pass
        finally:
            self._executor.shutdown(wait=True)
        return completed
