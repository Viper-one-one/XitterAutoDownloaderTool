"""Main classic desktop window for XitterAutoDownloaderTool."""

from __future__ import annotations

import base64
import csv
import html
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QByteArray, QDateTime, QSize, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QStyle,
    QTableView,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src.config import AppSettings, ConfigStore
from src.downloader import check_dependencies
from src.firefox_profile import discover_firefox_profiles, inspect_x_cookies
from src.models import AnchorRecord, BookmarkItem, FirefoxProfile, ItemStatus, RunConfig, RunStats
from src.ui.table_model import (
    BookmarkFilterProxyModel,
    BookmarkTableModel,
    ProgressBarDelegate,
)
from src.worker import ExtractionWorker, SingleDownloadWorker


class MainWindow(QMainWindow):
    """High-density early-2010s desktop utility window for X bookmark video extraction."""

    def __init__(self, config_store: Optional[ConfigStore] = None, parent=None) -> None:
        super().__init__(parent)
        self.config_store = config_store or ConfigStore()
        self.settings: AppSettings = self.config_store.load()
        self._profiles: list[FirefoxProfile] = []
        self._worker: Optional[ExtractionWorker] = None
        self._single_worker: Optional[SingleDownloadWorker] = None
        self._is_paused: bool = False
        self._active_run_stats = RunStats()

        self.setWindowTitle("XitterAutoDownloaderTool — X Bookmark Video Archiver")
        self.resize(1120, 680)
        self.setMinimumSize(860, 540)

        self._build_actions_and_menus()
        self._build_toolbar()
        self._build_central_ui()
        self._build_status_bar()
        self._apply_settings_to_ui()
        self._refresh_profiles(initial=True)
        self._update_run_controls(running=False)
        self._log_startup_info()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_actions_and_menus(self) -> None:
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("&File")
        self.act_select_folder = QAction("Select &Save Folder...", self)
        self.act_select_folder.setShortcut(QKeySequence("Ctrl+O"))
        self.act_select_folder.triggered.connect(self._browse_output_dir)
        file_menu.addAction(self.act_select_folder)

        self.act_open_folder = QAction("&Open Save Folder", self)
        self.act_open_folder.setShortcut(QKeySequence("Ctrl+E"))
        self.act_open_folder.triggered.connect(self._open_output_dir)
        file_menu.addAction(self.act_open_folder)

        self.act_export_csv = QAction("Export Results to &CSV...", self)
        self.act_export_csv.triggered.connect(self._export_results_csv)
        file_menu.addAction(self.act_export_csv)

        file_menu.addSeparator()
        self.act_exit = QAction("E&xit", self)
        self.act_exit.setShortcut(QKeySequence("Ctrl+Q"))
        self.act_exit.triggered.connect(self.close)
        file_menu.addAction(self.act_exit)

        # Edit menu
        edit_menu = menu_bar.addMenu("&Edit")
        self.act_reset_anchor = QAction("&Reset Stop Anchor", self)
        self.act_reset_anchor.triggered.connect(self._clear_anchor)
        edit_menu.addAction(self.act_reset_anchor)

        self.act_clear_finished = QAction("Clear &Finished & Skipped Rows", self)
        self.act_clear_finished.triggered.connect(self._clear_finished_rows)
        edit_menu.addAction(self.act_clear_finished)

        self.act_clear_all_rows = QAction("Clear &All Table Rows", self)
        self.act_clear_all_rows.triggered.connect(self._clear_all_rows)
        edit_menu.addAction(self.act_clear_all_rows)

        edit_menu.addSeparator()
        self.act_clear_log = QAction("Clear &Log Console", self)
        self.act_clear_log.triggered.connect(self._clear_log)
        edit_menu.addAction(self.act_clear_log)

        # View menu
        view_menu = menu_bar.addMenu("&View")
        self.act_hide_skipped = QAction("&Hide Skipped Non-Video Posts", self)
        self.act_hide_skipped.setCheckable(True)
        self.act_hide_skipped.toggled.connect(self._on_hide_skipped_toggled)
        view_menu.addAction(self.act_hide_skipped)

        self.act_toggle_bottom = QAction("Show &Console & Options Pane", self)
        self.act_toggle_bottom.setCheckable(True)
        self.act_toggle_bottom.setChecked(True)
        self.act_toggle_bottom.toggled.connect(self._on_toggle_bottom_pane)
        view_menu.addAction(self.act_toggle_bottom)

        # Tools menu
        tools_menu = menu_bar.addMenu("&Tools")
        self.act_refresh_profiles = QAction("&Refresh Firefox Profiles", self)
        self.act_refresh_profiles.setShortcut(QKeySequence("F5"))
        self.act_refresh_profiles.triggered.connect(lambda: self._refresh_profiles(initial=False))
        tools_menu.addAction(self.act_refresh_profiles)

        self.act_check_deps = QAction("Check &Dependencies (yt-dlp / ffmpeg / Firefox)...", self)
        self.act_check_deps.triggered.connect(self._show_dependencies_dialog)
        tools_menu.addAction(self.act_check_deps)

        self.act_open_data_dir = QAction("Open App &Data Folder", self)
        self.act_open_data_dir.triggered.connect(self._open_data_dir)
        tools_menu.addAction(self.act_open_data_dir)

        # Help menu
        help_menu = menu_bar.addMenu("&Help")
        self.act_guide = QAction("&Quick Usage & Anchor Guide", self)
        self.act_guide.triggered.connect(self._show_usage_guide)
        help_menu.addAction(self.act_guide)

        self.act_about = QAction("&About XitterAutoDownloaderTool", self)
        self.act_about.triggered.connect(self._show_about_dialog)
        help_menu.addAction(self.act_about)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main Controls", self)
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        style = self.style()

        self.btn_start = QPushButton("Start Download", self)
        self.btn_start.setObjectName("primaryButton")
        self.btn_start.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.btn_start.setToolTip("Open X Bookmarks in Firefox and download all new video posts")
        self.btn_start.clicked.connect(lambda: self._start_run(scan_only=False))
        toolbar.addWidget(self.btn_start)

        self.btn_scan_only = QPushButton("Scan Only", self)
        self.btn_scan_only.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView))
        self.btn_scan_only.setToolTip("Inspect bookmarks and filter status without downloading or advancing the anchor")
        self.btn_scan_only.clicked.connect(lambda: self._start_run(scan_only=True))
        toolbar.addWidget(self.btn_scan_only)

        self.btn_pause = QPushButton("Pause", self)
        self.btn_pause.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        self.btn_pause.clicked.connect(self._toggle_pause)
        toolbar.addWidget(self.btn_pause)

        self.btn_stop = QPushButton("Stop", self)
        self.btn_stop.setObjectName("dangerButton")
        self.btn_stop.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.btn_stop.clicked.connect(self._stop_run)
        toolbar.addWidget(self.btn_stop)

        toolbar.addSeparator()

        self.btn_open_folder = QPushButton("Open Folder", self)
        self.btn_open_folder.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.btn_open_folder.clicked.connect(self._open_output_dir)
        toolbar.addWidget(self.btn_open_folder)

        self.btn_reset_anchor = QPushButton("Reset Anchor", self)
        self.btn_reset_anchor.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.btn_reset_anchor.setToolTip("Clear stored last-seen bookmark delimiter so next run relies on date range")
        self.btn_reset_anchor.clicked.connect(self._clear_anchor)
        toolbar.addWidget(self.btn_reset_anchor)

        toolbar.addSeparator()

        spacer = QWidget(self)
        spacer.setFixedWidth(4)
        toolbar.addWidget(spacer)

        self.chk_hide_skipped = QCheckBox("Hide Skipped", self)
        self.chk_hide_skipped.setToolTip("Hide text/image/out-of-range posts from the grid")
        self.chk_hide_skipped.toggled.connect(self._on_hide_skipped_toggled)
        toolbar.addWidget(self.chk_hide_skipped)

        filter_spacer = QWidget(self)
        filter_spacer.setSizePolicy(
            filter_spacer.sizePolicy().horizontalPolicy(),
            filter_spacer.sizePolicy().verticalPolicy(),
        )
        # Expanding spacer pushes Filter to the right side cleanly
        from PySide6.QtWidgets import QSizePolicy

        filter_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(filter_spacer)

        lbl_filter = QLabel("Filter:", self)
        lbl_filter.setContentsMargins(0, 0, 4, 0)
        toolbar.addWidget(lbl_filter)

        self.edit_search = QLineEdit(self)
        self.edit_search.setPlaceholderText("ID, @author, text...")
        self.edit_search.setClearButtonEnabled(True)
        self.edit_search.setFixedWidth(185)
        self.edit_search.textChanged.connect(self._on_search_changed)
        toolbar.addWidget(self.edit_search)

    def _build_central_ui(self) -> None:
        central = QWidget(self)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(6, 5, 6, 4)
        root_layout.setSpacing(5)

        # 1. Top 2-column etched configuration strip
        config_row = QHBoxLayout()
        config_row.setSpacing(6)
        config_row.addWidget(self._build_session_group(), 1)
        config_row.addWidget(self._build_cutoff_group(), 1)
        root_layout.addLayout(config_row)

        # 2. Central vertical splitter: table (top) + console/options tabs (bottom)
        self.splitter = QSplitter(Qt.Orientation.Vertical, central)

        self.table_model = BookmarkTableModel(self)
        self.proxy_model = BookmarkFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.table_model)

        self.table_view = QTableView(self.splitter)
        self.table_view.setModel(self.proxy_model)
        self.table_view.setItemDelegateForColumn(6, ProgressBarDelegate(self.table_view))
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setShowGrid(True)
        self.table_view.setSortingEnabled(True)
        self.table_view.setWordWrap(False)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._show_table_context_menu)
        self.table_view.doubleClicked.connect(self._on_table_double_clicked)

        v_header = self.table_view.verticalHeader()
        v_header.setVisible(False)
        v_header.setDefaultSectionSize(22)
        v_header.setMinimumSectionSize(20)

        h_header = self.table_view.horizontalHeader()
        h_header.setHighlightSections(False)
        h_header.setStretchLastSection(True)
        h_header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        col_widths = [42, 145, 118, 122, 82, 84, 130, 128]
        for idx, width in enumerate(col_widths):
            self.table_view.setColumnWidth(idx, width)
        h_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)

        self.bottom_tabs = QTabWidget(self.splitter)
        self.bottom_tabs.addTab(self._build_log_tab(), "Activity & yt-dlp Log")
        self.bottom_tabs.addTab(self._build_options_tab(), "Download & Naming Options")

        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([420, 180])

        root_layout.addWidget(self.splitter, 1)
        self.setCentralWidget(central)

    def _build_session_group(self) -> QGroupBox:
        group = QGroupBox("Firefox Session & Output", self)
        grid = QGridLayout(group)
        grid.setContentsMargins(6, 6, 6, 5)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        # Row 0: Firefox Profile
        grid.addWidget(QLabel("Profile:", group), 0, 0)
        self.combo_profile = QComboBox(group)
        self.combo_profile.setMinimumWidth(180)
        self.combo_profile.currentIndexChanged.connect(self._on_profile_changed)
        grid.addWidget(self.combo_profile, 0, 1)

        prof_btns = QHBoxLayout()
        prof_btns.setSpacing(3)
        self.btn_refresh_profiles = QPushButton("Refresh", group)
        self.btn_refresh_profiles.setObjectName("compactButton")
        self.btn_refresh_profiles.clicked.connect(lambda: self._refresh_profiles(initial=False))
        self.btn_browse_profile = QPushButton("Browse...", group)
        self.btn_browse_profile.setObjectName("compactButton")
        self.btn_browse_profile.clicked.connect(self._browse_profile_dir)
        prof_btns.addWidget(self.btn_refresh_profiles)
        prof_btns.addWidget(self.btn_browse_profile)
        grid.addLayout(prof_btns, 0, 2)

        # Row 1: Output Folder
        grid.addWidget(QLabel("Save To:", group), 1, 0)
        self.combo_output_dir = QComboBox(group)
        self.combo_output_dir.setEditable(True)
        self.combo_output_dir.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        grid.addWidget(self.combo_output_dir, 1, 1)

        self.btn_browse_output = QPushButton("Browse...", group)
        self.btn_browse_output.setObjectName("compactButton")
        self.btn_browse_output.clicked.connect(self._browse_output_dir)
        grid.addWidget(self.btn_browse_output, 1, 2)

        # Row 2: Browser Mode, Concurrency, Archive
        grid.addWidget(QLabel("Browser:", group), 2, 0)
        opts_row = QHBoxLayout()
        opts_row.setSpacing(8)

        self.radio_headless = QRadioButton("Headless", group)
        self.radio_visible = QRadioButton("Visible", group)
        self._browser_mode_group = QButtonGroup(group)
        self._browser_mode_group.addButton(self.radio_headless)
        self._browser_mode_group.addButton(self.radio_visible)
        opts_row.addWidget(self.radio_headless)
        opts_row.addWidget(self.radio_visible)

        opts_row.addSpacing(8)
        opts_row.addWidget(QLabel("Workers:", group))
        self.spin_concurrency = QSpinBox(group)
        self.spin_concurrency.setRange(1, 4)
        self.spin_concurrency.setFixedWidth(44)
        opts_row.addWidget(self.spin_concurrency)

        opts_row.addSpacing(6)
        self.chk_archive = QCheckBox("Use Archive", group)
        self.chk_archive.setToolTip("Skip tweet IDs already recorded in download_archive.txt")
        opts_row.addWidget(self.chk_archive)
        opts_row.addStretch(1)

        grid.addLayout(opts_row, 2, 1, 1, 2)
        grid.setColumnStretch(1, 1)
        return group

    def _build_cutoff_group(self) -> QGroupBox:
        group = QGroupBox("Extraction Scope & Cutoff Rules", self)
        grid = QGridLayout(group)
        grid.setContentsMargins(6, 6, 6, 5)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        # Row 0: Anchor bookmark stop
        self.chk_anchor_stop = QCheckBox("Stop at Anchor:", group)
        self.chk_anchor_stop.setToolTip(
            "Stop scanning immediately when reaching the most recent bookmark from the previous run"
        )
        grid.addWidget(self.chk_anchor_stop, 0, 0)

        anchor_row = QHBoxLayout()
        anchor_row.setSpacing(4)
        self.lbl_anchor_status = QLabel("None (First Run)", group)
        self.lbl_anchor_status.setObjectName("anchorBanner")
        anchor_row.addWidget(self.lbl_anchor_status, 1)

        self.btn_clear_anchor = QPushButton("Clear", group)
        self.btn_clear_anchor.setObjectName("compactButton")
        self.btn_clear_anchor.clicked.connect(self._clear_anchor)
        anchor_row.addWidget(self.btn_clear_anchor)
        grid.addLayout(anchor_row, 0, 1)

        # Row 1: Date range
        self.chk_date_filter = QCheckBox("Date Range:", group)
        self.chk_date_filter.toggled.connect(self._sync_date_controls_enabled)
        grid.addWidget(self.chk_date_filter, 1, 0)

        date_row = QHBoxLayout()
        date_row.setSpacing(4)
        date_row.addWidget(QLabel("From:", group))
        self.dt_from = QDateTimeEdit(group)
        self.dt_from.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.dt_from.setCalendarPopup(True)
        date_row.addWidget(self.dt_from)

        date_row.addWidget(QLabel("To:", group))
        self.chk_to_now = QCheckBox("Now", group)
        self.chk_to_now.toggled.connect(self._sync_date_controls_enabled)
        date_row.addWidget(self.chk_to_now)

        self.dt_to = QDateTimeEdit(group)
        self.dt_to.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.dt_to.setCalendarPopup(True)
        date_row.addWidget(self.dt_to)
        date_row.addStretch(1)
        grid.addLayout(date_row, 1, 1)

        # Row 2: Fallback limit + media toggles
        grid.addWidget(QLabel("Fallback Stop:", group), 2, 0)
        fallback_row = QHBoxLayout()
        fallback_row.setSpacing(4)
        fallback_row.addWidget(QLabel("After", group))
        self.spin_old_limit = QSpinBox(group)
        self.spin_old_limit.setRange(1, 500)
        self.spin_old_limit.setFixedWidth(50)
        self.spin_old_limit.setToolTip(
            "Stop scrolling after this many consecutive posts older than From date (used when no anchor stops the run first)"
        )
        fallback_row.addWidget(self.spin_old_limit)
        fallback_row.addWidget(QLabel("older posts", group))

        fallback_row.addSpacing(8)
        self.chk_include_gifs = QCheckBox("GIFs", group)
        self.chk_include_gifs.setToolTip("Download animated GIF loops as MP4 videos")
        fallback_row.addWidget(self.chk_include_gifs)

        self.chk_include_quoted = QCheckBox("Quoted Videos", group)
        self.chk_include_quoted.setToolTip("Also download videos embedded inside quoted posts")
        fallback_row.addWidget(self.chk_include_quoted)
        fallback_row.addStretch(1)
        grid.addLayout(fallback_row, 2, 1)

        grid.setColumnStretch(1, 1)
        return group

    def _build_log_tab(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(4)
        top_bar.addWidget(QLabel("Execution Trace:", widget))
        top_bar.addStretch(1)

        btn_copy = QPushButton("Copy Log", widget)
        btn_copy.setObjectName("compactButton")
        btn_copy.clicked.connect(self._copy_log)
        top_bar.addWidget(btn_copy)

        btn_clear = QPushButton("Clear", widget)
        btn_clear.setObjectName("compactButton")
        btn_clear.clicked.connect(self._clear_log)
        top_bar.addWidget(btn_clear)
        layout.addLayout(top_bar)

        self.log_console = QPlainTextEdit(widget)
        self.log_console.setObjectName("logConsole")
        self.log_console.setReadOnly(True)
        self.log_console.setMaximumBlockCount(5000)
        layout.addWidget(self.log_console, 1)
        return widget

    def _build_options_tab(self) -> QWidget:
        widget = QWidget(self)
        grid = QGridLayout(widget)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)

        # Row 0: Filename template + presets
        grid.addWidget(QLabel("Filename Template:", widget), 0, 0)
        tmpl_row = QHBoxLayout()
        tmpl_row.setSpacing(4)
        self.edit_filename_tmpl = QLineEdit(widget)
        tmpl_row.addWidget(self.edit_filename_tmpl, 1)

        presets = [
            ("@user - date - id", "%(uploader_id)s - %(upload_date)s - %(id)s.%(ext)s"),
            ("date_@user_id", "%(upload_date)s_%(uploader_id)s_%(id)s.%(ext)s"),
            ("id", "%(id)s.%(ext)s"),
        ]
        for label, tmpl_val in presets:
            btn = QPushButton(label, widget)
            btn.setObjectName("compactButton")
            btn.clicked.connect(lambda _checked=False, v=tmpl_val: self.edit_filename_tmpl.setText(v))
            tmpl_row.addWidget(btn)
        grid.addLayout(tmpl_row, 0, 1)

        # Row 1: Format selector
        grid.addWidget(QLabel("yt-dlp Format:", widget), 1, 0)
        self.combo_format = QComboBox(widget)
        self.combo_format.setEditable(True)
        self.combo_format.addItems(
            [
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "best[ext=mp4]/best",
                "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best",
                "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best",
            ]
        )
        grid.addWidget(self.combo_format, 1, 1)

        # Row 2: Extra yt-dlp metadata + scrolling parameters
        grid.addWidget(QLabel("Extras & Tuning:", widget), 2, 0)
        extra_row = QHBoxLayout()
        extra_row.setSpacing(10)
        self.chk_write_info = QCheckBox("Write .info.json", widget)
        self.chk_write_thumb = QCheckBox("Write thumbnail", widget)
        extra_row.addWidget(self.chk_write_info)
        extra_row.addWidget(self.chk_write_thumb)

        extra_row.addSpacing(12)
        extra_row.addWidget(QLabel("Scroll Delay (ms):", widget))
        self.spin_scroll_delay = QSpinBox(widget)
        self.spin_scroll_delay.setRange(200, 10000)
        self.spin_scroll_delay.setSingleStep(100)
        self.spin_scroll_delay.setFixedWidth(68)
        extra_row.addWidget(self.spin_scroll_delay)

        extra_row.addWidget(QLabel("Max Scrolls:", widget))
        self.spin_max_scrolls = QSpinBox(widget)
        self.spin_max_scrolls.setRange(10, 5000)
        self.spin_max_scrolls.setSingleStep(50)
        self.spin_max_scrolls.setFixedWidth(68)
        extra_row.addWidget(self.spin_max_scrolls)
        extra_row.addStretch(1)
        grid.addLayout(extra_row, 2, 1)

        grid.setRowStretch(3, 1)
        grid.setColumnStretch(1, 1)
        return widget

    def _make_status_cell(self, initial_text: str) -> tuple[QFrame, QLabel]:
        frame = QFrame(self)
        frame.setObjectName("statusCell")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(4, 1, 4, 1)
        lbl = QLabel(initial_text, frame)
        layout.addWidget(lbl)
        return frame, lbl

    def _build_status_bar(self) -> None:
        sb = QStatusBar(self)
        sb.setSizeGripEnabled(True)
        self.setStatusBar(sb)

        cell_auth, self.lbl_sb_auth = self._make_status_cell("Profile: None")
        cell_scanned, self.lbl_sb_scanned = self._make_status_cell("Scanned: 0")
        cell_videos, self.lbl_sb_videos = self._make_status_cell("Videos: 0")
        cell_skipped, self.lbl_sb_skipped = self._make_status_cell("Skipped: 0")
        cell_done, self.lbl_sb_done = self._make_status_cell("Done: 0")
        cell_failed, self.lbl_sb_failed = self._make_status_cell("Failed: 0")

        self.global_progress = QProgressBar(self)
        self.global_progress.setObjectName("globalProgress")
        self.global_progress.setRange(0, 100)
        self.global_progress.setValue(0)
        self.global_progress.setFixedWidth(135)
        self.global_progress.setFormat("%v / %m")

        cell_state, self.lbl_sb_state = self._make_status_cell("Idle")

        sb.addWidget(cell_auth)
        sb.addWidget(cell_scanned)
        sb.addWidget(cell_videos)
        sb.addWidget(cell_skipped)
        sb.addWidget(cell_done)
        sb.addWidget(cell_failed)
        sb.addWidget(self.global_progress)
        sb.addPermanentWidget(cell_state, 1)

    # ------------------------------------------------------------------
    # Settings Load / Save / Sync
    # ------------------------------------------------------------------

    def _apply_settings_to_ui(self) -> None:
        s = self.settings
        # Output dirs
        self.combo_output_dir.clear()
        seen_dirs: set[str] = set()
        for d in [s.output_dir, *s.recent_output_dirs]:
            norm = os.path.normpath(d) if d else ""
            if norm and norm.lower() not in seen_dirs:
                seen_dirs.add(norm.lower())
                self.combo_output_dir.addItem(norm)
        self.combo_output_dir.setCurrentText(s.output_dir)

        self.radio_headless.setChecked(s.headless)
        self.radio_visible.setChecked(not s.headless)
        self.spin_concurrency.setValue(s.concurrency)
        self.chk_archive.setChecked(s.use_download_archive)

        self.chk_anchor_stop.setChecked(s.use_anchor_stop)
        self._update_anchor_display(s.last_anchor)

        self.chk_date_filter.setChecked(s.use_date_filter)
        self.dt_from.setDateTime(self._iso_to_local_qdatetime(s.date_from_iso, fallback_days=30))
        self.chk_to_now.setChecked(s.use_date_to_now)
        self.dt_to.setDateTime(self._iso_to_local_qdatetime(s.date_to_iso, fallback_days=0))
        self._sync_date_controls_enabled()

        self.spin_old_limit.setValue(s.consecutive_old_limit)
        self.chk_include_gifs.setChecked(s.include_gifs)
        self.chk_include_quoted.setChecked(s.include_quoted_videos)

        self.edit_filename_tmpl.setText(s.filename_template)
        self.combo_format.setCurrentText(s.format_selector)
        self.chk_write_info.setChecked(s.write_info_json)
        self.chk_write_thumb.setChecked(s.write_thumbnail)
        self.spin_scroll_delay.setValue(s.scroll_pause_ms)
        self.spin_max_scrolls.setValue(s.max_scrolls)

        self.chk_hide_skipped.setChecked(s.hide_skipped)
        self.act_hide_skipped.setChecked(s.hide_skipped)
        self.proxy_model.set_hide_skipped(s.hide_skipped)

        if s.splitter_sizes and len(s.splitter_sizes) == 2:
            self.splitter.setSizes(s.splitter_sizes)
        if s.window_geometry_b64:
            try:
                raw = base64.b64decode(s.window_geometry_b64.encode("ascii"))
                self.restoreGeometry(QByteArray(raw))
            except Exception:
                pass

    def _collect_settings_from_ui(self) -> AppSettings:
        s = self.settings
        s.last_profile_path = str(self.combo_profile.currentData() or "")
        out_dir = self.combo_output_dir.currentText().strip() or s.output_dir
        s.output_dir = out_dir
        self.config_store.add_recent_output_dir(s, out_dir)

        s.headless = self.radio_headless.isChecked()
        s.concurrency = self.spin_concurrency.value()
        s.use_download_archive = self.chk_archive.isChecked()

        s.use_anchor_stop = self.chk_anchor_stop.isChecked()
        s.use_date_filter = self.chk_date_filter.isChecked()
        s.date_from_iso = self._qdatetime_to_utc(self.dt_from.dateTime()).isoformat()
        s.use_date_to_now = self.chk_to_now.isChecked()
        s.date_to_iso = self._qdatetime_to_utc(self.dt_to.dateTime()).isoformat()

        s.consecutive_old_limit = self.spin_old_limit.value()
        s.include_gifs = self.chk_include_gifs.isChecked()
        s.include_quoted_videos = self.chk_include_quoted.isChecked()

        s.filename_template = (
            self.edit_filename_tmpl.text().strip()
            or "%(uploader_id)s - %(upload_date)s - %(id)s.%(ext)s"
        )
        s.format_selector = (
            self.combo_format.currentText().strip()
            or "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        )
        s.write_info_json = self.chk_write_info.isChecked()
        s.write_thumbnail = self.chk_write_thumb.isChecked()
        s.scroll_pause_ms = self.spin_scroll_delay.value()
        s.max_scrolls = self.spin_max_scrolls.value()
        s.hide_skipped = self.chk_hide_skipped.isChecked()

        s.splitter_sizes = self.splitter.sizes()
        geom_bytes = bytes(self.saveGeometry().toBase64())
        s.window_geometry_b64 = geom_bytes.decode("ascii")
        return s

    def _persist_settings(self) -> None:
        try:
            self.config_store.save(self._collect_settings_from_ui())
        except Exception as exc:
            self._append_log("WARN", f"Could not save state.json: {exc}")

    @staticmethod
    def _iso_to_local_qdatetime(iso_str: str, fallback_days: int) -> QDateTime:
        dt: Optional[datetime] = None
        if iso_str:
            try:
                dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except ValueError:
                dt = None
        if dt is None:
            now_local = datetime.now().astimezone()
            if fallback_days > 0:
                from datetime import timedelta

                dt = (now_local - timedelta(days=fallback_days)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
            else:
                dt = now_local
        local_dt = dt.astimezone()
        return QDateTime(
            local_dt.year,
            local_dt.month,
            local_dt.day,
            local_dt.hour,
            local_dt.minute,
            local_dt.second,
        )

    @staticmethod
    def _qdatetime_to_utc(qdt: QDateTime) -> datetime:
        py_local = qdt.toPython()
        if py_local.tzinfo is None:
            py_local = py_local.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return py_local.astimezone(timezone.utc)

    # ------------------------------------------------------------------
    # Profile & Folder Management
    # ------------------------------------------------------------------

    def _refresh_profiles(self, initial: bool = False) -> None:
        previous = str(self.combo_profile.currentData() or self.settings.last_profile_path or "")
        self._profiles = discover_firefox_profiles()

        self.combo_profile.blockSignals(True)
        self.combo_profile.clear()

        for prof in self._profiles:
            self._add_profile_combo_item(prof)

        # Preserve custom profile directory if user had selected one manually
        prev_is_dir = False
        if previous:
            try:
                prev_is_dir = Path(previous).is_dir()
            except OSError:
                prev_is_dir = False
        if prev_is_dir:
            if self.combo_profile.findData(previous) < 0:
                has_auth, summary = inspect_x_cookies(Path(previous))
                try:
                    has_db = (Path(previous) / "cookies.sqlite").is_file()
                except OSError:
                    has_db = False
                custom_prof = FirefoxProfile(
                    name=Path(previous).name,
                    path=previous,
                    has_cookies_db=has_db,
                    has_x_auth=has_auth,
                    cookie_summary=summary,
                )
                self._profiles.append(custom_prof)
                self._add_profile_combo_item(custom_prof)

        if previous:
            idx = self.combo_profile.findData(previous)
            if idx >= 0:
                self.combo_profile.setCurrentIndex(idx)

        self.combo_profile.blockSignals(False)
        self._on_profile_changed()

        if not initial:
            self._append_log("INFO", f"Refreshed Firefox profiles ({len(self._profiles)} found).")

    def _add_profile_combo_item(self, prof: FirefoxProfile) -> None:
        default_tag = " [Default]" if prof.is_default else ""
        auth_tag = "Auth OK" if prof.has_x_auth else "No X Auth"
        label = f"{prof.name}{default_tag} — {auth_tag}"
        self.combo_profile.addItem(label, prof.path)

    def _on_profile_changed(self) -> None:
        path_str = str(self.combo_profile.currentData() or "")
        if not path_str:
            self.lbl_sb_auth.setText("Profile: None Selected")
            return
        matched = next((p for p in self._profiles if p.path == path_str), None)
        if matched is None:
            has_auth, summary = inspect_x_cookies(Path(path_str))
            self.lbl_sb_auth.setText(f"Profile: {summary}")
        else:
            state = "Auth OK" if matched.has_x_auth else matched.cookie_summary
            self.lbl_sb_auth.setText(f"Profile: {matched.name} ({state})")

    def _browse_profile_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Select Firefox Profile Folder",
            str(self.combo_profile.currentData() or Path.home()),
        )
        if not chosen:
            return
        has_auth, summary = inspect_x_cookies(Path(chosen))
        existing_idx = self.combo_profile.findData(chosen)
        if existing_idx < 0:
            prof = FirefoxProfile(
                name=Path(chosen).name,
                path=chosen,
                has_cookies_db=(Path(chosen) / "cookies.sqlite").is_file(),
                has_x_auth=has_auth,
                cookie_summary=summary,
            )
            self._profiles.append(prof)
            self._add_profile_combo_item(prof)
            existing_idx = self.combo_profile.findData(chosen)
        self.combo_profile.setCurrentIndex(existing_idx)
        self._persist_settings()
        self._append_log("INFO", f"Selected custom Firefox profile: {chosen} ({summary})")

    def _browse_output_dir(self) -> None:
        current = self.combo_output_dir.currentText().strip() or self.settings.output_dir
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Select Download Output Folder",
            current,
        )
        if not chosen:
            return
        norm = os.path.normpath(chosen)
        if self.combo_output_dir.findText(norm) < 0:
            self.combo_output_dir.insertItem(0, norm)
        self.combo_output_dir.setCurrentText(norm)
        self._persist_settings()

    def _open_output_dir(self) -> None:
        folder = Path(self.combo_output_dir.currentText().strip() or self.settings.output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _open_data_dir(self) -> None:
        data_dir = self.config_store.state_path.parent
        data_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir)))

    # ------------------------------------------------------------------
    # Anchor, Filter & Controls Sync
    # ------------------------------------------------------------------

    def _sync_date_controls_enabled(self) -> None:
        enabled = self.chk_date_filter.isChecked()
        self.dt_from.setEnabled(enabled)
        self.chk_to_now.setEnabled(enabled)
        self.dt_to.setEnabled(enabled and not self.chk_to_now.isChecked())

    def _update_anchor_display(self, anchor: Optional[AnchorRecord]) -> None:
        if anchor is None:
            self.lbl_anchor_status.setText("None (First Run)")
            self.lbl_anchor_status.setToolTip("No bookmark delimiter saved yet.")
        else:
            author = f"@{anchor.author_handle}" if anchor.author_handle else "unknown"
            self.lbl_anchor_status.setText(f"#{anchor.tweet_id} ({author})")
            tip_lines = [
                f"Anchor Tweet ID: {anchor.tweet_id}",
                f"Author: {author}",
                f"Post Date: {anchor.created_at or 'Unknown'}",
                f"Recorded: {anchor.recorded_at or 'Unknown'}",
            ]
            if anchor.snippet:
                tip_lines.append(f"Snippet: {anchor.snippet}")
            self.lbl_anchor_status.setToolTip("\n".join(tip_lines))

    def _clear_anchor(self) -> None:
        self.config_store.update_anchor(self.settings, None)
        self._update_anchor_display(None)
        self._append_log("INFO", "Cleared last-seen stop anchor bookmark.")

    def _on_hide_skipped_toggled(self, checked: bool) -> None:
        if self.chk_hide_skipped.isChecked() != checked:
            self.chk_hide_skipped.setChecked(checked)
        if self.act_hide_skipped.isChecked() != checked:
            self.act_hide_skipped.setChecked(checked)
        self.proxy_model.set_hide_skipped(checked)

    def _on_search_changed(self, text: str) -> None:
        self.proxy_model.set_search_text(text)

    def _on_toggle_bottom_pane(self, visible: bool) -> None:
        self.bottom_tabs.setVisible(visible)

    def _update_run_controls(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_scan_only.setEnabled(not running)
        self.btn_pause.setEnabled(running)
        self.btn_stop.setEnabled(running)

        self.combo_profile.setEnabled(not running)
        self.btn_refresh_profiles.setEnabled(not running)
        self.btn_browse_profile.setEnabled(not running)
        self.btn_reset_anchor.setEnabled(not running)
        self.btn_clear_anchor.setEnabled(not running)

        if not running:
            self._is_paused = False
            self.btn_pause.setText("Pause")

    # ------------------------------------------------------------------
    # Extraction & Download Execution
    # ------------------------------------------------------------------

    def _build_run_config(self, scan_only: bool) -> Optional[RunConfig]:
        profile_path = str(self.combo_profile.currentData() or "").strip()
        if not profile_path and self.radio_headless.isChecked():
            QMessageBox.warning(
                self,
                "No Firefox Profile Selected",
                "No local Firefox profile was detected.\n\n"
                "Click 'Browse...' to select a Firefox profile directory, or switch Browser Mode to 'Visible' to sign in manually.",
            )
            return None

        output_dir = self.combo_output_dir.currentText().strip()
        if not output_dir:
            QMessageBox.warning(
                self,
                "Output Folder Required",
                "Please select a folder where downloaded videos should be saved.",
            )
            return None

        if not scan_only:
            try:
                Path(output_dir).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                QMessageBox.critical(
                    self,
                    "Invalid Output Folder",
                    f"Could not create output folder:\n{output_dir}\n\n{exc}",
                )
                return None

        self._persist_settings()

        date_from: Optional[datetime] = None
        date_to: Optional[datetime] = None
        if self.chk_date_filter.isChecked():
            date_from = self._qdatetime_to_utc(self.dt_from.dateTime())
            if not self.chk_to_now.isChecked():
                date_to = self._qdatetime_to_utc(self.dt_to.dateTime())
                if date_to < date_from:
                    QMessageBox.warning(
                        self,
                        "Invalid Date Range",
                        "'From' date/time must be earlier than 'To' date/time.",
                    )
                    return None

        anchor_id = (
            self.settings.last_anchor.tweet_id
            if (self.chk_anchor_stop.isChecked() and self.settings.last_anchor)
            else None
        )

        return RunConfig(
            profile_path=profile_path,
            output_dir=output_dir,
            headless=self.radio_headless.isChecked(),
            scan_only=scan_only,
            use_anchor_stop=self.chk_anchor_stop.isChecked(),
            anchor_tweet_id=anchor_id,
            use_date_filter=self.chk_date_filter.isChecked(),
            date_from=date_from,
            date_to=date_to,
            consecutive_old_limit=self.spin_old_limit.value(),
            max_scrolls=self.spin_max_scrolls.value(),
            include_gifs=self.chk_include_gifs.isChecked(),
            include_quoted_videos=self.chk_include_quoted.isChecked(),
            filename_template=self.edit_filename_tmpl.text().strip()
            or "%(uploader_id)s - %(upload_date)s - %(id)s.%(ext)s",
            format_selector=self.combo_format.currentText().strip()
            or "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            concurrency=self.spin_concurrency.value(),
            use_download_archive=self.chk_archive.isChecked(),
            write_info_json=self.chk_write_info.isChecked(),
            write_thumbnail=self.chk_write_thumb.isChecked(),
            scroll_pause_ms=self.spin_scroll_delay.value(),
        )

    def _start_run(self, scan_only: bool) -> None:
        if self._worker is not None and self._worker.isRunning():
            return

        config = self._build_run_config(scan_only=scan_only)
        if config is None:
            return

        self.table_model.clear_all()
        self._active_run_stats = RunStats()
        self._update_stats_bar(self._active_run_stats)
        self._update_run_controls(running=True)

        mode_name = "Scan Only" if scan_only else "Extraction & Download"
        self._append_log("INFO", f"=== Starting {mode_name} ===")
        if config.anchor_tweet_id:
            self._append_log("INFO", f"Stop Anchor active: #{config.anchor_tweet_id}")
        if config.use_date_filter and config.date_from:
            to_desc = config.date_to.strftime("%Y-%m-%d %H:%M UTC") if config.date_to else "Now"
            self._append_log(
                "INFO",
                f"Date Filter: {config.date_from.strftime('%Y-%m-%d %H:%M UTC')} -> {to_desc} "
                f"(stop after {config.consecutive_old_limit} older posts)",
            )

        self._worker = ExtractionWorker(config, parent=self)
        self._worker.log_message.connect(self._append_log)
        self._worker.item_added.connect(self.table_model.add_or_update_item)
        self._worker.item_updated.connect(self.table_model.update_item)
        self._worker.stats_updated.connect(self._update_stats_bar)
        self._worker.status_changed.connect(self.lbl_sb_state.setText)
        self._worker.anchor_candidate_ready.connect(self._on_anchor_candidate_ready)
        self._worker.run_finished.connect(self._on_run_finished)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _toggle_pause(self) -> None:
        if self._worker is None or not self._worker.isRunning():
            return
        self._is_paused = not self._is_paused
        self._worker.set_paused(self._is_paused)
        self.btn_pause.setText("Resume" if self._is_paused else "Pause")

    def _stop_run(self) -> None:
        if self._worker is None or not self._worker.isRunning():
            return
        self.btn_stop.setEnabled(False)
        self.lbl_sb_state.setText("Stopping...")
        self._append_log("WARN", "Stop requested. Finishing current cleanup...")
        self._worker.request_stop()

    def _on_anchor_candidate_ready(self, anchor: AnchorRecord) -> None:
        self.config_store.update_anchor(self.settings, anchor)
        self._update_anchor_display(anchor)
        self._append_log(
            "INFO",
            f"Updated Stop Anchor to newest seen bookmark: #{anchor.tweet_id} (@{anchor.author_handle})",
        )

    def _on_run_finished(self, success: bool, summary: str, stats: RunStats) -> None:
        self._active_run_stats = stats
        self._update_stats_bar(stats)
        self._update_run_controls(running=False)
        self._worker = None

        level = "SUCCESS" if success else "WARN"
        self._append_log(
            level,
            f"=== Finished: {summary} | Scanned={stats.scanned}, Videos={stats.videos_found}, "
            f"Done={stats.downloaded}, Archived={stats.skipped_archive}, "
            f"Skipped={stats.skipped_no_video + stats.skipped_date}, Failed={stats.failed} ===",
        )

        if not success and "login" in summary.lower():
            QMessageBox.warning(self, "X Authentication Required", summary)

    def _update_stats_bar(self, stats: RunStats) -> None:
        total_skipped = stats.skipped_no_video + stats.skipped_date + stats.skipped_archive
        self.lbl_sb_scanned.setText(f"Scanned: {stats.scanned}")
        self.lbl_sb_videos.setText(f"Videos: {stats.videos_found}")
        self.lbl_sb_skipped.setText(f"Skipped: {total_skipped}")
        self.lbl_sb_done.setText(f"Done: {stats.downloaded}")
        self.lbl_sb_failed.setText(f"Failed: {stats.failed}")

        completed_videos = stats.downloaded + stats.failed + stats.skipped_archive
        if stats.videos_found > 0:
            self.global_progress.setRange(0, stats.videos_found)
            self.global_progress.setValue(min(completed_videos, stats.videos_found))
            self.global_progress.setFormat("%v / %m")
        else:
            self.global_progress.setRange(0, 100)
            self.global_progress.setValue(0)
            self.global_progress.setFormat("0 / 0")

    # ------------------------------------------------------------------
    # Table Actions & Context Menu
    # ------------------------------------------------------------------

    def _selected_bookmark(self) -> Optional[BookmarkItem]:
        sel = self.table_view.selectionModel()
        if sel is None:
            return None
        indexes = sel.selectedRows()
        if not indexes:
            return None
        source_idx = self.proxy_model.mapToSource(indexes[0])
        return self.table_model.get_item(source_idx.row())

    def _on_table_double_clicked(self, proxy_index) -> None:
        source_idx = self.proxy_model.mapToSource(proxy_index)
        item = self.table_model.get_item(source_idx.row())
        if item is None:
            return
        if item.saved_filepath and Path(item.saved_filepath).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(item.saved_filepath))
        else:
            QDesktopServices.openUrl(QUrl(item.url))

    def _show_table_context_menu(self, pos) -> None:
        item = self._selected_bookmark()
        if item is None:
            return

        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        has_file = bool(item.saved_filepath and Path(item.saved_filepath).is_file())

        act_open_file = menu.addAction("Open Downloaded Video")
        act_open_file.setEnabled(has_file)
        act_open_file.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(item.saved_filepath))
        )

        act_show_explorer = menu.addAction("Show in Explorer")
        act_show_explorer.setEnabled(has_file)
        act_show_explorer.triggered.connect(lambda: self._reveal_in_explorer(item.saved_filepath))

        act_open_post = menu.addAction("Open Post in Browser")
        act_open_post.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(item.url)))

        act_copy_url = menu.addAction("Copy Post URL")
        act_copy_url.triggered.connect(lambda: self._copy_text(item.url))

        menu.addSeparator()

        can_retry = (
            (self._worker is None or not self._worker.isRunning())
            and (self._single_worker is None or not self._single_worker.isRunning())
            and (
                item.has_video
                or item.status in (ItemStatus.FAILED, ItemStatus.CANCELLED, ItemStatus.QUEUED)
            )
        )
        act_retry = menu.addAction("Retry Download")
        act_retry.setEnabled(can_retry)
        act_retry.triggered.connect(lambda: self._retry_single_item(item))

        act_set_anchor = menu.addAction("Set as Stop Anchor")
        act_set_anchor.setEnabled(self._worker is None or not self._worker.isRunning())
        act_set_anchor.triggered.connect(lambda: self._set_item_as_anchor(item))

        menu.exec(self.table_view.viewport().mapToGlobal(pos))

    @staticmethod
    def _reveal_in_explorer(filepath: str) -> None:
        target = Path(filepath)
        if sys.platform.startswith("win") and target.exists():
            subprocess.Popen(["explorer", "/select,", str(target)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))

    def _copy_text(self, text: str) -> None:
        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

    def _retry_single_item(self, item: BookmarkItem) -> None:
        config = self._build_run_config(scan_only=False)
        if config is None:
            return
        self._append_log("INFO", f"Retrying download for #{item.tweet_id} (@{item.author_handle})...")
        self.lbl_sb_state.setText(f"Retrying #{item.tweet_id}...")

        self._single_worker = SingleDownloadWorker(config, item, parent=self)
        self._single_worker.log_message.connect(self._append_log)
        self._single_worker.item_updated.connect(self.table_model.update_item)
        self._single_worker.finished_one.connect(self._on_single_download_finished)
        self._single_worker.finished.connect(self._single_worker.deleteLater)
        self._single_worker.start()

    def _on_single_download_finished(self, _ok: bool, _item: BookmarkItem) -> None:
        self._single_worker = None
        self.lbl_sb_state.setText("Idle")

    def _set_item_as_anchor(self, item: BookmarkItem) -> None:
        snippet = (item.text or "").replace("\n", " ").strip()
        if len(snippet) > 80:
            snippet = snippet[:77] + "..."
        anchor = AnchorRecord(
            tweet_id=item.tweet_id,
            author_handle=item.author_handle,
            created_at=item.created_at.isoformat() if item.created_at else None,
            snippet=snippet,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        self.config_store.update_anchor(self.settings, anchor)
        self._update_anchor_display(anchor)
        self._append_log("INFO", f"Manually set Stop Anchor to #{item.tweet_id} (@{item.author_handle}).")

    def _clear_finished_rows(self) -> None:
        self.table_model.clear_completed_and_skipped()

    def _clear_all_rows(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.table_model.clear_all()

    def _export_results_csv(self) -> None:
        items = self.table_model.all_items()
        if not items:
            QMessageBox.information(self, "Export CSV", "No bookmark rows to export.")
            return
        default_path = str(Path(self.combo_output_dir.currentText() or ".") / "bookmarks_export.csv")
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Export Bookmark Results",
            default_path,
            "CSV Files (*.csv);;All Files (*.*)",
        )
        if not dest:
            return
        try:
            with open(dest, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "Index",
                        "Post ID",
                        "Author",
                        "Post Date (UTC)",
                        "Media Type",
                        "Details",
                        "Status",
                        "Saved File",
                        "URL",
                        "Error",
                    ]
                )
                for it in items:
                    writer.writerow(
                        [
                            it.index,
                            it.tweet_id,
                            f"@{it.author_handle}",
                            it.created_at.isoformat() if it.created_at else "",
                            it.media_type.value,
                            it.details_summary,
                            it.status.value,
                            it.saved_filepath,
                            it.url,
                            it.error_message,
                        ]
                    )
            self._append_log("SUCCESS", f"Exported {len(items)} rows to {dest}")
        except OSError as exc:
            QMessageBox.critical(self, "Export Failed", f"Failed to write CSV:\n{exc}")

    # ------------------------------------------------------------------
    # Logging & Dialogs
    # ------------------------------------------------------------------

    def _append_log(self, level: str, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        lvl = level.upper()
        color_map = {
            "INFO": "#1F2937",
            "WARN": "#9A5B00",
            "ERROR": "#A81C1C",
            "SUCCESS": "#166A14",
        }
        color = color_map.get(lvl, "#1F2937")
        safe_msg = html.escape(message)
        line_html = (
            f'<span style="color:#6B7280;">{ts}</span> '
            f'<span style="color:{color};font-weight:bold;">[{lvl}]</span> '
            f'<span style="color:{color};">{safe_msg}</span>'
        )
        self.log_console.appendHtml(line_html)

    def _clear_log(self) -> None:
        self.log_console.clear()

    def _copy_log(self) -> None:
        self._copy_text(self.log_console.toPlainText())

    def _log_startup_info(self) -> None:
        ffmpeg_ok = shutil.which("ffmpeg") is not None
        self._append_log(
            "INFO",
            f"Initialized. Detected {len(self._profiles)} Firefox profile(s). "
            f"ffmpeg={'OK' if ffmpeg_ok else 'MISSING (streams may not merge)'}",
        )
        if self.settings.last_anchor:
            self._append_log(
                "INFO",
                f"Active Stop Anchor: #{self.settings.last_anchor.tweet_id} (@{self.settings.last_anchor.author_handle})",
            )

    def _show_dependencies_dialog(self) -> None:
        deps = check_dependencies()
        lines: list[str] = []
        for key, label in (
            ("yt_dlp", "yt-dlp"),
            ("ffmpeg", "FFmpeg"),
            ("playwright_firefox", "Playwright Firefox"),
        ):
            ok, detail = deps.get(key, (False, "Not checked"))
            badge = "[OK]" if ok else "[MISSING]"
            lines.append(f"{badge} {label}: {detail}")
        QMessageBox.information(self, "Runtime Dependency Check", "\n".join(lines))

    def _show_usage_guide(self) -> None:
        QMessageBox.information(
            self,
            "Quick Usage & Anchor Guide",
            "1. Select your Firefox profile (log into x.com in Firefox first, or choose Visible mode).\n"
            "2. Choose the destination folder under 'Save To:'.\n"
            "3. Set your Date Range fallback ('From' date to 'Now').\n"
            "4. Click 'Start Download'.\n\n"
            "How Incremental Runs Work:\n"
            "• Posts without video (text/images) are skipped automatically.\n"
            "• Each successful run remembers the newest bookmark (#ID) at the top of your feed as the Stop Anchor.\n"
            "• Subsequent runs stop immediately upon reaching that Stop Anchor, or fall back to stopping after N consecutive posts older than your 'From' date.",
        )

    def _show_about_dialog(self) -> None:
        QMessageBox.about(
            self,
            "About XitterAutoDownloaderTool",
            "XitterAutoDownloaderTool\n\n"
            "Desktop utility for extracting and archiving video posts from X (Twitter) Bookmarks "
            "using Firefox session profiles, Playwright automation, and yt-dlp.\n\n"
            "Built with Python + PySide6.",
        )

    # ------------------------------------------------------------------
    # Close & Shutdown
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Extraction Running",
                "An extraction or download run is currently in progress.\n"
                "Stop the active run and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._worker.request_stop()
            self._worker.wait(3000)

        self._persist_settings()
        super().closeEvent(event)
