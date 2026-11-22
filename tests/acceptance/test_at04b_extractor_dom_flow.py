"""Additional integration and edge case tests for BookmarkExtractor and Playwright interactions."""

import pytest
from unittest.mock import MagicMock, patch
from src.extractor import BookmarkExtractor, _is_login_url, AuthenticationError
from src.models import RunConfig, ItemStatus, MediaType


def test_at04_5_is_login_url():
    """Verify login redirect URL pattern matching."""
    assert _is_login_url("https://x.com/i/flow/login") is True
    assert _is_login_url("https://twitter.com/login") is True
    assert _is_login_url("https://x.com/i/bookmarks") is False


def test_at04_6_dom_tweet_extraction_fallback():
    """Verify fallback DOM tweet parser inside BookmarkExtractor."""
    extractor = BookmarkExtractor(
        config=RunConfig(profile_path="", output_dir="", include_quoted_videos=True),
        cookies=[],
    )

    mock_page = MagicMock()
    # Return simulated DOM evaluation rows
    mock_page.evaluate.return_value = [
        {
            "statusHref": "/gamer/status/91001",
            "createdAt": "2026-11-20T10:00:00Z",
            "text": "Check out this gaming clip",
            "hasPrimaryVideo": True,
            "hasQuotedVideo": False,
            "hasPhoto": False,
        },
        {
            "statusHref": "/writer/status/91002",
            "createdAt": "2026-11-20T09:00:00Z",
            "text": "Quoted post has video",
            "hasPrimaryVideo": False,
            "hasQuotedVideo": True,
            "hasPhoto": False,
        },
        {
            "statusHref": "/photog/status/91003",
            "createdAt": "2026-11-20T08:00:00Z",
            "text": "Nice sunset",
            "hasPrimaryVideo": False,
            "hasQuotedVideo": False,
            "hasPhoto": True,
        },
    ]

    items = extractor._extract_dom_tweets(mock_page)
    assert len(items) == 3
    assert items[0].tweet_id == "91001"
    assert items[0].has_video is True
    assert items[0].media_type == MediaType.VIDEO

    assert items[1].tweet_id == "91002"
    assert items[1].has_video is True
    assert items[1].media_type == MediaType.QUOTED_VIDEO

    assert items[2].tweet_id == "91003"
    assert items[2].has_video is False
    assert items[2].media_type == MediaType.IMAGE


def test_at04_7_mock_playwright_run_flow():
    """Verify full BookmarkExtractor.run loop with mocked Playwright browser/page objects."""
    extractor = BookmarkExtractor(
        config=RunConfig(profile_path="", output_dir="", max_scrolls=2, scroll_pause_ms=50),
        cookies=[{"name": "auth_token", "value": "valid_token", "domain": ".x.com"}],
    )

    mock_p = MagicMock()
    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()

    mock_p.firefox.launch.return_value = mock_browser
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page
    mock_page.url = "https://x.com/i/bookmarks"
    mock_page.evaluate.side_effect = [
        1000,  # prev_height
        None,  # scrollBy
        1000,  # new_height
        1000,  # prev_height
        None,  # scrollBy
        1000,  # new_height
    ]
    mock_context.cookies.return_value = [
        {"name": "auth_token", "value": "refreshed_token", "domain": ".x.com"}
    ]

    # Preload a mock DOM tweet
    extractor._extract_dom_tweets = MagicMock(return_value=[])

    with patch("src.extractor.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.__enter__.return_value = mock_p
        stats, refreshed_cookies = extractor.run()

    assert stats is not None
    assert any(c["name"] == "auth_token" for c in refreshed_cookies)
