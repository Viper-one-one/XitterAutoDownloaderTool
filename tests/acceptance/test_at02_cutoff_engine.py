"""AT-02: Dual Cutoff Engine (Anchor Bookmark Delimiter + Date-Range Fallback) Acceptance Tests."""

import pytest
from datetime import datetime, timezone
from src.cutoff import BookmarkCutoffTracker, CutoffDecision
from src.models import BookmarkItem, MediaType, RunConfig, AnchorRecord
from src.config import ConfigStore, AppSettings


def test_at02_1_first_run_date_range_and_consecutive_cutoff():
    """AT-02.1: First run with no anchor, stops after N consecutive old posts."""
    # From Date: Oct 1, 2026. Consecutive limit: 3
    run_config = RunConfig(
        profile_path="",
        output_dir="",
        use_anchor_stop=True,
        anchor_tweet_id=None,
        use_date_filter=True,
        date_from=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
        date_to=None,
        consecutive_old_limit=3,
    )
    tracker = BookmarkCutoffTracker(run_config)
    
    # 1. In-range video post (Oct 20) -> DOWNLOAD
    item1 = BookmarkItem(tweet_id="101", created_at=datetime(2026, 10, 20, tzinfo=timezone.utc), has_video=True, media_type=MediaType.VIDEO)
    decision1 = tracker.evaluate(item1)
    assert decision1 == CutoffDecision.DOWNLOAD
    assert tracker.candidate_new_anchor.tweet_id == "101"
    assert tracker.consecutive_old_count == 0
    
    # 2. In-range video post (Oct 15) -> DOWNLOAD
    item2 = BookmarkItem(tweet_id="102", created_at=datetime(2026, 10, 15, tzinfo=timezone.utc), has_video=True, media_type=MediaType.VIDEO)
    decision2 = tracker.evaluate(item2)
    assert decision2 == CutoffDecision.DOWNLOAD
    assert tracker.consecutive_old_count == 0
    
    # 3. Old post (Sept 15) -> SKIP_DATE, count = 1
    item3 = BookmarkItem(tweet_id="103", created_at=datetime(2026, 9, 15, tzinfo=timezone.utc), has_video=True, media_type=MediaType.VIDEO)
    decision3 = tracker.evaluate(item3)
    assert decision3 == CutoffDecision.SKIP_DATE
    assert tracker.consecutive_old_count == 1
    
    # 4. Out-of-order in-range post (Oct 5) -> DOWNLOAD, resets count to 0!
    item4 = BookmarkItem(tweet_id="104", created_at=datetime(2026, 10, 5, tzinfo=timezone.utc), has_video=True, media_type=MediaType.VIDEO)
    decision4 = tracker.evaluate(item4)
    assert decision4 == CutoffDecision.DOWNLOAD
    assert tracker.consecutive_old_count == 0
    
    # 5. Consecutive old post 1 (Sept 10) -> count = 1
    item5 = BookmarkItem(tweet_id="105", created_at=datetime(2026, 9, 10, tzinfo=timezone.utc), has_video=True, media_type=MediaType.VIDEO)
    assert tracker.evaluate(item5) == CutoffDecision.SKIP_DATE
    assert tracker.consecutive_old_count == 1
    
    # 6. Consecutive old post 2 (Sept 9) -> count = 2
    item6 = BookmarkItem(tweet_id="106", created_at=datetime(2026, 9, 9, tzinfo=timezone.utc), has_video=True, media_type=MediaType.VIDEO)
    assert tracker.evaluate(item6) == CutoffDecision.SKIP_DATE
    assert tracker.consecutive_old_count == 2
    
    # 7. Consecutive old post 3 (Sept 1) -> count = 3 == limit -> STOP!
    item7 = BookmarkItem(tweet_id="107", created_at=datetime(2026, 9, 1, tzinfo=timezone.utc), has_video=True, media_type=MediaType.VIDEO)
    assert tracker.evaluate(item7) == CutoffDecision.STOP_OLD_LIMIT
    assert tracker.should_stop is True
    
    # Topmost bookmark captured
    assert tracker.candidate_new_anchor.tweet_id == "101"


def test_at02_2_repeat_run_stop_at_anchor():
    """AT-02.2: Halts immediately upon encountering stored last_anchor_tweet_id."""
    run_config = RunConfig(
        profile_path="",
        output_dir="",
        use_anchor_stop=True,
        anchor_tweet_id="1005",
        use_date_filter=False,
    )
    tracker = BookmarkCutoffTracker(run_config)
    
    item1 = BookmarkItem(tweet_id="1009", created_at=datetime(2026, 11, 20, tzinfo=timezone.utc), has_video=True)
    assert tracker.evaluate(item1) == CutoffDecision.DOWNLOAD
    assert tracker.candidate_new_anchor.tweet_id == "1009"
    
    item2 = BookmarkItem(tweet_id="1008", created_at=datetime(2026, 11, 19, tzinfo=timezone.utc), has_video=True)
    assert tracker.evaluate(item2) == CutoffDecision.DOWNLOAD
    
    # Hits anchor
    item3 = BookmarkItem(tweet_id="1005", created_at=datetime(2026, 11, 18, tzinfo=timezone.utc), has_video=True)
    assert tracker.evaluate(item3) == CutoffDecision.STOP_ANCHOR
    assert tracker.should_stop is True
    assert tracker.candidate_new_anchor.tweet_id == "1009"


