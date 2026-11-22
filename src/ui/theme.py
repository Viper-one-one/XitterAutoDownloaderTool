"""Early-2010s classic desktop utility QSS theme and icon generator."""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)


def get_classic_stylesheet() -> str:
    """Return a high-density, early-2010s Aero/Classic QSS stylesheet."""
    return """
    QWidget {
        font-family: "Segoe UI", "Tahoma", "MS Shell Dlg 2", sans-serif;
        font-size: 8.5pt;
        color: #1A1E24;
    }

    QMainWindow, QDialog {
        background-color: #ECEFF4;
    }

    /* Menu Bar */
    QMenuBar {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #F8FAFC, stop:1 #E4E8EF);
        border-bottom: 1px solid #BCC4D0;
        padding: 1px 2px;
        spacing: 2px;
    }
    QMenuBar::item {
        background: transparent;
        padding: 3px 7px;
        border: 1px solid transparent;
        border-radius: 2px;
    }
    QMenuBar::item:selected {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #EBF3FD, stop:1 #CFE2FA);
        border: 1px solid #7DA2CE;
        color: #000000;
    }
    QMenu {
        background-color: #F6F7F9;
        border: 1px solid #9BA7B8;
        padding: 2px;
    }
    QMenu::item {
        padding: 4px 24px 4px 20px;
        border: 1px solid transparent;
    }
    QMenu::item:selected {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #EBF3FD, stop:1 #CFE2FA);
        border: 1px solid #7DA2CE;
        color: #000000;
    }
    QMenu::separator {
        height: 1px;
        background: #D0D7E2;
        margin: 2px 4px;
    }

    /* Classic Metallic Toolbar */
    QToolBar#mainToolbar {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #FAFBFC, stop:0.48 #ECEFF5, stop:1 #DCE2EC);
        border-top: 1px solid #FFFFFF;
        border-bottom: 1px solid #9BA7B8;
        padding: 3px 5px;
        spacing: 4px;
    }
    QToolBar#mainToolbar::separator {
        width: 1px;
        background: #B4BECB;
        margin: 2px 4px;
    }

    /* Classic Beveled Buttons */
    QPushButton, QToolButton {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #FBFDFE, stop:0.45 #EDF2F8, stop:0.5 #E1E8F2, stop:1 #D5DFEC);
        border: 1px solid #8E9BAE;
        border-radius: 2px;
        padding: 2px 9px;
        min-height: 18px;
        color: #1A1E24;
    }
    QPushButton:hover, QToolButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #F7FBFF, stop:0.45 #E3EFFC, stop:0.5 #CFE3FA, stop:1 #BCD7F7);
        border: 1px solid #4C7EB5;
    }
    QPushButton:pressed, QToolButton:pressed, QToolButton:checked {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #C8D8EC, stop:1 #E3ECF7);
        border: 1px solid #4A73A2;
        padding-top: 3px;
        padding-bottom: 1px;
    }
    QPushButton:disabled, QToolButton:disabled {
        background: #E8EBF0;
        border: 1px solid #C2C8D1;
        color: #8A929E;
    }

    QPushButton#primaryButton {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #F2FBF0, stop:0.45 #D6F0D2, stop:0.5 #BEE7B8, stop:1 #A8DAA1);
        border: 1px solid #4D8A46;
        color: #133910;
        font-weight: bold;
    }
    QPushButton#primaryButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #F7FDF6, stop:0.45 #DFF5DC, stop:0.5 #C9ECC4, stop:1 #B2E1AA);
        border: 1px solid #3B7634;
    }
    QPushButton#primaryButton:pressed {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #A2D39B, stop:1 #CCE9C8);
        border: 1px solid #356B2E;
    }
    QPushButton#primaryButton:disabled {
        background: #E4ECE3;
        border: 1px solid #B7C6B6;
        color: #7D8C7C;
        font-weight: normal;
    }

    QPushButton#dangerButton:enabled {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #FDF4F4, stop:0.45 #F8E0E0, stop:0.5 #F2CECE, stop:1 #EBBDBD);
        border: 1px solid #A86464;
        color: #521818;
    }
    QPushButton#dangerButton:hover:enabled {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #FFF7F7, stop:0.45 #FCE6E6, stop:0.5 #F5D2D2, stop:1 #EDBDBD);
        border: 1px solid #964242;
    }

    QPushButton#compactButton {
        padding: 1px 6px;
        min-height: 17px;
    }

    /* Etched Classic Group Boxes */
    QGroupBox {
        background-color: #F4F6F9;
        border: 1px solid #B5BECA;
        border-radius: 2px;
        margin-top: 8px;
        padding: 8px 7px 6px 7px;
        font-weight: bold;
        color: #1E395B;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 8px;
        padding: 0 4px;
        background-color: #ECEFF4;
        color: #1E395B;
    }

    /* Sunken Compact Inputs */
    QLineEdit, QComboBox, QSpinBox, QDateTimeEdit {
        background-color: #FFFFFF;
        border: 1px solid #9AA6B6;
        border-top-color: #7E8B9C;
        border-radius: 2px;
        padding: 1px 4px;
        min-height: 19px;
        max-height: 22px;
        selection-background-color: #3399FF;
        selection-color: #FFFFFF;
    }
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateTimeEdit:focus {
        border: 1px solid #4A85C5;
    }
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDateTimeEdit:disabled {
        background-color: #ECEFF3;
        color: #7C8490;
        border-color: #C2C8D1;
    }

    QComboBox::drop-down, QDateTimeEdit::drop-down {
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 17px;
        border-left: 1px solid #B6C0CE;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #F9FBFD, stop:1 #DCE3EE);
    }
    QComboBox QAbstractItemView {
        background-color: #FFFFFF;
        color: #1A1E24;
        border: 1px solid #7E8B9C;
        selection-background-color: #CFE2FA;
        selection-color: #000000;
        outline: 0;
    }
    QComboBox QAbstractItemView::item {
        min-height: 20px;
        padding: 2px 6px;
        background-color: #FFFFFF;
        color: #1A1E24;
    }
    QComboBox QAbstractItemView::item:hover,
    QComboBox QAbstractItemView::item:selected {
        background-color: #CFE2FA;
        color: #000000;
    }

    /* Classic Calendar Popup */
    QCalendarWidget QWidget {
        background-color: #F4F6F9;
        color: #1A1E24;
    }
    QCalendarWidget QAbstractItemView:enabled {
        background-color: #FFFFFF;
        color: #1A1E24;
        selection-background-color: #CFE2FA;
        selection-color: #000000;
    }
    QCalendarWidget QWidget#qt_calendar_navigationbar {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #F5F7FA, stop:1 #DCE3EE);
        border-bottom: 1px solid #B5BECA;
    }
    QCalendarWidget QToolButton {
        color: #1A1E24;
        background: transparent;
        border: 1px solid transparent;
        padding: 2px 6px;
    }
    QCalendarWidget QToolButton:hover {
        background: #DCEBFC;
        border: 1px solid #7DA2CE;
    }

    /* Classic Pale-Yellow Tooltips */
    QToolTip {
        background-color: #FFFFE1;
        color: #1A1E24;
        border: 1px solid #767676;
        padding: 2px 5px;
    }

    QCheckBox, QRadioButton {
        spacing: 4px;
        color: #1A1E24;
    }

    /* Dense Classic Data Grid */
    QTableView {
        background-color: #FFFFFF;
        alternate-background-color: #F4F7FB;
        gridline-color: #D4DAE3;
        border: 1px solid #9AA6B6;
        selection-background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #DCEBFC, stop:1 #C1DBFC);
        selection-color: #000000;
        outline: 0;
    }
    QTableView::item {
        padding: 0px 4px;
    }
    QTableView::item:selected {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #DCEBFC, stop:1 #C1DBFC);
        color: #000000;
    }

    QHeaderView::section {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #F7F9FC, stop:0.48 #EAEFF6, stop:1 #DCE2EC);
        border: none;
        border-right: 1px solid #C2C9D4;
        border-bottom: 1px solid #A4AEBE;
        padding: 2px 6px;
        min-height: 20px;
        font-weight: bold;
        color: #1E293B;
    }
    QHeaderView::section:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #F3F8FE, stop:1 #CFE2FA);
    }

    /* Classic Tabs */
    QTabWidget::pane {
        border: 1px solid #9AA6B6;
        background-color: #F5F7FA;
        top: -1px;
    }
    QTabBar::tab {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #F3F5F9, stop:1 #DCE1EA);
        border: 1px solid #9AA6B6;
        border-bottom-color: #9AA6B6;
        border-top-left-radius: 2px;
        border-top-right-radius: 2px;
        padding: 3px 10px;
        margin-right: 2px;
        color: #2A313C;
    }
    QTabBar::tab:selected {
        background: #F5F7FA;
        border-bottom-color: #F5F7FA;
        font-weight: bold;
        color: #142842;
    }
    QTabBar::tab:hover:!selected {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #F6FAFF, stop:1 #DCEBFC);
    }

    /* Monospace Log Console */
    QPlainTextEdit#logConsole {
        background-color: #FFFFFF;
        border: 1px solid #9AA6B6;
        font-family: "Consolas", "Courier New", monospace;
        font-size: 8.5pt;
        color: #1A1E24;
    }

    /* Classic Scrollbars */
    QScrollBar:vertical {
        background: #EEF1F6;
        width: 14px;
        border-left: 1px solid #C8CFD9;
        margin: 0px;
    }
    QScrollBar::handle:vertical {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #E4E9F1, stop:1 #C9D2DF);
        border: 1px solid #9AA6B6;
        border-radius: 2px;
        min-height: 22px;
        margin: 1px;
    }
    QScrollBar::handle:vertical:hover {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #D4E4F7, stop:1 #B0CCE9);
        border-color: #6B94C2;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar:horizontal {
        background: #EEF1F6;
        height: 14px;
        border-top: 1px solid #C8CFD9;
        margin: 0px;
    }
    QScrollBar::handle:horizontal {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #E4E9F1, stop:1 #C9D2DF);
        border: 1px solid #9AA6B6;
        border-radius: 2px;
        min-width: 22px;
        margin: 1px;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
    }

    /* Splitter Handle */
    QSplitter::handle {
        background-color: #DCE1EA;
        border-top: 1px solid #C4CBD6;
        border-bottom: 1px solid #C4CBD6;
        height: 4px;
    }

    /* Recessed Multi-Cell Status Bar */
    QStatusBar {
        background-color: #E4E8EF;
        border-top: 1px solid #A4AEBE;
        padding: 1px;
    }
    QStatusBar::item {
        border: none;
    }
    QFrame#statusCell {
        background-color: #F4F6F9;
        border: 1px solid #B5BECA;
        border-top-color: #97A2B1;
        border-left-color: #97A2B1;
        border-radius: 1px;
        padding: 0px 4px;
    }
    QLabel#anchorBanner {
        background-color: #FFFFFF;
        border: 1px solid #B5BECA;
        border-radius: 2px;
        padding: 1px 5px;
        font-family: "Consolas", "Courier New", monospace;
        font-size: 8pt;
        color: #1F3552;
    }
    QProgressBar#globalProgress {
        border: 1px solid #8E9BAE;
        background-color: #FFFFFF;
        text-align: center;
        font-size: 7.5pt;
        max-height: 15px;
    }
    QProgressBar#globalProgress::chunk {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #8AE87D, stop:0.49 #34C22C, stop:0.5 #20AE19, stop:1 #4ED446);
    }
    """


