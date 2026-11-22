"""Firefox profile discovery and lock-safe X cookie extraction."""

from __future__ import annotations

import configparser
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from src.models import FirefoxProfile


def _safe_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _safe_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def get_firefox_root_dir() -> Path:
    """Return the platform-specific Mozilla Firefox user data directory."""
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Mozilla" / "Firefox"
        return Path.home() / "AppData" / "Roaming" / "Mozilla" / "Firefox"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Firefox"
    return Path.home() / ".mozilla" / "firefox"


def _is_x_domain(host: str) -> bool:
    """Return True only for x.com / twitter.com and their subdomains."""
    normalized = host.strip().lstrip(".").lower()
    return (
        normalized == "x.com"
        or normalized.endswith(".x.com")
        or normalized == "twitter.com"
        or normalized.endswith(".twitter.com")
    )


def _normalize_same_site(raw_value: Any, secure: bool) -> str:
    """Map Firefox moz_cookies sameSite integer to Playwright string."""
    mapping = {0: "None", 1: "Lax", 2: "Strict"}
    try:
        code = int(raw_value)
    except (TypeError, ValueError):
        code = 1
    same_site = mapping.get(code, "Lax")
    if same_site == "None" and not secure:
        return "Lax"
    return same_site


def _normalize_expiry(raw_expiry: Any) -> Optional[int]:
    """Normalize SQLite cookie expiry into integer Unix seconds, or None for session."""
    if raw_expiry is None:
        return None
    try:
        val = int(raw_expiry)
    except (TypeError, ValueError):
        return None
    if val <= 0:
        return None
    # Modern Firefox stores some expiries in milliseconds or microseconds.
    if val > 10**14:
        val //= 1_000_000
    elif val > 10**12:
        val //= 1_000
    return val


def extract_x_cookies(profile_path: Path) -> list[dict[str, Any]]:
    """Copy cookies.sqlite to a temp dir and extract unexpired X/Twitter cookies."""
    profile_dir = Path(profile_path)
    cookies_db = profile_dir / "cookies.sqlite"
    if not _safe_is_file(cookies_db):
        return []

    now_sec = int(time.time())
    extracted: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="xff_cookies_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        tmp_db = tmp_path / "cookies.sqlite"
        shutil.copy2(cookies_db, tmp_db)

        for suffix in ("-wal", "-shm"):
            sidecar = profile_dir / f"cookies.sqlite{suffix}"
            if _safe_is_file(sidecar):
                try:
                    shutil.copy2(sidecar, tmp_path / f"cookies.sqlite{suffix}")
                except OSError:
                    pass

        conn = sqlite3.connect(str(tmp_db))
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(moz_cookies)")
            columns = {row[1] for row in cursor.fetchall()}
            if not columns:
                return []

            has_http_only = "isHttpOnly" in columns
            has_same_site = "sameSite" in columns

            select_cols = [
                "name",
                "value",
                "host",
                "path",
                "expiry",
                "isSecure",
                "isHttpOnly" if has_http_only else "0 AS isHttpOnly",
                "sameSite" if has_same_site else "1 AS sameSite",
            ]
            query = (
                f"SELECT {', '.join(select_cols)} FROM moz_cookies "
                "WHERE host LIKE '%x.com' OR host LIKE '%twitter.com'"
            )
            cursor.execute(query)
            for row in cursor.fetchall():
                name, value, host, path, raw_expiry, raw_secure, raw_http, raw_ss = row
                if not name or not host or not _is_x_domain(str(host)):
                    continue
                expires = _normalize_expiry(raw_expiry)
                if expires is not None and expires <= now_sec:
                    continue

                secure = bool(raw_secure)
                extracted.append(
                    {
                        "name": str(name),
                        "value": str(value or ""),
                        "domain": str(host),
                        "path": str(path or "/"),
                        "expires": expires,
                        "httpOnly": bool(raw_http),
                        "secure": secure,
                        "sameSite": _normalize_same_site(raw_ss, secure),
                    }
                )
        finally:
            conn.close()

    return extracted


