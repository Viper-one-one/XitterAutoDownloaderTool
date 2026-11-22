"""Settings and state persistence for XitterAutoDownloaderTool."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from src.models import AnchorRecord


def _default_date_from_iso() -> str:
    """Return midnight UTC 30 days ago as an ISO-8601 string."""
    dt = (datetime.now(timezone.utc) - timedelta(days=30)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return dt.isoformat()


def _default_output_dir() -> str:
    """Return the default user output folder for downloaded bookmark videos."""
    return str(Path.home() / "Videos" / "XBookmarks")


@dataclass
class AppSettings:
    """Persisted user preferences and bookmark anchor state."""

    last_profile_path: str = ""
    output_dir: str = field(default_factory=_default_output_dir)
    recent_output_dirs: list[str] = field(default_factory=list)
    headless: bool = True
    use_anchor_stop: bool = True
    last_anchor: Optional[AnchorRecord] = None
    use_date_filter: bool = True
    date_from_iso: str = field(default_factory=_default_date_from_iso)
    use_date_to_now: bool = True
    date_to_iso: str = ""
    consecutive_old_limit: int = 15
    include_gifs: bool = True
    include_quoted_videos: bool = False
    filename_template: str = "%(uploader_id)s - %(upload_date)s - %(id)s.%(ext)s"
    format_selector: str = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    concurrency: int = 2
    use_download_archive: bool = True
    write_info_json: bool = False
    write_thumbnail: bool = False
    scroll_pause_ms: int = 1200
    max_scrolls: int = 500
    hide_skipped: bool = False
    window_geometry_b64: str = ""
    splitter_sizes: list[int] = field(default_factory=lambda: [430, 180])

    def to_dict(self) -> dict[str, Any]:
        """Convert settings to a JSON-serializable dictionary."""
        data = asdict(self)
        data["last_anchor"] = self.last_anchor.to_dict() if self.last_anchor else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettings:
        """Create AppSettings from persisted JSON dictionary with safe defaults."""
        defaults = cls()
        if not isinstance(data, dict):
            return defaults

        raw_recent = data.get("recent_output_dirs")
        recent_dirs = (
            [str(p) for p in raw_recent if isinstance(p, str) and p.strip()]
            if isinstance(raw_recent, list)
            else []
        )

        raw_splitter = data.get("splitter_sizes")
        splitter_sizes = defaults.splitter_sizes
        if (
            isinstance(raw_splitter, list)
            and len(raw_splitter) == 2
            and all(isinstance(v, int) and v > 0 for v in raw_splitter)
        ):
            splitter_sizes = list(raw_splitter)

        return cls(
            last_profile_path=str(data.get("last_profile_path") or ""),
            output_dir=str(data.get("output_dir") or defaults.output_dir),
            recent_output_dirs=recent_dirs,
            headless=bool(data.get("headless", defaults.headless)),
            use_anchor_stop=bool(data.get("use_anchor_stop", defaults.use_anchor_stop)),
            last_anchor=AnchorRecord.from_dict(data.get("last_anchor")),
            use_date_filter=bool(data.get("use_date_filter", defaults.use_date_filter)),
            date_from_iso=str(data.get("date_from_iso") or defaults.date_from_iso),
            use_date_to_now=bool(data.get("use_date_to_now", defaults.use_date_to_now)),
            date_to_iso=str(data.get("date_to_iso") or ""),
            consecutive_old_limit=max(
                1, int(data.get("consecutive_old_limit", defaults.consecutive_old_limit))
            ),
            include_gifs=bool(data.get("include_gifs", defaults.include_gifs)),
            include_quoted_videos=bool(
                data.get("include_quoted_videos", defaults.include_quoted_videos)
            ),
            filename_template=str(
                data.get("filename_template") or defaults.filename_template
            ),
            format_selector=str(data.get("format_selector") or defaults.format_selector),
            concurrency=max(1, min(8, int(data.get("concurrency", defaults.concurrency)))),
            use_download_archive=bool(
                data.get("use_download_archive", defaults.use_download_archive)
            ),
            write_info_json=bool(data.get("write_info_json", defaults.write_info_json)),
            write_thumbnail=bool(data.get("write_thumbnail", defaults.write_thumbnail)),
            scroll_pause_ms=max(
                200, int(data.get("scroll_pause_ms", defaults.scroll_pause_ms))
            ),
            max_scrolls=max(1, int(data.get("max_scrolls", defaults.max_scrolls))),
            hide_skipped=bool(data.get("hide_skipped", defaults.hide_skipped)),
            window_geometry_b64=str(data.get("window_geometry_b64") or ""),
            splitter_sizes=splitter_sizes,
        )


class ConfigStore:
    """Loads and atomically persists AppSettings to local JSON storage."""


    def __init__(self, state_path: Optional[Path] = None) -> None:
        if state_path is None:
            repo_root = Path(__file__).resolve().parent.parent
            state_path = repo_root / "data" / "state.json"
        self.state_path = Path(state_path)

    def load(self) -> AppSettings:
        """Load settings from disk, falling back gracefully if missing or corrupt."""
        if not self.state_path.exists():
            return AppSettings()
        try:
            raw = self.state_path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            return AppSettings.from_dict(parsed)
        except (OSError, ValueError, TypeError):
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        """Atomically persist settings to disk."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(settings.to_dict(), indent=2, ensure_ascii=False)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".state_", suffix=".tmp", dir=str(self.state_path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp_name, self.state_path)
        except Exception:
            if os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
            raise

    def update_anchor(
        self, settings: AppSettings, anchor: Optional[AnchorRecord]
    ) -> AppSettings:
        """Update the persisted anchor bookmark and immediately save."""
        settings.last_anchor = anchor
        self.save(settings)
        return settings

    def add_recent_output_dir(self, settings: AppSettings, path: str) -> None:
        """Prepend an output directory to recent history, deduplicated to 10 items."""
        cleaned = str(path or "").strip()
        if not cleaned:
            return
        normalized = os.path.normpath(cleaned)
        updated = [normalized]
        for existing in settings.recent_output_dirs:
            if os.path.normpath(existing).lower() != normalized.lower():
                updated.append(existing)
        settings.recent_output_dirs = updated[:10]