def test_at02_3_deleted_or_unbookmarked_anchor_fallback():
    """AT-02.3: When anchor is missing/deleted, falls back to date range cutoff."""
    run_config = RunConfig(
        profile_path="",
        output_dir="",
        use_anchor_stop=True,
        anchor_tweet_id="9999", # Doesn't exist in feed
        use_date_filter=True,
        date_from=datetime(2026, 10, 1, tzinfo=timezone.utc),
        consecutive_old_limit=2,
    )
    tracker = BookmarkCutoffTracker(run_config)
    
    # In range
    item1 = BookmarkItem(tweet_id="2001", created_at=datetime(2026, 10, 15, tzinfo=timezone.utc), has_video=True)
    assert tracker.evaluate(item1) == CutoffDecision.DOWNLOAD
    
    # Consecutive old posts
    item2 = BookmarkItem(tweet_id="2002", created_at=datetime(2026, 9, 20, tzinfo=timezone.utc), has_video=True)
    assert tracker.evaluate(item2) == CutoffDecision.SKIP_DATE
    
    item3 = BookmarkItem(tweet_id="2003", created_at=datetime(2026, 9, 19, tzinfo=timezone.utc), has_video=True)
    assert tracker.evaluate(item3) == CutoffDecision.STOP_OLD_LIMIT
    assert tracker.should_stop is True
    assert tracker.candidate_new_anchor.tweet_id == "2001"


def test_at02_4_upper_bound_to_date_filtering():
    """AT-02.4: Posts newer than to_date are skipped but do not count as 'older than from_date'."""
    run_config = RunConfig(
        profile_path="",
        output_dir="",
        use_date_filter=True,
        date_from=datetime(2026, 10, 1, tzinfo=timezone.utc),
        date_to=datetime(2026, 11, 1, tzinfo=timezone.utc),
        consecutive_old_limit=2,
    )
    tracker = BookmarkCutoffTracker(run_config)
    
    # Newer than to_date (Nov 15)
    item_new = BookmarkItem(tweet_id="3001", created_at=datetime(2026, 11, 15, tzinfo=timezone.utc), has_video=True)
    action = tracker.evaluate(item_new)
    assert action == CutoffDecision.SKIP_DATE
    assert tracker.consecutive_old_count == 0  # Should NOT increment consecutive old counter!
    
    # Inside range (Oct 20)
    item_in = BookmarkItem(tweet_id="3002", created_at=datetime(2026, 10, 20, tzinfo=timezone.utc), has_video=True)
    assert tracker.evaluate(item_in) == CutoffDecision.DOWNLOAD
    assert tracker.consecutive_old_count == 0
    
    # Older than from_date (Sept 1)
    item_old = BookmarkItem(tweet_id="3003", created_at=datetime(2026, 9, 1, tzinfo=timezone.utc), has_video=True)
    assert tracker.evaluate(item_old) == CutoffDecision.SKIP_DATE
    assert tracker.consecutive_old_count == 1


def test_at02_5_anchor_preservation_on_abort(tmp_path):
    """AT-02.5: Anchor state is only committed on clean completion, not on abort."""
    store = ConfigStore(state_path=tmp_path / "state.json")
    settings = AppSettings(last_anchor=AnchorRecord(tweet_id="initial_anchor_100"))
    store.save(settings)
    
    run_config = RunConfig(
        profile_path="",
        output_dir="",
        use_anchor_stop=True,
        anchor_tweet_id=settings.last_anchor.tweet_id,
    )
    tracker = BookmarkCutoffTracker(run_config)
    
    # Discovers top bookmark
    item = BookmarkItem(tweet_id="new_top_500", created_at=datetime.now(timezone.utc), has_video=True)
    tracker.evaluate(item)
    assert tracker.candidate_new_anchor.tweet_id == "new_top_500"
    
    # Simulating abort/crash: do not save tracker.candidate_new_anchor
    loaded_after_abort = store.load()
    assert loaded_after_abort.last_anchor.tweet_id == "initial_anchor_100"
    
    # When completed cleanly:
    store.update_anchor(loaded_after_abort, tracker.candidate_new_anchor)
    reloaded_clean = store.load()
    assert reloaded_clean.last_anchor.tweet_id == "new_top_500"
