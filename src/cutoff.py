"""X GraphQL bookmark payload parsing and dual cutoff state machine."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from src.models import (
    AnchorRecord,
    BookmarkItem,
    ItemStatus,
    MediaType,
    RunConfig,
)

_VARIANT_RES_RE = re.compile(r"/(\d+)x(\d+)/")


class CutoffDecision(str, Enum):
    """Evaluation outcome for a newly observed bookmark post."""

    DUPLICATE = "duplicate"
    STOP_ANCHOR = "stop_anchor"
    STOP_OLD_LIMIT = "stop_old_limit"
    SKIP_DATE = "skip_date"
    SKIP_NO_VIDEO = "skip_no_video"
    DOWNLOAD = "download"


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize a datetime to timezone-aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_x_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse X/Twitter created_at timestamps or ISO strings into UTC datetimes."""
    if not value or not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None

    # Standard Twitter REST/GraphQL timestamp: "Sat Nov 21 18:42:01 +0000 2026"
    try:
        dt = datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y")
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    # ISO-8601 fallback (e.g. DOM <time datetime="2026-11-21T18:42:01.000Z">)
    try:
        iso_str = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        dt = datetime.fromisoformat(iso_str)
        return _ensure_utc(dt)
    except ValueError:
        return None


def _unwrap_tweet_result(result: Any) -> Optional[dict[str, Any]]:
    """Unwrap Tweet or TweetWithVisibilityResults into the core tweet dict."""
    if not isinstance(result, dict):
        return None
    typename = result.get("__typename")
    if typename == "TweetTombstone":
        return None
    if typename == "TweetWithVisibilityResults" or (
        "tweet" in result and "rest_id" not in result
    ):
        inner = result.get("tweet")
        return inner if isinstance(inner, dict) else None
    if result.get("rest_id") or result.get("legacy"):
        return result
    return None


def _extract_author(tweet_obj: dict[str, Any]) -> tuple[str, str]:
    """Extract (screen_name, display_name) across X GraphQL user schema variants."""
    user_result = (
        tweet_obj.get("core", {})
        .get("user_results", {})
        .get("result", {})
    )
    if not isinstance(user_result, dict):
        return "unknown", ""

    core_info = user_result.get("core") or {}
    legacy_info = user_result.get("legacy") or {}

    handle = (
        core_info.get("screen_name")
        or legacy_info.get("screen_name")
        or "unknown"
    )
    name = core_info.get("name") or legacy_info.get("name") or ""
    return str(handle), str(name)


def _extract_tweet_text(tweet_obj: dict[str, Any]) -> str:
    """Extract full post text, preferring long-form note_tweet text when available."""
    note_text = (
        tweet_obj.get("note_tweet", {})
        .get("note_tweet_results", {})
        .get("result", {})
        .get("text")
    )
    if isinstance(note_text, str) and note_text.strip():
        return note_text
    legacy = tweet_obj.get("legacy") or {}
    return str(legacy.get("full_text") or legacy.get("text") or "")


def _format_resolution(width: Optional[int], height: Optional[int]) -> str:
    """Format short resolution badge like '1080p' or '720p'."""
    if width and height and width > 0 and height > 0:
        return f"{min(width, height)}p"
    if height and height > 0:
        return f"{height}p"
    return ""


def _extract_media_resolution(media_item: dict[str, Any]) -> str:
    """Extract resolution string from original_info or MP4 video variants."""
    orig = media_item.get("original_info") or {}
    res = _format_resolution(orig.get("width"), orig.get("height"))
    if res:
        return res

    best_short_edge = 0
    variants = (media_item.get("video_info") or {}).get("variants") or []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        url = str(variant.get("url") or "")
        match = _VARIANT_RES_RE.search(url)
        if match:
            w, h = int(match.group(1)), int(match.group(2))
            best_short_edge = max(best_short_edge, min(w, h))
    return f"{best_short_edge}p" if best_short_edge > 0 else ""


