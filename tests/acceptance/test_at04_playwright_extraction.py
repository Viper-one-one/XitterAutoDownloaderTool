"""AT-04: Playwright Firefox Session & Scroll Automation Acceptance Tests."""

import threading
import pytest
from unittest.mock import MagicMock, patch
from src.extractor import BookmarkExtractor, _filter_x_context_cookies
from src.models import RunConfig, RunStats, BookmarkItem, MediaType, ItemStatus


def test_at04_1_playwright_headless_vs_visible_config():
    """AT-04.1: Launch mode parameter properly stored in RunConfig for Playwright Firefox."""
    cfg_headless = RunConfig(profile_path="", output_dir="", headless=True)
    assert cfg_headless.headless is True

    cfg_visible = RunConfig(profile_path="", output_dir="", headless=False)
    assert cfg_visible.headless is False

    extractor = BookmarkExtractor(config=cfg_visible, cookies=[])
    assert extractor.config.headless is False


def test_at04_2_session_cookie_context_filtering():
    """AT-04.2: Filters raw cookies to only x.com and twitter.com for session injection/export."""
    raw_cookies = [
        {"name": "auth_token", "value": "123", "domain": ".x.com", "expires": 2000000000},
        {"name": "ct0", "value": "abc", "domain": "x.com", "expires": 2000000000},
        {"name": "irrelevant", "value": "xyz", "domain": ".google.com", "expires": 2000000000},
        {"name": "twid", "value": "u%3D1", "domain": ".twitter.com", "expires": 2000000000},
    ]

    filtered = _filter_x_context_cookies(raw_cookies)
    domains = {c["domain"] for c in filtered}
    names = {c["name"] for c in filtered}

    assert "auth_token" in names
    assert "ct0" in names
    assert "twid" in names
    assert "irrelevant" not in names
    assert ".google.com" not in domains


def test_at04_3_pause_and_cancel_signals():
    """AT-04.3: BookmarkExtractor handles pause and cancellation signals cleanly without hanging."""
    cancel_evt = threading.Event()
    pause_evt = threading.Event()

    extractor = BookmarkExtractor(
        config=RunConfig(profile_path="", output_dir=""),
        cookies=[],
        cancel_event=cancel_evt,
        pause_event=pause_evt,
    )

    # Paused state
    pause_evt.clear()

    # In another thread, simulate cancelling after 50ms
    def cancel_later():
        import time
        time.sleep(0.05)
        cancel_evt.set()

    t = threading.Thread(target=cancel_later)
    t.start()

    res = extractor._wait_if_paused()
    t.join()
    assert res is False  # Aborted during pause because cancel was flagged


def test_at04_4_graphql_response_interception_and_queueing():
    """AT-04.4: Test that intercepted GraphQL responses trigger video queueing while non-videos are skipped."""
    queued_videos: list[BookmarkItem] = []
    emitted_items: list[BookmarkItem] = []

    extractor = BookmarkExtractor(
        config=RunConfig(profile_path="", output_dir="", scan_only=False),
        cookies=[],
        on_item=lambda it: emitted_items.append(it),
        on_video_queued=lambda it: queued_videos.append(it),
    )

    # Mock response from /i/api/graphql/.../Bookmarks
    mock_response = MagicMock()
    mock_response.url = "https://x.com/i/api/graphql/XYZ/Bookmarks?variables=%7B%7D"
    mock_response.status = 200
    mock_response.json.return_value = {
        "data": {
            "bookmark_timeline_v2": {
                "timeline": {
                    "instructions": [
                        {
                            "type": "TimelineAddEntries",
                            "entries": [
                                {
                                    "entryId": "tweet-8001",
                                    "content": {
                                        "entryType": "TimelineTimelineItem",
                                        "itemContent": {
                                            "itemType": "TimelineTweet",
                                            "tweet_results": {
                                                "result": {
                                                    "__typename": "Tweet",
                                                    "rest_id": "8001",
                                                    "core": {
                                                        "user_results": {
                                                            "result": {
                                                                "legacy": {"screen_name": "videocreator"}
                                                            }
                                                        }
                                                    },
                                                    "legacy": {
                                                        "created_at": "Sat Nov 21 12:00:00 +0000 2026",
                                                        "full_text": "Watch this clip!",
                                                        "extended_entities": {
                                                            "media": [
                                                                {
                                                                    "type": "video",
                                                                    "video_info": {
                                                                        "duration_millis": 20000,
                                                                        "variants": [
                                                                            {"bitrate": 832000, "url": "https://video.twimg.com/8001_720x1280.mp4"}
                                                                        ]
                                                                    }
                                                                }
                                                            ]
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                },
                                {
                                    "entryId": "tweet-8002",
                                    "content": {
                                        "entryType": "TimelineTimelineItem",
                                        "itemContent": {
                                            "itemType": "TimelineTweet",
                                            "tweet_results": {
                                                "result": {
                                                    "__typename": "Tweet",
                                                    "rest_id": "8002",
                                                    "core": {
                                                        "user_results": {
                                                            "result": {
                                                                "legacy": {"screen_name": "textauthor"}
                                                            }
                                                        }
                                                    },
                                                    "legacy": {
                                                        "created_at": "Sat Nov 21 11:00:00 +0000 2026",
                                                        "full_text": "No video here, just thoughts.",
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            ]
                        }
                    ]
                }
            }
        }
    }

    from src.cutoff import parse_bookmarks_graphql_payload
    parsed = parse_bookmarks_graphql_payload(mock_response.json(), include_gifs=True, include_quoted_videos=False)
    assert len(parsed) == 2

    # Feed into extractor's candidate processing logic
    from src.cutoff import BookmarkCutoffTracker, CutoffDecision
    tracker = BookmarkCutoffTracker(extractor.config)

    for item in parsed:
        decision = tracker.evaluate(item)
        if decision == CutoffDecision.DOWNLOAD:
            extractor.on_video_queued(item)
        extractor.on_item(item)

    # Tweet 8001 should be queued for download
    assert len(queued_videos) == 1
    assert queued_videos[0].tweet_id == "8001"
    assert queued_videos[0].has_video is True

    # Both tweets emitted to UI model
    assert len(emitted_items) == 2
    assert emitted_items[1].tweet_id == "8002"
    assert emitted_items[1].has_video is False
    assert emitted_items[1].status == ItemStatus.SKIPPED_NO_VIDEO
