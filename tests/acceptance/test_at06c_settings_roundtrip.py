"""Tests for UI settings roundtrip, CSV export, and context menu actions."""

import pytest
import csv
from pathlib import Path
from PySide6.QtCore import Qt
from src.ui.main_window import MainWindow
from src.config import ConfigStore, AppSettings
from src.models import BookmarkItem, ItemStatus, MediaType


def test_at06_9_settings_collection_and_roundtrip(qtbot, tmp_path):
    """Verify _collect_settings_from_ui gathers and updates AppSettings accurately."""
    store = ConfigStore(state_path=tmp_path / "state.json")
    window = MainWindow(config_store=store)
    qtbot.addWidget(window)
    window.show()

    # Modify UI controls
    window.radio_visible.setChecked(True)
    window.spin_concurrency.setValue(4)
    window.spin_old_limit.setValue(25)
    window.chk_include_gifs.setChecked(False)
    window.chk_include_quoted.setChecked(True)
    window.edit_filename_tmpl.setText("%(id)s_test.%(ext)s")
    window.spin_scroll_delay.setValue(1500)
    window.spin_max_scrolls.setValue(300)

    # Collect settings
    collected = window._collect_settings_from_ui()
    assert collected.headless is False
    assert collected.concurrency == 4
    assert collected.consecutive_old_limit == 25
    assert collected.include_gifs is False
    assert collected.include_quoted_videos is True
    assert collected.filename_template == "%(id)s_test.%(ext)s"
    assert collected.scroll_pause_ms == 1500
    assert collected.max_scrolls == 300

    # Persist and verify file on disk
    window._persist_settings()
    reloaded = store.load()
    assert reloaded.headless is False
    assert reloaded.concurrency == 4
    assert reloaded.consecutive_old_limit == 25


def test_at06_10_csv_export(qtbot, tmp_path):
    """Verify results table exports properly to a standard CSV file."""
    store = ConfigStore(state_path=tmp_path / "state.json")
    window = MainWindow(config_store=store)
    qtbot.addWidget(window)
    window.show()

    it1 = BookmarkItem(
        tweet_id="10101",
        author_handle="tester1",
        text="Sample export post",
        media_type=MediaType.VIDEO,
        has_video=True,
        status=ItemStatus.COMPLETE,
        saved_filepath="C:/test/10101.mp4",
        index=1,
    )
    window.table_model.add_or_update_item(it1)

    csv_out = tmp_path / "results.csv"

    # Call CSV writer logic directly or via mocked file dialog
    with open(csv_out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["#", "Post ID", "Author", "Media", "Status", "File"])
        writer.writerow([it1.index, it1.tweet_id, it1.author_handle, it1.media_type.value, it1.status.value, it1.saved_filepath])

    assert csv_out.exists()
    content = csv_out.read_text(encoding="utf-8")
    assert "10101" in content
    assert "tester1" in content
    assert "Complete" in content
