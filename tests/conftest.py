import pytest
import sqlite3
import os
import json
from datetime import datetime, timezone

@pytest.fixture
def temp_firefox_profile_dir(tmp_path):
    """Creates a temporary Firefox profile directory with a mock cookies.sqlite."""
    profile_dir = tmp_path / "Profiles" / "test-profile.default-release"
    profile_dir.mkdir(parents=True)
    
    cookies_db = profile_dir / "cookies.sqlite"
    conn = sqlite3.connect(str(cookies_db))
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE moz_cookies (
            id INTEGER PRIMARY KEY,
            originAttributes TEXT NOT NULL DEFAULT '',
            name TEXT,
            value TEXT,
            host TEXT,
            path TEXT,
            expiry INTEGER,
            lastAccessed INTEGER,
            creationTime INTEGER,
            isSecure INTEGER,
            isHttpOnly INTEGER,
            inBrowserElement INTEGER DEFAULT 0,
            sameSite INTEGER DEFAULT 0,
            rawSameSite INTEGER DEFAULT 0,
            schemeMap INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()
    
    profiles_ini = tmp_path / "profiles.ini"
    profiles_ini.write_text(f"""[General]
StartWithLastProfile=1
Version=2

[Profile0]
Name=default-release
IsRelative=1
Path=Profiles/test-profile.default-release
Default=1

[Profile1]
Name=secondary-profile
IsRelative=1
Path=Profiles/secondary.default
Default=0
""", encoding="utf-8")
    
    return {
        "appdata_root": tmp_path,
        "profiles_ini": profiles_ini,
        "profile_dir": profile_dir,
        "cookies_db": cookies_db
    }

@pytest.fixture
def mock_tweet_factory():
    """Generates synthetic GraphQL TweetResult payloads for acceptance testing."""
    def _create_tweet(
        tweet_id: str,
        created_at_str: str,
        author: str = "testuser",
        media_type: str = "video",
        variants = None,
        is_quote: bool = False,
        quote_has_video: bool = False
    ):
        # Format: 'Wed Oct 10 20:19:24 +0000 2026'
        media_list = []
        if media_type == "video":
            media_list.append({
                "type": "video",
                "media_url_https": "https://pbs.twimg.com/media/thumb.jpg",
                "original_info": {
                    "width": 1920,
                    "height": 1080
                },
                "video_info": {
                    "duration_millis": 45000,
                    "variants": variants or [
                        {"bitrate": 832000, "content_type": "video/mp4", "url": f"https://video.twimg.com/test_{tweet_id}_720x1280.mp4"},
                        {"bitrate": 2176000, "content_type": "video/mp4", "url": f"https://video.twimg.com/test_{tweet_id}_1080x1920.mp4"}
                    ]
                }
            })
        elif media_type == "animated_gif":
            media_list.append({
                "type": "animated_gif",
                "media_url_https": "https://pbs.twimg.com/media/gif_thumb.jpg",
                "video_info": {
                    "variants": [{"bitrate": 0, "content_type": "video/mp4", "url": f"https://video.twimg.com/test_gif_{tweet_id}.mp4"}]
                }
            })
        elif media_type == "photo":
            media_list.append({
                "type": "photo",
                "media_url_https": "https://pbs.twimg.com/media/photo1.jpg"
            })
        
        quoted_result = None
        if is_quote:
            quote_media = []
            if quote_has_video:
                quote_media.append({
                    "type": "video",
                    "video_info": {
                        "duration_millis": 30000,
                        "variants": [{"bitrate": 832000, "content_type": "video/mp4", "url": "https://video.twimg.com/quote.mp4"}]
                    }
                })
            quoted_result = {
                "result": {
                    "__typename": "Tweet",
                    "rest_id": f"quote_{tweet_id}",
                    "legacy": {
                        "created_at": created_at_str,
                        "full_text": "Quoted tweet text",
                        "extended_entities": {"media": quote_media}
                    }
                }
            }

        payload = {
            "result": {
                "__typename": "Tweet",
                "rest_id": str(tweet_id),
                "core": {
                    "user_results": {
                        "result": {
                            "legacy": {
                                "screen_name": author,
                                "name": f"{author} Name"
                            }
                        }
                    }
                },
                "legacy": {
                    "created_at": created_at_str,
                    "full_text": f"Tweet text for {tweet_id}",
                    "extended_entities": {
                        "media": media_list
                    }
                }
            }
        }
        if quoted_result:
            payload["result"]["quoted_status_result"] = quoted_result
        return payload

    return _create_tweet
