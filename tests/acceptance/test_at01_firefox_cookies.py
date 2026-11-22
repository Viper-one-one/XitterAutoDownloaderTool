"""AT-01: Firefox Profile Discovery & Lock-Safe Cookie Extraction Acceptance Tests."""

import sqlite3
import pytest
from pathlib import Path

from src.firefox_profile import (
    discover_firefox_profiles,
    extract_x_cookies,
    inspect_x_cookies,
    export_netscape_cookies,
    to_playwright_cookies,
)
from src.models import FirefoxProfile


def test_at01_1_auto_discover_profiles(temp_firefox_profile_dir):
    """AT-01.1: Auto-discover profiles from profiles.ini and identify default-release."""
    profiles = discover_firefox_profiles(firefox_root=temp_firefox_profile_dir["appdata_root"])
    
    assert len(profiles) >= 1
    # Profile default-release should be flagged as default
    default_p = next((p for p in profiles if p.is_default), None)
    assert default_p is not None
    assert default_p.name == "default-release"
    assert "test-profile.default-release" in default_p.path.replace("\\", "/")


def test_at01_2_custom_profile_directory_inspection(tmp_path):
    """AT-01.2: Custom profile directory validation with and without cookies.sqlite."""
    # 1. Invalid directory (no cookies.sqlite)
    empty_dir = tmp_path / "custom_empty"
    empty_dir.mkdir()
    ok, msg = inspect_x_cookies(empty_dir)
    assert not ok
    assert "cookies.sqlite" in msg.lower()
    
    # 2. Valid directory with cookies.sqlite (empty table)
    valid_dir = tmp_path / "custom_valid"
    valid_dir.mkdir()
    db_file = valid_dir / "cookies.sqlite"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE moz_cookies (name TEXT, value TEXT, host TEXT, path TEXT, expiry INTEGER, isSecure INTEGER, isHttpOnly INTEGER, sameSite INTEGER);"
    )
    conn.commit()
    conn.close()
    
    ok, msg = inspect_x_cookies(valid_dir)
    assert not ok  # No cookies yet, but detected database
    assert "no active x/twitter cookies" in msg.lower() or "not logged" in msg.lower()


def test_at01_3_lock_safe_sqlite_extraction(temp_firefox_profile_dir):
    """AT-01.3: Lock-safe extraction while Firefox holds an exclusive SQLite lock."""
    db_path = temp_firefox_profile_dir["cookies_db"]
    
    # Populate with valid auth_token & ct0
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        INSERT INTO moz_cookies (name, value, host, path, expiry, isSecure, isHttpOnly)
        VALUES ('auth_token', 'secret1234567890abcdef', '.x.com', '/', 1893456000, 1, 1),
               ('ct0', 'csrf_token_xyz', '.x.com', '/', 1893456000, 1, 0)
    """)
    conn.commit()
    
    # Acquire exclusive write transaction lock simulating running Firefox
    lock_conn = sqlite3.connect(str(db_path), timeout=0.1)
    lock_conn.execute("BEGIN EXCLUSIVE TRANSACTION")
    
    try:
        # Should succeed by copying to a temp working directory before reading
        cookies = extract_x_cookies(temp_firefox_profile_dir["profile_dir"])
        names = {c["name"]: c["value"] for c in cookies}
        assert "auth_token" in names
        assert names["auth_token"] == "secret1234567890abcdef"
        assert "ct0" in names
    finally:
        lock_conn.rollback()
        lock_conn.close()
        conn.close()


def test_at01_4_cookie_authentication_states(temp_firefox_profile_dir):
    """AT-01.4: Validation across valid, legacy twitter.com, expired, and missing cookie states."""
    profile_dir = temp_firefox_profile_dir["profile_dir"]
    db_path = temp_firefox_profile_dir["cookies_db"]
    
    # State D: Missing auth_token
    ok, msg = inspect_x_cookies(profile_dir)
    assert not ok
    assert "no active" in msg.lower() or "not logged" in msg.lower()
    
    # State C: Expired auth_token
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        INSERT INTO moz_cookies (name, value, host, path, expiry, isSecure, isHttpOnly)
        VALUES ('auth_token', 'expired_token', '.x.com', '/', 1000000000, 1, 1),
               ('ct0', 'csrf_token', '.x.com', '/', 1000000000, 1, 0)
    """)
    conn.commit()
    conn.close()
    
    ok, msg = inspect_x_cookies(profile_dir)
    assert not ok
    assert "no active" in msg.lower() or "not logged" in msg.lower()
    
    # State B: Legacy .twitter.com cookies
    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM moz_cookies")
    conn.execute("""
        INSERT INTO moz_cookies (name, value, host, path, expiry, isSecure, isHttpOnly)
        VALUES ('auth_token', 'legacy_token', '.twitter.com', '/', 2000000000, 1, 1),
               ('ct0', 'csrf_token', '.twitter.com', '/', 2000000000, 1, 0)
    """)
    conn.commit()
    conn.close()
    
    ok, msg = inspect_x_cookies(profile_dir)
    assert ok
    assert "auth ok" in msg.lower()
    
    # State A: Valid .x.com cookies
    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM moz_cookies")
    conn.execute("""
        INSERT INTO moz_cookies (name, value, host, path, expiry, isSecure, isHttpOnly)
        VALUES ('auth_token', 'valid_x_token', '.x.com', '/', 2000000000, 1, 1),
               ('ct0', 'csrf_token', '.x.com', '/', 2000000000, 1, 0)
    """)
    conn.commit()
    conn.close()
    
    ok, msg = inspect_x_cookies(profile_dir)
    assert ok
    assert "auth ok" in msg.lower()


def test_at01_5_dual_cookie_export(temp_firefox_profile_dir, tmp_path):
    """AT-01.5: Dual cookie export for Playwright and Netscape cookies.txt for yt-dlp."""
    db_path = temp_firefox_profile_dir["cookies_db"]
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        INSERT INTO moz_cookies (name, value, host, path, expiry, isSecure, isHttpOnly)
        VALUES ('auth_token', 'export_token_123', '.x.com', '/', 2000000000, 1, 1),
               ('ct0', 'export_ct0_456', '.x.com', '/', 2000000000, 1, 0)
    """)
    conn.commit()
    conn.close()
    
    cookies = extract_x_cookies(temp_firefox_profile_dir["profile_dir"])
    
    # 1. Playwright cookies
    pw_cookies = to_playwright_cookies(cookies)
    assert len(pw_cookies) >= 2
    auth_pw = next(c for c in pw_cookies if c["name"] == "auth_token")
    assert auth_pw["value"] == "export_token_123"
    assert auth_pw["domain"] in [".x.com", "x.com"]
    assert auth_pw["httpOnly"] is True
    
    # 2. Netscape format file for yt-dlp
    netscape_file = tmp_path / "cookies.txt"
    export_netscape_cookies(cookies, netscape_file)
    
    assert netscape_file.exists()
    content = netscape_file.read_text(encoding="utf-8")
    assert "# Netscape HTTP Cookie File" in content
    assert "export_token_123" in content
    assert "export_ct0_456" in content