def to_playwright_cookies(cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert extracted cookie dictionaries into Playwright add_cookies format."""
    pw_cookies: list[dict[str, Any]] = []
    for cookie in cookies:
        secure = bool(cookie.get("secure", False))
        same_site = str(cookie.get("sameSite") or "Lax")
        if same_site not in ("Strict", "Lax", "None"):
            same_site = "Lax"
        if same_site == "None" and not secure:
            same_site = "Lax"

        entry: dict[str, Any] = {
            "name": str(cookie["name"]),
            "value": str(cookie.get("value", "")),
            "domain": str(cookie["domain"]),
            "path": str(cookie.get("path") or "/"),
            "httpOnly": bool(cookie.get("httpOnly", False)),
            "secure": secure,
            "sameSite": same_site,
        }
        expires = cookie.get("expires")
        if expires is not None:
            try:
                exp_int = int(expires)
                if exp_int > 0:
                    entry["expires"] = exp_int
            except (TypeError, ValueError):
                pass
        pw_cookies.append(entry)
    return pw_cookies


def inspect_x_cookies(profile_path: Path) -> tuple[bool, str]:
    """Check whether a Firefox profile has active X session cookies (auth_token & ct0)."""
    profile_dir = Path(profile_path)
    if not _safe_is_file(profile_dir / "cookies.sqlite"):
        return False, "No cookies.sqlite database found"

    try:
        cookies = extract_x_cookies(profile_dir)
    except (sqlite3.Error, OSError) as exc:
        return False, f"Cookie read error: {exc}"

    if not cookies:
        return False, "No active X/Twitter cookies"

    names = {c["name"] for c in cookies if c.get("value")}
    has_auth_token = "auth_token" in names
    has_ct0 = "ct0" in names

    if has_auth_token and has_ct0:
        return True, f"Auth OK ({len(cookies)} X cookies)"
    if has_auth_token:
        return False, "Incomplete auth (missing ct0 CSRF cookie)"
    return False, f"Not logged into X ({len(cookies)} cookies, no auth_token)"


def export_netscape_cookies(cookies: list[dict[str, Any]], dest_path: Path) -> Path:
    """Export cookies in Netscape cookies.txt format for yt-dlp."""
    target = Path(dest_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Netscape HTTP Cookie File",
        "# Generated by XitterAutoDownloaderTool",
        "",
    ]
    for cookie in cookies:
        domain = str(cookie.get("domain") or "").strip()
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "")
        if not domain or not name:
            continue
        if any(ch in value for ch in ("\n", "\r", "\t")):
            continue

        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path = str(cookie.get("path") or "/")
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        expires_val = cookie.get("expires")
        try:
            expires_str = str(int(expires_val)) if expires_val and int(expires_val) > 0 else "0"
        except (TypeError, ValueError):
            expires_str = "0"

        lines.append(
            f"{domain}\t{include_subdomains}\t{path}\t{secure}\t{expires_str}\t{name}\t{value}"
        )

    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def discover_firefox_profiles(
    firefox_root: Optional[Path] = None,
) -> list[FirefoxProfile]:
    """Discover local Firefox profiles from profiles.ini and inspect their X cookies."""
    root = Path(firefox_root) if firefox_root else get_firefox_root_dir()
    if not _safe_exists(root):
        return []

    profiles: list[FirefoxProfile] = []
    seen_paths: set[str] = set()
    profiles_ini = root / "profiles.ini"

    install_defaults: set[str] = set()
    if _safe_is_file(profiles_ini):
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(profiles_ini, encoding="utf-8")
        except (configparser.Error, OSError):
            parser = configparser.ConfigParser(interpolation=None)

        for section_name in parser.sections():
            if section_name.startswith("Install"):
                default_val = parser[section_name].get("default", "").strip()
                if default_val:
                    install_defaults.add(os.path.normpath(str(root / default_val)).lower())
                    install_defaults.add(os.path.normpath(default_val).lower())

        for section_name in parser.sections():
            if not section_name.startswith("Profile"):
                continue
            section = parser[section_name]
            raw_path = section.get("path", "").strip()
            if not raw_path:
                continue
            is_relative = section.get("isrelative", "1").strip() == "1"
            resolved = (root / raw_path) if is_relative else Path(raw_path)
            norm_key = os.path.normpath(str(resolved)).lower()
            if norm_key in seen_paths or not _safe_is_dir(resolved):
                continue
            seen_paths.add(norm_key)

            is_default = (
                section.get("default", "0").strip() == "1"
                or norm_key in install_defaults
            )
            has_db = _safe_is_file(resolved / "cookies.sqlite")
            has_auth, summary = inspect_x_cookies(resolved) if has_db else (False, "No cookies.sqlite")

            profiles.append(
                FirefoxProfile(
                    name=section.get("name", resolved.name).strip() or resolved.name,
                    path=str(resolved),
                    is_default=is_default,
                    is_relative=is_relative,
                    has_cookies_db=has_db,
                    has_x_auth=has_auth,
                    cookie_summary=summary,
                )
            )

    # Fallback scan if profiles.ini didn't list profiles directly.
    if not profiles:
        candidate_roots = [root / "Profiles", root]
        for base in candidate_roots:
            if not _safe_is_dir(base):
                continue
            try:
                entries = list(base.iterdir())
            except OSError:
                continue
            for entry in entries:
                if not _safe_is_dir(entry):
                    continue
                norm_key = os.path.normpath(str(entry)).lower()
                if norm_key in seen_paths:
                    continue
                if _safe_is_file(entry / "cookies.sqlite"):
                    seen_paths.add(norm_key)
                    has_auth, summary = inspect_x_cookies(entry)
                    profiles.append(
                        FirefoxProfile(
                            name=entry.name,
                            path=str(entry),
                            is_default=False,
                            is_relative=True,
                            has_cookies_db=True,
                            has_x_auth=has_auth,
                            cookie_summary=summary,
                        )
                    )

    profiles.sort(
        key=lambda p: (
            not (p.is_default and p.has_x_auth),
            not p.has_x_auth,
            not p.is_default,
            not p.has_cookies_db,
            p.name.lower(),
        )
    )
    return profiles
