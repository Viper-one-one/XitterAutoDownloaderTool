"""Additional UI widget, actions, and theme unit & integration tests."""

import pytest
from pathlib import Path
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow
from src.ui.theme import create_app_icon
from src.ui.table_model import BookmarkTableModel, BookmarkFilterProxyModel, ProgressBarDelegate
from src.config import ConfigStore, AppSettings
from src.models import BookmarkItem, ItemStatus, MediaType, FirefoxProfile, RunStats


def test_at06_5_app_icon_generation():
    """Verify classic glossy blue desktop application icon generates valid sizes."""
    icon = create_app_icon()
    assert isinstance(icon, QIcon)
    assert not icon.isNull()
    # Check pixmaps
    p16 = icon.pixmap(16, 16)
    assert p16.width() == 16
    p32 = icon.pixmap(32, 32)
    assert p32.width() == 32


def test_at06_6_table_model_sorting_and_formatting():
    """Verify table model display values, sorting keys, tooltips, and background/foreground roles."""
    model = BookmarkTableModel()
    
    it1 = BookmarkItem(
        tweet_id="1001",
        author_handle="zelda",
        author_name="Princess Zelda",
        text="A line of text\nwith a newline",
        media_type=MediaType.VIDEO,
        has_video=True,
        status=ItemStatus.COMPLETE,
        saved_filepath="C:/Videos/1001.mp4",
        index=1,
    )
    it2 = BookmarkItem(
        tweet_id="1002",
        author_handle="link",
        author_name="Hero Link",
        text="Shield clip",
        media_type=MediaType.VIDEO,
        has_video=True,
        status=ItemStatus.FAILED,
        error_message="HTTP Error 404",
        index=2,
    )
    model.add_or_update_item(it1)
    model.add_or_update_item(it2)

    # Display roles
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "1"
    assert model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole) == "1001"
    assert model.data(model.index(0, 2), Qt.ItemDataRole.DisplayRole) == "@zelda"
    assert model.data(model.index(0, 7), Qt.ItemDataRole.DisplayRole) == ItemStatus.COMPLETE.value
    assert "1001.mp4" in model.data(model.index(0, 8), Qt.ItemDataRole.DisplayRole)
    assert "HTTP Error 404" in model.data(model.index(1, 8), Qt.ItemDataRole.DisplayRole)

    # Tooltip role
    tip = model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole)
    assert "Princess Zelda" in tip
    assert "Saved:" in tip

    # Foreground color role
    color_complete = model.data(model.index(0, 7), Qt.ItemDataRole.ForegroundRole)
    assert color_complete is not None
    color_failed = model.data(model.index(1, 7), Qt.ItemDataRole.ForegroundRole)
    assert color_failed is not None

    # Sort values
    assert model._sort_value(it1, 0) == 1
    assert model._sort_value(it1, 1) == 1001
    assert model._sort_value(it1, 2) == "zelda"


def test_at06_7_mainwindow_menu_actions_and_dialogs(qtbot, tmp_path):
    """Verify MainWindow toolbar and menu actions: clear finished, clear log, toggle bottom pane."""
    store = ConfigStore(state_path=tmp_path / "state.json")
    window = MainWindow(config_store=store)
    qtbot.addWidget(window)
    window.show()

    # Add finished and active items
    it_done = BookmarkItem(tweet_id="1", author_handle="a", status=ItemStatus.COMPLETE, has_video=True)
    it_active = BookmarkItem(tweet_id="2", author_handle="b", status=ItemStatus.DOWNLOADING, has_video=True)
    window.table_model.add_or_update_item(it_done)
    window.table_model.add_or_update_item(it_active)
    assert window.table_model.rowCount() == 2

    # Clear finished rows
    window._clear_finished_rows()
    assert window.table_model.rowCount() == 1
    assert window.table_model.get_item(0).tweet_id == "2"

    # Append and clear log
    window._append_log("INFO", "Test message 1")
    assert "Test message 1" in window.log_console.toPlainText()
    window._clear_log()
    assert window.log_console.toPlainText() == ""

    # Toggle bottom pane
    assert window.bottom_tabs.isVisible() is True
    window.act_toggle_bottom.setChecked(False)
    assert window.bottom_tabs.isVisible() is False
    window.act_toggle_bottom.setChecked(True)
    assert window.bottom_tabs.isVisible() is True

    # Date controls sync
    window.chk_date_filter.setChecked(True)
    window.chk_to_now.setChecked(True)
    assert window.dt_to.isEnabled() is False
    window.chk_to_now.setChecked(False)
    assert window.dt_to.isEnabled() is True


def test_at06_8_mainwindow_profile_selection_and_status(qtbot, tmp_path):
    """Verify profile combo updates and status bar authentication cell reflection."""
    store = ConfigStore(state_path=tmp_path / "state.json")
    window = MainWindow(config_store=store)
    qtbot.addWidget(window)
    window.show()

    prof_valid = FirefoxProfile(
        name="profile_a",
        path=str(tmp_path / "prof_a"),
        has_cookies_db=True,
        has_x_auth=True,
        cookie_summary="Auth OK",
    )
    prof_invalid = FirefoxProfile(
        name="profile_b",
        path=str(tmp_path / "prof_b"),
        has_cookies_db=True,
        has_x_auth=False,
        cookie_summary="No X Auth",
    )

    window._profiles = [prof_valid, prof_invalid]
    window.combo_profile.clear()
    window._add_profile_combo_item(prof_valid)
    window._add_profile_combo_item(prof_invalid)

    # Select valid
    window.combo_profile.setCurrentIndex(0)
    window._on_profile_changed()
    assert "profile_a" in window.lbl_sb_auth.text()
    assert "Auth OK" in window.lbl_sb_auth.text()

    # Select invalid
    window.combo_profile.setCurrentIndex(1)
    window._on_profile_changed()
    assert "profile_b" in window.lbl_sb_auth.text()
    assert "No X Auth" in window.lbl_sb_auth.text()
