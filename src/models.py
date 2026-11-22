"""Core data models and enums for XitterAutoDownloaderTool."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class MediaType(str, Enum):
    """Detected media classification for a bookmarked X post."""

    VIDEO = "Video"
    GIF = "GIF"
    QUOTED_VIDEO = "Quoted Video"
    IMAGE = "Image"
    TEXT = "Text"
    UNKNOWN = "Unknown"


class PostStatus(str, Enum):
    """Processing and download lifecycle status for a bookmark item."""

    READY = "Ready"
    QUEUED = "Queued"
    DOWNLOADING = "Downloading"
    MERGING = "Merging"
    COMPLETE = "Complete"
    ARCHIVED = "Complete (Archived)"
    SKIPPED_NO_VIDEO = "Skipped (No Video)"
    SKIPPED_DATE = "Skipped (Date)"
    SKIPPED_OUT_OF_RANGE = "Skipped (Date Range)"
    SKIPPED_ARCHIVE = "Skipped (Archived)"
    FAILED = "Failed"
    ERROR = "Error"
    CANCELLED = "Cancelled"


# Backwards compatibility alias
ItemStatus = PostStatus


class CutoffAction(str, Enum):
    """Action to take for an evaluated bookmark item."""

    PROCESS = "process"
    SKIP_DATE_RANGE = "skip_date_range"
    STOP_ANCHOR_REACHED = "stop_anchor_reached"
    STOP_THRESHOLD_REACHED = "stop_threshold_reached"


@dataclass
class CutoffConfig:
    """Configuration for cutoff engine."""

    stop_at_anchor: bool = True
    last_anchor_tweet_id: Optional[str] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    consecutive_old_threshold: int = 15



@dataclass
class AnchorRecord:
    """Most-recently-seen bookmark delimiter used to stop incremental runs."""

    tweet_id: str
    author_handle: str = ""
    created_at: Optional[str] = None
    snippet: str = ""
    recorded_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize this anchor record to a JSON-compatible dictionary."""
        return {
            "tweet_id": self.tweet_id,
            "author_handle": self.author_handle,
            "created_at": self.created_at,
            "snippet": self.snippet,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> Optional[AnchorRecord]:
        """Reconstruct an AnchorRecord from persisted JSON data."""
        if not isinstance(data, dict):
            return None
        tweet_id = str(data.get("tweet_id") or "").strip()
        if not tweet_id:
            return None
        return cls(
            tweet_id=tweet_id,
            author_handle=str(data.get("author_handle") or ""),
            created_at=data.get("created_at"),
            snippet=str(data.get("snippet") or ""),
            recorded_at=str(data.get("recorded_at") or ""),
        )


@dataclass
class FirefoxProfile:
    """Discovered local Firefox profile metadata and X cookie auth state."""

    name: str
    path: str
    is_default: bool = False
    is_relative: bool = True
    has_cookies_db: bool = False
    has_x_auth: bool = False
    cookie_summary: str = ""


@dataclass
class BookmarkItem:
    """Represents a single bookmarked post extracted from X."""

    tweet_id: str
    url: str = ""
    author_handle: str = ""
    author_name: str = ""
    text: str = ""
    created_at: Optional[datetime] = None
    media_type: MediaType = MediaType.UNKNOWN
    has_video: bool = False
    is_quoted_video: bool = False
    duration_seconds: Optional[float] = None
    resolution: str = ""
    status: ItemStatus = ItemStatus.QUEUED
    progress: float = 0.0
    speed_text: str = ""
    eta_text: str = ""
    saved_filepath: str = ""
    error_message: str = ""
    download_url: str = ""
    index: int = 0
    video_urls: list[str] = field(default_factory=list)

    def __init__(
        self,
        tweet_id: str,
        author: str = "",
        author_handle: str = "",
        created_at: Optional[datetime] = None,
        media_type: MediaType = MediaType.UNKNOWN,
        has_video: bool = False,
        status: ItemStatus = ItemStatus.QUEUED,
        duration_seconds: Optional[float] = None,
        resolution: str = "",
        url: str = "",
        index: int = 0,
        **kwargs
    ):
        self.tweet_id = str(tweet_id)
        self.author_handle = author_handle or author
        self.author_name = kwargs.get("author_name", "")
        self.url = url or f"https://x.com/i/status/{tweet_id}"
        self.text = kwargs.get("text", "")
        self.created_at = created_at
        self.media_type = media_type
        self.has_video = has_video
        self.is_quoted_video = kwargs.get("is_quoted_video", False)
        self.duration_seconds = duration_seconds
        self.resolution = resolution
        self.status = status
        self.progress = kwargs.get("progress", 0.0)
        self.speed_text = kwargs.get("speed_text", "")
        self.eta_text = kwargs.get("eta_text", "")
        self.saved_filepath = kwargs.get("saved_filepath", "")
        self.error_message = kwargs.get("error_message", "")
        self.download_url = kwargs.get("download_url", "")
        self.index = index
        self.video_urls = kwargs.get("video_urls", [])

    @property
    def author(self) -> str:
        return self.author_handle

    @author.setter
    def author(self, val: str):
        self.author_handle = val


    @property
    def effective_download_url(self) -> str:
        """Return the URL passed to yt-dlp (quoted post URL when targeting quoted video)."""
        return self.download_url or self.url

    @property
    def details_summary(self) -> str:
        """Format compact resolution and duration details for the UI table."""
        parts: list[str] = []
        if self.resolution:
            parts.append(self.resolution)
        if self.duration_seconds is not None and self.duration_seconds >= 0:
            total_sec = int(round(self.duration_seconds))
            hours, remainder = divmod(total_sec, 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours > 0:
                parts.append(f"{hours}:{minutes:02d}:{seconds:02d}")
            else:
                parts.append(f"{minutes}:{seconds:02d}")
        return " ".join(parts) if parts else "--"


@dataclass
class RunConfig:
    """Runtime parameters for a bookmark extraction and download session."""

    profile_path: str
    output_dir: str
    headless: bool = True
    scan_only: bool = False
    use_anchor_stop: bool = True
    anchor_tweet_id: Optional[str] = None
    use_date_filter: bool = True
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    consecutive_old_limit: int = 15
    max_scrolls: int = 500
    include_gifs: bool = True
    include_quoted_videos: bool = False
    filename_template: str = "%(uploader_id)s - %(upload_date)s - %(id)s.%(ext)s"
    format_selector: str = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    concurrency: int = 2
    use_download_archive: bool = True
    write_info_json: bool = False
    write_thumbnail: bool = False
    scroll_pause_ms: int = 1200
    max_stale_scrolls: int = 8


@dataclass
class RunStats:
    """Live and summary counters for an extraction/download run."""

    scanned: int = 0
    videos_found: int = 0
    skipped_no_video: int = 0
    skipped_date: int = 0
    skipped_archive: int = 0
    downloaded: int = 0
    failed: int = 0
    stop_reason: str = ""
    candidate_new_anchor: Optional[AnchorRecord] = field(default=None)
