"""AT-06: Classic Early-2010s High-Density UI & MainWindow End-to-End Acceptance Tests."""

import os
import pytest
from datetime import datetime, timezone
from pathlib import Path
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication, QHeaderView, QStyle

from src.ui.main_window import MainWindow
from src.ui.theme import get_classic_stylesheet
from src.config import ConfigStore, AppSettings
from src.models import BookmarkItem, MediaType, ItemStatus, AnchorRecord, RunStats


def test_at06_1_mainwindow_density_geometry_and_theme(qtbot, tmp_path):
    """AT-06.1: Assert MainWindow initializes with exact early-2010s density constraints."""
    store = ConfigStore(state_path=tmp_path / "state.json")
    window = MainWindow(config_store=store)
    qtbot.addWidget(window)
    window.show()

    # 1. Row height density: defaultSectionSize must be compact (<= 24px)
    v_header = window.table_view.verticalHeader()
    assert v_header.defaultSectionSize() <= 24

    # 2. Grid & Alternate colors enabled
    assert window.table_view.showGrid() is True
    assert window.table_view.alternatingRowColors() is True

    # 3. Typography & QSS stylesheet
    qss = get_classic_stylesheet()
    assert "Segoe UI" in qss or "Tahoma" in qss
    assert "8.5pt" in qss
    assert "qlineargradient" in qss

    # 4. Top toolbar action buttons exist
    assert window.btn_start is not None
    assert window.btn_scan_only is not None
    assert window.btn_pause is not None
    assert window.btn_stop is not None
    assert window.btn_reset_anchor is not None
    assert window.chk_hide_skipped is not None

    # 5. Config panels
    assert window.combo_profile is not None
    assert window.combo_output_dir is not None
    assert window.spin_concurrency.value() >= 1
    assert window.spin_old_limit.value() >= 1


def test_at06_2_mainwindow_table_filtering_and_search(qtbot, tmp_path):
    """AT-06.2: Test Hide Skipped and text search filtering directly in MainWindow."""
    store = ConfigStore(state_path=tmp_path / "state.json")
    window = MainWindow(config_store=store)
    qtbot.addWidget(window)
    window.show()

    # Populate 3 items: 1 Video, 1 Skipped (No Video), 1 Skipped (Date Range)
    item1 = BookmarkItem(
        tweet_id="101",
        author_handle="alice",
        text="Cool tech demo video",
        media_type=MediaType.VIDEO,
        has_video=True,
        status=ItemStatus.COMPLETE,
        index=1,
    )
    item2 = BookmarkItem(
        tweet_id="102",
        author_handle="bob",
        text="Text-only announcement",
        media_type=MediaType.TEXT,
        has_video=False,
        status=ItemStatus.SKIPPED_NO_VIDEO,
        index=2,
    )
    item3 = BookmarkItem(
        tweet_id="103",
        author_handle="charlie",
        text="Old post video",
        media_type=MediaType.VIDEO,
        has_video=True,
        status=ItemStatus.SKIPPED_OUT_OF_RANGE,
        index=3,
    )

    window.table_model.add_or_update_item(item1)
    window.table_model.add_or_update_item(item2)
    window.table_model.add_or_update_item(item3)

    assert window.proxy_model.rowCount() == 3

    # Toggle 'Hide Skipped' ON
    window.chk_hide_skipped.setChecked(True)
    # Should only show item1 (item2 is SKIPPED_NO_VIDEO, item3 is SKIPPED_OUT_OF_RANGE)
    assert window.proxy_model.rowCount() == 1
    displayed_id = window.proxy_model.data(window.proxy_model.index(0, 1), Qt.ItemDataRole.DisplayRole)
    assert displayed_id == "101"

    # Toggle 'Hide Skipped' OFF
    window.chk_hide_skipped.setChecked(False)
    assert window.proxy_model.rowCount() == 3

    # Test Search filter by author
    window.edit_search.setText("charlie")
    assert window.proxy_model.rowCount() == 1
    assert window.proxy_model.data(window.proxy_model.index(0, 2), Qt.ItemDataRole.DisplayRole) == "@charlie"

    # Clear search
    window.edit_search.setText("")
    assert window.proxy_model.rowCount() == 3


def test_at06_3_mainwindow_anchor_reset_and_persistence(qtbot, tmp_path):
    """AT-06.3: Clearing and updating anchor through MainWindow updates UI and saves to disk."""
    state_file = tmp_path / "state.json"
    store = ConfigStore(state_path=state_file)
    settings = AppSettings(last_anchor=AnchorRecord(tweet_id="9999", author_handle="initial_author"))
    store.save(settings)

    window = MainWindow(config_store=store)
    qtbot.addWidget(window)
    window.show()

    # Verify initial anchor banner reflects loaded state
    assert "#9999" in window.lbl_anchor_status.text()
    assert "@initial_author" in window.lbl_anchor_status.text()

    # Click Reset Anchor button
    window.btn_reset_anchor.click()

    # UI label should reset to None
    assert "None (First Run)" in window.lbl_anchor_status.text() or "None" in window.lbl_anchor_status.text()

    # Re-read from disk to ensure persistence occurred
    reloaded = store.load()
    assert reloaded.last_anchor is None


def test_at06_4_mainwindow_worker_signals_and_status_bar(qtbot, tmp_path):
    """AT-06.4: Test signal dispatch updates table progress and status bar multi-cell metrics."""
    store = ConfigStore(state_path=tmp_path / "state.json")
    window = MainWindow(config_store=store)
    qtbot.addWidget(window)
    window.show()

    # 1. Add item through table_model slot
    item = BookmarkItem(
        tweet_id="2001",
        author_handle="streamer",
        media_type=MediaType.VIDEO,
        has_video=True,
        status=ItemStatus.QUEUED,
        index=1,
    )
    window.table_model.add_or_update_item(item)
    assert window.table_model.rowCount() == 1

    # 2. Update item download progress
    item.status = ItemStatus.DOWNLOADING
    item.progress = 65.0
    item.speed_text = "4.2 MB/s"
    window.table_model.update_item(item)

    # Inspect model display value for Progress column (index 6)
    prog_str = window.table_model.data(window.table_model.index(0, 6), Qt.ItemDataRole.DisplayRole)
    assert "65%" in prog_str
    assert "4.2 MB/s" in prog_str

    # 3. Update stats slot
    stats = RunStats(
        scanned=10,
        videos_found=4,
        skipped_no_video=5,
        skipped_date=1,
        downloaded=2,
    )
    window._update_stats_bar(stats)

    # Status bar labels should update
    assert "10" in window.lbl_sb_scanned.text()
    assert "4" in window.lbl_sb_videos.text()
    assert "6" in window.lbl_sb_skipped.text()
    assert "2" in window.lbl_sb_done.text()
