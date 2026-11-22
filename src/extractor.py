"""Playwright Firefox automation for extracting X bookmarks."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable, Optional

from playwright.sync_api import Page, Response, sync_playwright

from src.cutoff import (
    BookmarkCutoffTracker,
    CutoffDecision,
    parse_bookmarks_graphql_payload,
    parse_x_datetime,
)
from src.firefox_profile import to_playwright_cookies
from src.models import BookmarkItem, MediaType, RunConfig, RunStats

LogCallback = Callable[[str, str], None]
ItemCallback = Callable[[BookmarkItem], None]
StatusCallback = Callable[[str], None]


class AuthenticationError(RuntimeError):
    """Raised when the Firefox profile lacks a valid authenticated X session."""


def _is_login_url(url: str) -> bool:
    lower = url.lower()
    return "/i/flow/login" in lower or "/login" in lower


def _filter_x_context_cookies(raw_cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep X/Twitter cookies from Playwright context.cookies() for Netscape export."""
    result: list[dict[str, Any]] = []
    for cookie in raw_cookies:
        domain = str(cookie.get("domain") or "").strip()
        norm = domain.lstrip(".").lower()
        if not (
            norm == "x.com"
            or norm.endswith(".x.com")
            or norm == "twitter.com"
            or norm.endswith(".twitter.com")
        ):
            continue
        expires = cookie.get("expires")
        exp_int = int(expires) if isinstance(expires, (int, float)) and expires > 0 else None
        result.append(
            {
                "name": str(cookie.get("name") or ""),
                "value": str(cookie.get("value") or ""),
                "domain": domain,
                "path": str(cookie.get("path") or "/"),
                "expires": exp_int,
                "httpOnly": bool(cookie.get("httpOnly", False)),
                "secure": bool(cookie.get("secure", False)),
                "sameSite": str(cookie.get("sameSite") or "Lax"),
            }
        )
    return result


_DOM_EXTRACT_JS = r"""
() => {
  const articles = Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
  return articles.map(article => {
    const links = Array.from(article.querySelectorAll('a[href*="/status/"]'));
    let statusHref = '';
    for (const a of links) {
      const href = a.getAttribute('href') || '';
      if (/^\/[^/]+\/status\/\d+/.test(href)) {
        statusHref = href;
        break;
      }
    }
    const timeEl = article.querySelector('time');
    const createdAt = timeEl ? (timeEl.getAttribute('datetime') || '') : '';
    const textEl = article.querySelector('[data-testid="tweetText"]');
    const text = textEl ? textEl.innerText : '';

    // Distinguish primary tweet video vs quoted tweet video
    const quoteContainer = article.querySelector('[data-testid="quoteTweet"]');
    const allVideos = Array.from(
      article.querySelectorAll('video, [data-testid="videoPlayer"], [data-testid="videoComponent"]')
    );
    let hasPrimaryVideo = false;
    let hasQuotedVideo = false;
    for (const v of allVideos) {
      if (quoteContainer && quoteContainer.contains(v)) {
        hasQuotedVideo = true;
      } else {
        hasPrimaryVideo = true;
      }
    }
    const hasPhoto = article.querySelector('[data-testid="tweetPhoto"]') !== null;
    return { statusHref, createdAt, text, hasPrimaryVideo, hasQuotedVideo, hasPhoto };
  });
}
"""

_SCROLL_STATE_JS = r"""
() => {
  const doc = document.documentElement;
  const scrollY = window.scrollY || window.pageYOffset || doc.scrollTop || 0;
  const innerHeight = window.innerHeight || 900;
  const scrollHeight = doc.scrollHeight || 0;
  const primary = document.querySelector('[data-testid="primaryColumn"]') || document;
  const hasSpinner = primary.querySelector('[role="progressbar"]') !== null;
  return { scrollY, innerHeight, scrollHeight, hasSpinner };
}
"""


def _read_scroll_state(page: Page) -> dict[str, Any]:
    """Read current viewport scroll position, height, and loading spinner state."""
    try:
        res = page.evaluate(_SCROLL_STATE_JS)
        if isinstance(res, dict):
            return {
                "scrollY": float(res.get("scrollY") or 0),
                "innerHeight": float(res.get("innerHeight") or 900),
                "scrollHeight": float(res.get("scrollHeight") or 0),
                "hasSpinner": bool(res.get("hasSpinner", False)),
            }
        if isinstance(res, (int, float)):
            return {
                "scrollY": float(res),
                "innerHeight": 900.0,
                "scrollHeight": float(res),
                "hasSpinner": False,
            }
    except Exception:
        pass
    return {"scrollY": 0.0, "innerHeight": 900.0, "scrollHeight": 0.0, "hasSpinner": False}