class ConfigManager:
    """Compatibility adapter for tests and UI."""

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = Path(storage_dir) if storage_dir else Path.cwd() / "data"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.storage_dir / "state.json"
        self.store = ConfigStore(self.state_file)
        self.settings = self.store.load()
        # Aliases for test compatibility
        self.config = self.settings
        self.state = self.settings

    @property
    def selected_profile_name(self) -> str:
        return self.settings.last_profile_path

    @selected_profile_name.setter
    def selected_profile_name(self, val: str):
        self.settings.last_profile_path = val

    @property
    def save_directory(self) -> str:
        return self.settings.output_dir

    @save_directory.setter
    def save_directory(self, val: str):
        self.settings.output_dir = val

    @property
    def last_anchor_tweet_id(self) -> Optional[str]:
        return self.settings.last_anchor.tweet_id if self.settings.last_anchor else None

    @last_anchor_tweet_id.setter
    def last_anchor_tweet_id(self, val: Optional[str]):
        if val:
            if self.settings.last_anchor:
                self.settings.last_anchor.tweet_id = val
            else:
                self.settings.last_anchor = AnchorRecord(tweet_id=val)
        else:
            self.settings.last_anchor = None

    @property
    def last_anchor_author(self) -> Optional[str]:
        return self.settings.last_anchor.author_handle if self.settings.last_anchor else None

    @last_anchor_author.setter
    def last_anchor_author(self, val: Optional[str]):
        if self.settings.last_anchor:
            self.settings.last_anchor.author_handle = val or ""
        elif val:
            self.settings.last_anchor = AnchorRecord(tweet_id="", author_handle=val)

    def save_config(self):
        self.store.save(self.settings)

    def save_state(self):
        self.store.save(self.settings)

    def update_anchor(self, tweet_id: Optional[str], author: Optional[str] = None, created_at: Optional[str] = None):
        if tweet_id:
            record = AnchorRecord(tweet_id=tweet_id, author_handle=author or "", created_at=created_at)
        else:
            record = None
        self.store.update_anchor(self.settings, record)


AppConfig = AppSettings
AppState = AppSettings

