"""Additional tests for Firefox profile fallback discovery and cookies.sqlite error handling."""

import os
import pytest
from pathlib import Path
from src.firefox_profile import discover_firefox_profiles, get_firefox_root_dir, _is_x_domain, _normalize_same_site
from src.models import FirefoxProfile


def test_at01_6_is_x_domain_and_same_site():
    """Verify domain check and sameSite integer to string mappings."""
    assert _is_x_domain("x.com") is True
    assert _is_x_domain(".x.com") is True
    assert _is_x_domain("api.x.com") is True
    assert _is_x_domain("twitter.com") is True
    assert _is_x_domain("google.com") is False
    assert _is_x_domain("notx.com") is False

    assert _normalize_same_site(0, secure=True) == "None"
    assert _normalize_same_site(0, secure=False) == "Lax"  # None requires secure
    assert _normalize_same_site(1, secure=True) == "Lax"
    assert _normalize_same_site(2, secure=True) == "Strict"


def test_at01_7_fallback_directory_scan_without_profiles_ini(tmp_path):
    """Verify fallback directory scan when profiles.ini is absent."""
    root = tmp_path / "firefox_root"
    root.mkdir()
    
    # Create Profiles subfolder with a profile that has cookies.sqlite
    prof_folder = root / "Profiles" / "fallback.default"
    prof_folder.mkdir(parents=True)
    (prof_folder / "cookies.sqlite").write_text("", encoding="utf-8")

    profiles = discover_firefox_profiles(firefox_root=root)
    assert len(profiles) >= 1
    assert profiles[0].name == "fallback.default"
    assert profiles[0].has_cookies_db is True