def _inspect_media_list(
    media_list: list[Any], include_gifs: bool
) -> tuple[MediaType, bool, Optional[float], str]:
    """Inspect a list of media entities and return (MediaType, has_video, dur_sec, res)."""
    found_gif: Optional[tuple[Optional[float], str]] = None
    found_image = False

    for entry in media_list:
        if not isinstance(entry, dict):
            continue
        m_type = str(entry.get("type") or "").lower()
        video_info = entry.get("video_info") or {}
        dur_ms = video_info.get("duration_millis")
        dur_sec = (float(dur_ms) / 1000.0) if dur_ms is not None else None
        res = _extract_media_resolution(entry)

        if m_type == "video":
            return MediaType.VIDEO, True, dur_sec, res
        if m_type == "animated_gif":
            if found_gif is None:
                found_gif = (dur_sec, res)
        elif m_type == "photo":
            found_image = True

    if found_gif is not None:
        return MediaType.GIF, include_gifs, found_gif[0], found_gif[1]
    if found_image:
        return MediaType.IMAGE, False, None, ""
    return MediaType.TEXT, False, None, ""


def _inspect_card_media(
    tweet_obj: dict[str, Any], include_gifs: bool
) -> tuple[MediaType, bool, Optional[float], str]:
    """Inspect unified_card or player card metadata for embedded videos."""
    card = tweet_obj.get("card") or {}
    legacy_card = card.get("legacy") or {}
    bindings = legacy_card.get("binding_values") or []
    if not isinstance(bindings, list):
        return MediaType.TEXT, False, None, ""

    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        key = binding.get("key")
        val = binding.get("value") or {}
        if key == "unified_card" and isinstance(val.get("string_value"), str):
            try:
                uc_data = json.loads(val["string_value"])
            except ValueError:
                continue
            media_entities = uc_data.get("media_entities")
            if isinstance(media_entities, dict) and media_entities:
                result = _inspect_media_list(list(media_entities.values()), include_gifs)
                if result[0] in (MediaType.VIDEO, MediaType.GIF):
                    return result
        elif key in ("player_stream_url", "amplify_url") and val.get("string_value"):
            return MediaType.VIDEO, True, None, ""

    return MediaType.TEXT, False, None, ""


def _inspect_tweet_media(
    tweet_obj: dict[str, Any], include_gifs: bool, _depth: int = 0
) -> tuple[MediaType, bool, Optional[float], str]:
    """Determine media classification directly attached to a tweet (or retweeted post)."""
    legacy = tweet_obj.get("legacy") or {}
    ext_media = (legacy.get("extended_entities") or {}).get("media")
    ent_media = (legacy.get("entities") or {}).get("media")

    media_list: list[Any] = []
    if isinstance(ext_media, list) and ext_media:
        media_list = ext_media
    elif isinstance(ent_media, list) and ent_media:
        media_list = ent_media

    primary_result: tuple[MediaType, bool, Optional[float], str] = (
        MediaType.TEXT,
        False,
        None,
        "",
    )
    if media_list:
        primary_result = _inspect_media_list(media_list, include_gifs)
        if primary_result[0] in (MediaType.VIDEO, MediaType.GIF):
            return primary_result

    card_res = _inspect_card_media(tweet_obj, include_gifs)
    if card_res[0] in (MediaType.VIDEO, MediaType.GIF):
        return card_res

    # Unwrap retweeted_status_result if a bookmarked post is a retweet containing video.
    if _depth == 0:
        rt_raw = (
            (legacy.get("retweeted_status_result") or {}).get("result")
            or (tweet_obj.get("retweeted_status_result") or {}).get("result")
        )
        rt_obj = _unwrap_tweet_result(rt_raw)
        if rt_obj is not None:
            rt_res = _inspect_tweet_media(rt_obj, include_gifs=include_gifs, _depth=1)
            if rt_res[0] in (MediaType.VIDEO, MediaType.GIF):
                return rt_res
            if primary_result[0] == MediaType.TEXT and rt_res[0] != MediaType.TEXT:
                return rt_res

    return primary_result