class BookmarkExtractor:
    """Drives Firefox to scroll X bookmarks and stream video posts to the queue."""

    def __init__(
        self,
        config: RunConfig,
        cookies: list[dict[str, Any]],
        on_log: Optional[LogCallback] = None,
        on_item: Optional[ItemCallback] = None,
        on_video_queued: Optional[ItemCallback] = None,
        on_status: Optional[StatusCallback] = None,
        cancel_event: Optional[threading.Event] = None,
        pause_event: Optional[threading.Event] = None,
    ) -> None:
        self.config = config
        self.cookies = cookies
        self.on_log = on_log or (lambda _lvl, _msg: None)
        self.on_item = on_item or (lambda _item: None)
        self.on_video_queued = on_video_queued or (lambda _item: None)
        self.on_status = on_status or (lambda _msg: None)
        self.cancel_event = cancel_event or threading.Event()
        if pause_event is None:
            self.pause_event = threading.Event()
            self.pause_event.set()
        else:
            self.pause_event = pause_event

    def _wait_if_paused(self, page: Optional[Page] = None) -> bool:
        """Block while paused; return False if cancelled while waiting."""
        was_paused = False
        while not self.pause_event.is_set():
            if not was_paused:
                self.on_status("Paused")
                self.on_log("INFO", "Extraction paused.")
                was_paused = True
            if self.cancel_event.is_set():
                return False
            if page is not None:
                page.wait_for_timeout(150)
            else:
                time.sleep(0.15)
        if was_paused:
            self.on_status("Scanning bookmarks...")
            self.on_log("INFO", "Extraction resumed.")
        return not self.cancel_event.is_set()

    def _extract_dom_tweets(self, page: Page) -> list[BookmarkItem]:
        """Fallback DOM inspection when GraphQL response interception yields no rows."""
        try:
            raw_rows = page.evaluate(_DOM_EXTRACT_JS)
        except Exception:
            return []

        items: list[BookmarkItem] = []
        for row in raw_rows or []:
            href = str(row.get("statusHref") or "").strip()
            parts = [p for p in href.split("/") if p]
            if len(parts) < 3 or parts[1] != "status":
                continue
            handle = parts[0]
            tweet_id = parts[2].split("?")[0]
            if not tweet_id.isdigit():
                continue

            has_primary_video = bool(row.get("hasPrimaryVideo"))
            has_quoted_video = bool(row.get("hasQuotedVideo"))
            has_photo = bool(row.get("hasPhoto"))

            if has_primary_video:
                media_type = MediaType.VIDEO
                has_video = True
                is_quoted = False
            elif has_quoted_video:
                media_type = MediaType.QUOTED_VIDEO
                has_video = self.config.include_quoted_videos
                is_quoted = True
            elif has_photo:
                media_type = MediaType.IMAGE
                has_video = False
                is_quoted = False
            else:
                media_type = MediaType.TEXT
                has_video = False
                is_quoted = False

            items.append(
                BookmarkItem(
                    index=0,
                    tweet_id=tweet_id,
                    url=f"https://x.com/{handle}/status/{tweet_id}",
                    author_handle=handle,
                    text=str(row.get("text") or ""),
                    created_at=parse_x_datetime(row.get("createdAt")),
                    media_type=media_type,
                    has_video=has_video,
                    is_quoted_video=is_quoted,
                )
            )
        return items

    def run(self) -> tuple[RunStats, list[dict[str, Any]]]:
        """Execute Firefox bookmark navigation, scrolling, filtering, and queueing."""
        stats = RunStats()
        tracker = BookmarkCutoffTracker(self.config)
        graphql_queue: deque[BookmarkItem] = deque()
        queue_lock = threading.Lock()
        graphql_payload_count = 0
        rate_limited = threading.Event()
        refreshed_cookies = list(self.cookies)

        pw_cookies = to_playwright_cookies(self.cookies)

        def handle_response(response: Response) -> None:
            nonlocal graphql_payload_count
            try:
                url = response.url
                if "/graphql/" not in url or "bookmark" not in url.lower():
                    return
                if response.status == 429:
                    rate_limited.set()
                    self.on_log(
                        "WARN",
                        "[NET] X rate-limited Bookmarks API (HTTP 429). Will back off and retry...",
                    )
                    return
                if response.status != 200:
                    return
                payload = response.json()
            except Exception:
                return

            parsed = parse_bookmarks_graphql_payload(
                payload,
                include_gifs=self.config.include_gifs,
                include_quoted_videos=self.config.include_quoted_videos,
            )
            if parsed:
                graphql_payload_count += 1
                self.on_log(
                    "INFO",
                    f"[NET] Received Bookmarks page #{graphql_payload_count} ({len(parsed)} posts)",
                )
                with queue_lock:
                    graphql_queue.extend(parsed)

        def process_candidate(item: BookmarkItem) -> bool:
            """Evaluate one item; return True if extraction should continue."""
            decision = tracker.evaluate(item)
            if decision == CutoffDecision.DUPLICATE:
                return True

            if decision == CutoffDecision.STOP_ANCHOR:
                stats.stop_reason = tracker.stop_reason
                self.on_log("INFO", f"[STOP] {tracker.stop_reason}")
                return False

            stats.scanned += 1
            if decision == CutoffDecision.STOP_OLD_LIMIT:
                stats.skipped_date += 1
                self.on_item(item)
                stats.stop_reason = tracker.stop_reason
                self.on_log("INFO", f"[STOP] {tracker.stop_reason}")
                return False

            if decision == CutoffDecision.SKIP_DATE:
                stats.skipped_date += 1
                self.on_item(item)
                self.on_log(
                    "INFO",
                    f"[SKIP] #{item.tweet_id} (@{item.author_handle}) outside date range",
                )
                return True

            if decision == CutoffDecision.SKIP_NO_VIDEO:
                stats.skipped_no_video += 1
                self.on_item(item)
                self.on_log(
                    "INFO",
                    f"[SKIP] #{item.tweet_id} (@{item.author_handle}) has no video ({item.media_type.value})",
                )
                return True

            # CutoffDecision.DOWNLOAD
            stats.videos_found += 1
            self.on_item(item)
            detail = f" ({item.details_summary})" if item.details_summary != "--" else ""
            self.on_log(
                "INFO",
                f"[SCAN] #{item.tweet_id} (@{item.author_handle}) - {item.media_type.value}{detail}",
            )
            self.on_video_queued(item)
            return True

        def drain_queue() -> tuple[int, bool]:
            """Drain parsed GraphQL items through tracker. Returns (new_non_dup_count, should_continue)."""
            processed_non_dup = 0
            while True:
                with queue_lock:
                    if not graphql_queue:
                        break
                    item = graphql_queue.popleft()
                before_seen = len(tracker.seen_ids)
                keep_going = process_candidate(item)
                if len(tracker.seen_ids) > before_seen:
                    processed_non_dup += 1
                if not keep_going:
                    return processed_non_dup, False
            return processed_non_dup, True

        mode_label = "headless" if self.config.headless else "visible"
        self.on_status(f"Launching Firefox ({mode_label})...")
        self.on_log("INFO", f"Launching Playwright Firefox ({mode_label} mode)...")

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=self.config.headless)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            try:
                if pw_cookies:
                    try:
                        context.add_cookies(pw_cookies)
                        self.on_log(
                            "INFO",
                            f"Injected {len(pw_cookies)} X/Twitter cookies from Firefox profile.",
                        )
                    except Exception as exc:
                        self.on_log("WARN", f"Some cookies could not be injected: {exc}")

                page = context.new_page()
                page.on("response", handle_response)

                self.on_status("Opening x.com/i/bookmarks...")
                self.on_log("INFO", "Navigating to https://x.com/i/bookmarks")
                page.goto("https://x.com/i/bookmarks", wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(1800)

                if _is_login_url(page.url):
                    if self.config.headless:
                        raise AuthenticationError(
                            "X redirected to the login page. Log into x.com in the selected "
                            "Firefox profile or switch Browser Mode to 'Visible' to sign in."
                        )
                    self.on_status("Waiting for X sign-in in Firefox window...")
                    self.on_log(
                        "WARN",
                        "X login required. Please sign in inside the visible Firefox window (up to 120s)...",
                    )
                    deadline = time.monotonic() + 120.0
                    logged_in = False
                    while time.monotonic() < deadline:
                        if self.cancel_event.is_set():
                            stats.stop_reason = "Cancelled during login wait"
                            return stats, refreshed_cookies
                        page.wait_for_timeout(500)
                        if not _is_login_url(page.url):
                            logged_in = True
                            break
                    if not logged_in:
                        raise AuthenticationError(
                            "Timed out waiting for X sign-in in the visible Firefox window."
                        )
                    if "/bookmarks" not in page.url.lower():
                        page.goto(
                            "https://x.com/i/bookmarks",
                            wait_until="domcontentloaded",
                            timeout=45000,
                        )
                        page.wait_for_timeout(2000)

                # Wait briefly for first tweets to render / GraphQL to respond.
                try:
                    page.wait_for_selector('article[data-testid="tweet"]', timeout=8000)
                except Exception:
                    pass
                page.wait_for_timeout(600)

                # Capture fresh context cookies (useful for yt-dlp after visible login).
                try:
                    live_cookies = _filter_x_context_cookies(context.cookies())
                    if live_cookies:
                        refreshed_cookies = live_cookies
                except Exception:
                    pass

                self.on_status("Scanning bookmarks...")
                stale_scrolls = 0
                spinner_waits = 0
                scroll_index = 0

                def _interruptible_wait(ms: int) -> bool:
                    """Wait ms in short slices; return False if cancelled."""
                    rem = max(0, ms)
                    while rem > 0:
                        if self.cancel_event.is_set():
                            return False
                        step = min(150, rem)
                        page.wait_for_timeout(step)
                        rem -= step
                    return not self.cancel_event.is_set()

                # Drain initial batch
                _, keep_going = drain_queue()
                if keep_going and graphql_payload_count == 0:
                    for dom_item in self._extract_dom_tweets(page):
                        if not process_candidate(dom_item):
                            keep_going = False
                            break

                while keep_going and scroll_index < self.config.max_scrolls:
                    if self.cancel_event.is_set():
                        stats.stop_reason = "Stopped by user"
                        break
                    if not self._wait_if_paused(page):
                        stats.stop_reason = "Stopped by user"
                        break

                    # If X returned HTTP 429, back off before attempting to paginate further.
                    if rate_limited.is_set():
                        rate_limited.clear()
                        self.on_status("Rate-limited by X (backing off 15s)...")
                        if not _interruptible_wait(15000):
                            stats.stop_reason = "Stopped by user"
                            break
                        self.on_status("Scanning bookmarks...")

                    scroll_index += 1
                    prev_state = _read_scroll_state(page)
                    prev_height = prev_state["scrollHeight"]
                    prev_scroll_y = prev_state["scrollY"]

                    try:
                        if graphql_payload_count > 0:
                            # GraphQL captures full post JSON; jump straight to the bottom
                            # sentinel so X immediately fetches the next bookmark page.
                            page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
                        else:
                            # DOM fallback needs incremental steps so virtualized tweets render.
                            page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 0.85))")
                    except Exception:
                        break

                    if not _interruptible_wait(max(200, self.config.scroll_pause_ms)):
                        stats.stop_reason = "Stopped by user"
                        break

                    new_count, keep_going = drain_queue()
                    if keep_going and graphql_payload_count == 0:
                        dom_items = self._extract_dom_tweets(page)
                        for dom_item in dom_items:
                            before_seen = len(tracker.seen_ids)
                            if not process_candidate(dom_item):
                                keep_going = False
                                break
                            if len(tracker.seen_ids) > before_seen:
                                new_count += 1

                    if not keep_going:
                        break

                    post_state = _read_scroll_state(page)
                    new_height = post_state["scrollHeight"]
                    new_scroll_y = post_state["scrollY"]
                    inner_h = post_state["innerHeight"]
                    at_bottom = (new_scroll_y + inner_h) >= (new_height - 250)
                    has_spinner = post_state["hasSpinner"]

                    if new_count > 0:
                        stale_scrolls = 0
                        spinner_waits = 0
                    elif not at_bottom and new_scroll_y > prev_scroll_y:
                        # Still advancing down already-loaded posts; do not count as stale.
                        stale_scrolls = 0
                    elif has_spinner and spinner_waits < 4:
                        # X is actively fetching the next page; give it extra time.
                        spinner_waits += 1
                        if not _interruptible_wait(1000):
                            stats.stop_reason = "Stopped by user"
                            break
                        extra_count, keep_going = drain_queue()
                        if extra_count > 0:
                            stale_scrolls = 0
                            spinner_waits = 0
                        if not keep_going:
                            break
                    elif new_height > prev_height:
                        # Page grew (new DOM items rendered); reset spinner counter and keep going.
                        spinner_waits = 0
                        stale_scrolls += 1
                    else:
                        stale_scrolls += 1
                        spinner_waits = 0
                        # Nudge X's IntersectionObserver sentinel when stuck at the bottom.
                        if stale_scrolls in (2, 4, 6):
                            try:
                                page.evaluate("window.scrollBy(0, -400)")
                                page.wait_for_timeout(300)
                                page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
                            except Exception:
                                pass
                            if not _interruptible_wait(800):
                                stats.stop_reason = "Stopped by user"
                                break
                            extra_count, keep_going = drain_queue()
                            if extra_count > 0:
                                stale_scrolls = 0
                            if not keep_going:
                                break

                    if stale_scrolls >= self.config.max_stale_scrolls:
                        stats.stop_reason = "Reached end of bookmarks feed"
                        self.on_log("INFO", "Reached end of bookmarks feed (no more posts loaded).")
                        break

                if not stats.stop_reason:
                    if tracker.stop_reason:
                        stats.stop_reason = tracker.stop_reason
                    elif scroll_index >= self.config.max_scrolls:
                        stats.stop_reason = f"Reached max scroll limit ({self.config.max_scrolls})"
                    else:
                        stats.stop_reason = "Bookmark scan completed"
            finally:
                try:
                    context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass

        stats.candidate_new_anchor = tracker.candidate_new_anchor
        return stats, refreshed_cookies
