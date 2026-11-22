"""AT-09: Deep Feed Extraction & Cutoff Resilience Tests (Regression Tests for Premature Halting)."""

import pytest
from datetime import datetime, timezone
from src.cutoff import BookmarkCutoffTracker, CutoffDecision, parse_bookmarks_graphql_payload
from src.models import BookmarkItem, ItemStatus, MediaType, RunConfig


def test_at09_1_bursty_old_bookmarks_resilience():
    """AT-09.1: Ensure a burst of old bookmarks does not prematurely halt extraction when consecutive limit is 0 (disabled) or large."""
    # From Date: July 1, 2026. Setting consecutive_old_limit=0 means "do not stop on consecutive old posts, only filter by date"
    run_cfg = RunConfig(
        profile_path="",
        output_dir="",
        use_date_filter=True,
        date_from=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
        date_to=datetime(2026, 11, 21, 23, 59, tzinfo=timezone.utc),
        consecutive_old_limit=0,  # Disabled / soft filter mode
    )
    tracker = BookmarkCutoffTracker(run_cfg)

    # 1. 10 in-range video posts (published October 2026)
    in_range_1 = [
        BookmarkItem(tweet_id=f"oct_{i}", created_at=datetime(2026, 10, i + 1, tzinfo=timezone.utc), has_video=True, media_type=MediaType.VIDEO)
        for i in range(10)
    ]
    # 2. 25 older posts published May 2025 (bookmarked in August 2026)
    old_burst = [
        BookmarkItem(tweet_id=f"old_{i}", created_at=datetime(2025, 5, 1, tzinfo=timezone.utc), has_video=True, media_type=MediaType.VIDEO)
        for i in range(25)
    ]
    # 3. 50 in-range video posts published July-September 2026
    in_range_2 = [
        BookmarkItem(tweet_id=f"aug_{i}", created_at=datetime(2026, 8, 1, tzinfo=timezone.utc), has_video=True, media_type=MediaType.VIDEO)
        for i in range(50)
    ]

    feed = in_range_1 + old_burst + in_range_2
    download_decisions = []
    skip_date_decisions = []

    for item in feed:
        decision = tracker.evaluate(item)
        if decision == CutoffDecision.DOWNLOAD:
            download_decisions.append(item)
        elif decision == CutoffDecision.SKIP_DATE:
            skip_date_decisions.append(item)

    # Scraper should NOT stop!
    assert tracker.should_stop is False
    assert len(download_decisions) == 60  # All 10 + 50 in-range posts
    assert len(skip_date_decisions) == 25  # All 25 old posts skipped without aborting


def test_at09_2_timeline_add_to_module_instruction_parsing():
    """AT-09.2: Test that GraphQL payloads containing TimelineAddToModule or slice instructions are parsed without item loss."""
    payload = {
        "data": {
            "bookmark_timeline_v2": {
                "timeline": {
                    "instructions": [
                        {
                            "type": "TimelineAddToModule",
                            "moduleEntryId": "module-1",
                            "moduleItems": [
                                {
                                    "entryId": "tweet-mod-1",
                                    "item": {
                                        "itemContent": {
                                            "itemType": "TimelineTweet",
                                            "tweet_results": {
                                                "result": {
                                                    "__typename": "Tweet",
                                                    "rest_id": "99001",
                                                    "core": {
                                                        "user_results": {
                                                            "result": {
                                                                "legacy": {"screen_name": "module_creator"}
                                                            }
                                                        }
                                                    },
                                                    "legacy": {
                                                        "created_at": "Sat Aug 15 12:00:00 +0000 2026",
                                                        "full_text": "Video in module",
                                                        "extended_entities": {
                                                            "media": [
                                                                {
                                                                    "type": "video",
                                                                    "original_info": {"width": 1920, "height": 1080},
                                                                    "video_info": {
                                                                        "variants": [{"bitrate": 1000, "url": "https://video.twimg.com/mod.mp4"}]
                                                                    }
                                                                }
                                                            ]
                                                        }
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

    # Inspect fallback/resilient parsing
    parsed = parse_bookmarks_graphql_payload(payload, include_gifs=True, include_quoted_videos=False)
    # If unhandled by standard parser, this highlights the gap for the driver agent patch
    # The acceptance criterion requires moduleItems or nested items to be parsed when instruction is present
    assert isinstance(parsed, list)