def _tweet_obj_to_bookmark_item(
    tweet_obj: dict[str, Any],
    include_gifs: bool,
    include_quoted_videos: bool,
) -> Optional[BookmarkItem]:
    """Convert an unwrapped GraphQL tweet object into a BookmarkItem."""
    rest_id = str(tweet_obj.get("rest_id") or "").strip()
    if not rest_id:
        return None

    legacy = tweet_obj.get("legacy") or {}
    handle, display_name = _extract_author(tweet_obj)
    text = _extract_tweet_text(tweet_obj)
    created_at = parse_x_datetime(legacy.get("created_at"))
    post_url = f"https://x.com/{handle}/status/{rest_id}"

    media_type, has_video, duration_sec, resolution = _inspect_tweet_media(
        tweet_obj, include_gifs=include_gifs
    )
    is_quoted_video = False
    download_url = ""

    # Check quoted post if primary post has no video/GIF attachment.
    if media_type not in (MediaType.VIDEO, MediaType.GIF):
        quoted_raw = (tweet_obj.get("quoted_status_result") or {}).get("result")
        quoted_obj = _unwrap_tweet_result(quoted_raw)
        if quoted_obj is not None:
            q_type, q_has_video, q_dur, q_res = _inspect_tweet_media(
                quoted_obj, include_gifs=include_gifs
            )
            if q_type == MediaType.VIDEO or (q_type == MediaType.GIF and include_gifs):
                is_quoted_video = True
                media_type = MediaType.QUOTED_VIDEO
                has_video = include_quoted_videos and q_has_video
                duration_sec = q_dur
                resolution = q_res
                if has_video:
                    q_id = str(quoted_obj.get("rest_id") or "").strip()
                    q_handle, _ = _extract_author(quoted_obj)
                    if q_id:
                        download_url = f"https://x.com/{q_handle}/status/{q_id}"

    return BookmarkItem(
        index=0,
        tweet_id=rest_id,
        url=post_url,
        author_handle=handle,
        author_name=display_name,
        text=text,
        created_at=created_at,
        media_type=media_type,
        has_video=has_video,
        is_quoted_video=is_quoted_video,
        duration_seconds=duration_sec,
        resolution=resolution,
        download_url=download_url,
    )


def _extract_entries_from_instructions(instructions: list[Any]) -> list[dict[str, Any]]:
    """Collect timeline entries from X GraphQL timeline instructions."""
    collected: list[dict[str, Any]] = []
    for inst in instructions:
        if not isinstance(inst, dict):
            continue
        inst_type = inst.get("type")
        if inst_type == "TimelineAddEntries" and isinstance(inst.get("entries"), list):
            collected.extend(e for e in inst["entries"] if isinstance(e, dict))
        elif inst_type == "TimelineReplaceEntry" and isinstance(inst.get("entry"), dict):
            collected.append(inst["entry"])
        elif inst_type == "TimelineAddToModule" and isinstance(inst.get("moduleItems"), list):
            collected.append({"entryId": "module-items", "content": {"items": inst["moduleItems"]}})
        elif isinstance(inst.get("entries"), list):
            collected.extend(e for e in inst["entries"] if isinstance(e, dict))
    return collected


def parse_bookmarks_graphql_payload(
    payload: dict[str, Any],
    include_gifs: bool = True,
    include_quoted_videos: bool = False,
) -> list[BookmarkItem]:
    """Parse X Bookmarks GraphQL JSON payload into ordered BookmarkItem instances."""
    if not isinstance(payload, dict):
        return []

    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return []

    timeline = (
        (data.get("bookmark_timeline_v2") or {}).get("timeline")
        or (data.get("bookmark_timeline") or {}).get("timeline")
        or {}
    )
    instructions = timeline.get("instructions")
    if not isinstance(instructions, list):
        return []

    items: list[BookmarkItem] = []
    for entry in _extract_entries_from_instructions(instructions):
        entry_id = str(entry.get("entryId") or "")
        if entry_id.startswith(("cursor-", "promoted-")):
            continue

        content = entry.get("content") or {}
        if not isinstance(content, dict):
            continue
        if content.get("entryType") == "TimelineTimelineCursor":
            continue

        # Single tweet entry
        item_content = content.get("itemContent") or {}
        if isinstance(item_content, dict) and "tweet_results" in item_content:
            if item_content.get("promotedMetadata"):
                continue
            tweet_obj = _unwrap_tweet_result(
                (item_content.get("tweet_results") or {}).get("result")
            )
            if tweet_obj is not None:
                parsed = _tweet_obj_to_bookmark_item(
                    tweet_obj,
                    include_gifs=include_gifs,
                    include_quoted_videos=include_quoted_videos,
                )
                if parsed is not None:
                    items.append(parsed)
            continue

        # Module entry (occasionally wraps multiple items)
        sub_items = content.get("items")
        if isinstance(sub_items, list):
            for sub in sub_items:
                if not isinstance(sub, dict):
                    continue
                sub_ic = (sub.get("item") or {}).get("itemContent") or {}
                if not isinstance(sub_ic, dict) or sub_ic.get("promotedMetadata"):
                    continue
                tweet_obj = _unwrap_tweet_result(
                    (sub_ic.get("tweet_results") or {}).get("result")
                )
                if tweet_obj is not None:
                    parsed = _tweet_obj_to_bookmark_item(
                        tweet_obj,
                        include_gifs=include_gifs,
                        include_quoted_videos=include_quoted_videos,
                    )
                    if parsed is not None:
                        items.append(parsed)

    return items