def render_app_icon_pixmap(size: int) -> QPixmap:
    """Paint a single-resolution early-2010s glossy blue-steel desktop icon pixmap."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    margin = max(1.0, size * 0.055)
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    radius = max(2.0, size * 0.16)

    # Outer glossy blue-steel tile
    bg_grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    bg_grad.setColorAt(0.0, QColor("#69A4E8"))
    bg_grad.setColorAt(0.46, QColor("#2D66AF"))
    bg_grad.setColorAt(0.52, QColor("#1F5296"))
    bg_grad.setColorAt(1.0, QColor("#133363"))

    painter.setBrush(bg_grad)
    painter.setPen(QPen(QColor("#0E2444"), max(1.0, size * 0.035)))
    painter.drawRoundedRect(rect, radius, radius)

    # Subtle inner rim highlight
    inner_rect = rect.adjusted(
        max(1.0, size * 0.025),
        max(1.0, size * 0.025),
        -max(1.0, size * 0.025),
        -max(1.0, size * 0.025),
    )
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(255, 255, 255, 70), max(0.75, size * 0.02)))
    painter.drawRoundedRect(inner_rect, max(1.5, radius * 0.85), max(1.5, radius * 0.85))

    # Glossy top specular sheen
    gloss_rect = QRectF(
        inner_rect.left() + size * 0.01,
        inner_rect.top() + size * 0.01,
        inner_rect.width() - size * 0.02,
        inner_rect.height() * 0.42,
    )
    gloss_grad = QLinearGradient(gloss_rect.topLeft(), gloss_rect.bottomLeft())
    gloss_grad.setColorAt(0.0, QColor(255, 255, 255, 130))
    gloss_grad.setColorAt(1.0, QColor(255, 255, 255, 16))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gloss_grad)
    painter.drawRoundedRect(gloss_rect, max(1.2, radius * 0.65), max(1.2, radius * 0.65))

    # Download arrow geometry (slightly left-balanced for the bookmark ribbon)
    cx = size * 0.47
    arrow = QPainterPath()
    stem_w = size * 0.19
    head_w = size * 0.48
    top_y = size * 0.21
    mid_y = size * 0.50
    tip_y = size * 0.73

    arrow.moveTo(cx - stem_w * 0.5, top_y)
    arrow.lineTo(cx + stem_w * 0.5, top_y)
    arrow.lineTo(cx + stem_w * 0.5, mid_y)
    arrow.lineTo(cx + head_w * 0.5, mid_y)
    arrow.lineTo(cx, tip_y)
    arrow.lineTo(cx - head_w * 0.5, mid_y)
    arrow.lineTo(cx - stem_w * 0.5, mid_y)
    arrow.closeSubpath()

    # Soft drop shadow behind arrow
    painter.save()
    painter.translate(0, max(0.8, size * 0.03))
    painter.setBrush(QColor(8, 22, 46, 115))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawPath(arrow)
    painter.restore()

    # Glossy white-silver download arrow
    arrow_grad = QLinearGradient(QPointF(cx, top_y), QPointF(cx, tip_y))
    arrow_grad.setColorAt(0.0, QColor("#FFFFFF"))
    arrow_grad.setColorAt(1.0, QColor("#DCE8F7"))
    painter.setBrush(arrow_grad)
    painter.setPen(QPen(QColor("#0F2B52"), max(0.8, size * 0.024)))
    painter.drawPath(arrow)

    # Bottom tray bar
    tray_y = size * 0.78
    tray_h = max(1.6, size * 0.085)
    tray_rect = QRectF(size * 0.20, tray_y, size * 0.54, tray_h)
    painter.setBrush(QColor("#E3EFFB"))
    painter.setPen(QPen(QColor("#0F2B52"), max(0.6, size * 0.018)))
    painter.drawRoundedRect(tray_rect, max(0.8, size * 0.025), max(0.8, size * 0.025))

    # Golden notched bookmark ribbon in upper-right corner
    rib_x = size * 0.67
    rib_y = rect.top() + max(0.5, size * 0.015)
    rib_w = size * 0.20
    rib_h = size * 0.34
    notch_y = rib_y + rib_h - size * 0.09

    ribbon = QPainterPath()
    ribbon.moveTo(rib_x, rib_y)
    ribbon.lineTo(rib_x + rib_w, rib_y)
    ribbon.lineTo(rib_x + rib_w, rib_y + rib_h)
    ribbon.lineTo(rib_x + rib_w * 0.5, notch_y)
    ribbon.lineTo(rib_x, rib_y + rib_h)
    ribbon.closeSubpath()

    rib_grad = QLinearGradient(QPointF(rib_x, rib_y), QPointF(rib_x, rib_y + rib_h))
    rib_grad.setColorAt(0.0, QColor("#FFE38A"))
    rib_grad.setColorAt(0.5, QColor("#F5B82E"))
    rib_grad.setColorAt(1.0, QColor("#C9830F"))

    painter.setBrush(rib_grad)
    painter.setPen(QPen(QColor("#6E4406"), max(0.7, size * 0.02)))
    painter.drawPath(ribbon)

    painter.end()
    return pixmap


def save_app_icon_ico(
    dest_path: Path,
    sizes: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256),
) -> Path:
    """Write a multi-resolution Windows .ico file (PNG-compressed frames)."""
    target = Path(dest_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    frames: list[tuple[int, bytes]] = []
    for size in sizes:
        pixmap = render_app_icon_pixmap(size)
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buf, "PNG")
        frames.append((size, bytes(buf.data())))
        buf.close()

    # Standard ICO header (6 bytes) + directory entries (16 bytes each)
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    dir_entries = bytearray()
    payload = bytearray()

    for size, png_bytes in frames:
        dim = 0 if size >= 256 else size
        dir_entries.extend(
            struct.pack(
                "<BBBBHHII",
                dim,
                dim,
                0,  # color count
                0,  # reserved
                1,  # planes
                32,  # bits per pixel
                len(png_bytes),
                offset,
            )
        )
        payload.extend(png_bytes)
        offset += len(png_bytes)

    target.write_bytes(header + bytes(dir_entries) + bytes(payload))
    return target


def create_classic_palette() -> QPalette:
    """Build an explicit light classic Windows 7 palette immune to OS dark-mode overrides."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#ECEFF4"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#1A1E24"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#F4F7FB"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#FFFFE1"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#1A1E24"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#1A1E24"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#E4E9F2"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#1A1E24"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#CFE2FA"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#000000"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#1C5AA6"))
    palette.setColor(QPalette.ColorRole.Mid, QColor("#B5BECA"))
    palette.setColor(QPalette.ColorRole.Dark, QColor("#8E9BAE"))
    palette.setColor(QPalette.ColorRole.Light, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#7A828E"))

    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#8A929E"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#8A929E"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#8A929E"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor("#ECEFF3"))
    return palette


def apply_classic_theme(app) -> QIcon:
    """Apply Fusion style, light color scheme, classic palette, QSS, and app icon."""
    app.setStyle("Fusion")
    try:
        hints = app.styleHints()
        if hasattr(hints, "setColorScheme") and hasattr(Qt, "ColorScheme"):
            hints.setColorScheme(Qt.ColorScheme.Light)
    except Exception:
        pass
    app.setPalette(create_classic_palette())
    app.setStyleSheet(get_classic_stylesheet())
    icon = create_app_icon()
    app.setWindowIcon(icon)
    return icon


def create_app_icon() -> QIcon:
    """Load assets/app.ico if present, or paint the classic early-2010s app icon."""
    ico_path = Path(__file__).resolve().parent.parent.parent / "assets" / "app.ico"
    if ico_path.is_file():
        icon = QIcon(str(ico_path))
        if not icon.isNull():
            return icon

    icon = QIcon()
    for size in (16, 24, 32, 48, 64):
        icon.addPixmap(render_app_icon_pixmap(size))
    return icon
