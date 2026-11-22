"""AT-03: Video Detection & Non-Video Skipping Acceptance Tests."""

import pytest
from src.cutoff import parse_bookmarks_graphql_payload, _tweet_obj_to_bookmark_item, _unwrap_tweet_result
from src.models import MediaType, ItemStatus


def test_at03_1_native_video_detection(mock_tweet_factory):
    """AT-03.1: Native X Video post detection, duration, and resolution extraction."""
    raw = mock_tweet_factory(
        tweet_id="18940192831",
        created_at_str="Wed Nov 21 18:42:00 +0000 2026",
        author="techclips",
        media_type="video"
    )
    
    tweet_obj = _unwrap_tweet_result(raw.get("result"))
    item = _tweet_obj_to_bookmark_item(tweet_obj, include_gifs=True, include_quoted_videos=True)
    
    assert item is not None
    assert item.tweet_id == "18940192831"
    assert item.author_handle == "techclips"
    assert item.media_type == MediaType.VIDEO
    assert item.has_video is True
    assert item.duration_seconds == 45
    assert "1080" in item.resolution or "720" in item.resolution


def test_at03_2_text_only_skipping(mock_tweet_factory):
    """AT-03.2: Text-only post skipping without video dispatch."""
    raw = mock_tweet_factory(
        tweet_id="18939910294",
        created_at_str="Wed Nov 21 14:15:00 +0000 2026",
        author="newsdesk",
        media_type="none"
    )
    
    tweet_obj = _unwrap_tweet_result(raw.get("result"))
    item = _tweet_obj_to_bookmark_item(tweet_obj, include_gifs=True, include_quoted_videos=True)
    
    assert item is not None
    assert item.media_type in (MediaType.TEXT, MediaType.UNKNOWN)
    assert item.has_video is False


def test_at03_3_image_only_skipping(mock_tweet_factory):
    """AT-03.3: Photo/multi-photo post skipping."""
    raw = mock_tweet_factory(
        tweet_id="18937100291",
        created_at_str="Tue Nov 19 09:31:00 +0000 2026",
        author="retrocomputing",
        media_type="photo"
    )
    
    tweet_obj = _unwrap_tweet_result(raw.get("result"))
    item = _tweet_obj_to_bookmark_item(tweet_obj, include_gifs=True, include_quoted_videos=True)
    
    assert item is not None
    assert item.media_type == MediaType.IMAGE
    assert item.has_video is False


def test_at03_5_animated_gif_toggle(mock_tweet_factory):
    """AT-03.5: Animated GIF toggle option."""
    raw_gif = mock_tweet_factory(
        tweet_id="18930000001",
        created_at_str="Tue Nov 19 08:00:00 +0000 2026",
        media_type="animated_gif"
    )
    tweet_obj = _unwrap_tweet_result(raw_gif.get("result"))
    
    # When include_gifs=True
    item1 = _tweet_obj_to_bookmark_item(tweet_obj, include_gifs=True, include_quoted_videos=True)
    assert item1.has_video is True
    assert item1.media_type == MediaType.GIF
    
    # When include_gifs=False
    item2 = _tweet_obj_to_bookmark_item(tweet_obj, include_gifs=False, include_quoted_videos=True)
    assert item2.has_video is False


def test_at03_6_quoted_post_video_toggle(mock_tweet_factory):
    """AT-03.6: Quoted post containing video toggle."""
    raw_quote = mock_tweet_factory(
        tweet_id="18930000002",
        created_at_str="Mon Nov 18 10:00:00 +0000 2026",
        media_type="none",
        is_quote=True,
        quote_has_video=True
    )
    tweet_obj = _unwrap_tweet_result(raw_quote.get("result"))
    
    # When include_quoted_videos=True
    item1 = _tweet_obj_to_bookmark_item(tweet_obj, include_gifs=True, include_quoted_videos=True)
    assert item1.has_video is True
    assert item1.media_type == MediaType.QUOTED_VIDEO
    assert item1.is_quoted_video is True
    assert "quote" in item1.download_url
    
    # When include_quoted_videos=False
    item2 = _tweet_obj_to_bookmark_item(tweet_obj, include_gifs=True, include_quoted_videos=False)
    assert item2.has_video is False


def test_at03_9_tombstone_ignored():
    """AT-03.9: Tombstones or deleted bookmarks are handled gracefully."""
    tombstone_payload = {
        "result": {
            "__typename": "TweetTombstone",
            "tombstone": {
                "text": {"text": "This post was deleted by the author."}
            }
        }
    }
    tweet_obj = _unwrap_tweet_result(tombstone_payload.get("result"))
    assert tweet_obj is None  # Safely unwraps to None without exception