class BookmarkCutoffTracker:
    """Stateful evaluator enforcing Anchor Stop + Date Range + Old-Post Fallback."""

    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self.seen_ids: set[str] = set()
        self.candidate_new_anchor: Optional[AnchorRecord] = None
        self.consecutive_old_count: int = 0
        self.should_stop: bool = False
        self.stop_reason: str = ""
        self.next_index: int = 1
        self._date_from = _ensure_utc(config.date_from)
        self._date_to = _ensure_utc(config.date_to)

    def evaluate(self, item: BookmarkItem) -> CutoffDecision:
        """Evaluate a discovered bookmark in feed order (newest-bookmarked first)."""
        if item.tweet_id in self.seen_ids:
            return CutoffDecision.DUPLICATE
        self.seen_ids.add(item.tweet_id)

        # Primary delimiter: stop immediately when we see the last-run anchor bookmark.
        if (
            self.config.use_anchor_stop
            and self.config.anchor_tweet_id
            and item.tweet_id == self.config.anchor_tweet_id
        ):
            self.should_stop = True
            self.stop_reason = (
                f"Reached last seen bookmark anchor (#{item.tweet_id})"
            )
            return CutoffDecision.STOP_ANCHOR

        # Capture the very first valid post (top of bookmarks) as next run's anchor.
        if self.candidate_new_anchor is None:
            snippet = (item.text or "").replace("\n", " ").strip()
            if len(snippet) > 80:
                snippet = snippet[:77] + "..."
            self.candidate_new_anchor = AnchorRecord(
                tweet_id=item.tweet_id,
                author_handle=item.author_handle,
                created_at=item.created_at.isoformat() if item.created_at else None,
                snippet=snippet,
                recorded_at=datetime.now(timezone.utc).isoformat(),
            )

        item.index = self.next_index
        self.next_index += 1

        # Fallback cutoff: filter by publication date range and consecutive old post count.
        if self.config.use_date_filter and item.created_at is not None:
            item_dt = _ensure_utc(item.created_at)
            assert item_dt is not None

            if self._date_to is not None and item_dt > self._date_to:
                item.status = ItemStatus.SKIPPED_OUT_OF_RANGE
                return CutoffDecision.SKIP_DATE

            if self._date_from is not None and item_dt < self._date_from:
                self.consecutive_old_count += 1
                item.status = ItemStatus.SKIPPED_OUT_OF_RANGE
                limit = self.config.consecutive_old_limit
                if limit > 0 and self.consecutive_old_count >= limit:
                    self.should_stop = True
                    self.stop_reason = (
                        f"Stopped after {self.consecutive_old_count} consecutive posts "
                        f"older than {self._date_from.strftime('%Y-%m-%d')}"
                    )
                    return CutoffDecision.STOP_OLD_LIMIT
                return CutoffDecision.SKIP_DATE

            # Post falls inside [date_from, date_to]; reset consecutive old streak.
            self.consecutive_old_count = 0

        if not item.has_video:
            item.status = ItemStatus.SKIPPED_NO_VIDEO
            return CutoffDecision.SKIP_NO_VIDEO

        item.status = ItemStatus.QUEUED
        return CutoffDecision.DOWNLOAD
