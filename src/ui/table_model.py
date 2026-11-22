"""High-density bookmark table model, filter proxy, and classic Aero progress delegate."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from src.models import BookmarkItem, ItemStatus

ITEM_ROLE = Qt.ItemDataRole.UserRole + 1

COLUMNS = [
    "#",
    "Post ID",
    "Author",
    "Post Date",
    "Media",
    "Details",
    "Progress",
    "Status",
    "Output File / Summary",
]


class BookmarkTableModel(QAbstractTableModel):
    """Fast model backing the dense bookmark extraction and download grid."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[BookmarkItem] = []
        self._row_by_id: dict[str, int] = {}
        self._mono_font = QFont("Consolas", 8)
        self._bold_font = QFont("Segoe UI", 8, QFont.Weight.Bold)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._items)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(COLUMNS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(COLUMNS):
                return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._items):
            return None
        item = self._items[row]

        if role == ITEM_ROLE:
            return item

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_value(item, col)

        if role == Qt.ItemDataRole.UserRole:
            return self._sort_value(item, col)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (0, 4, 5, 6):
                return int(Qt.AlignmentFlag.AlignCenter)
            return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        if role == Qt.ItemDataRole.FontRole:
            if col in (1, 3):
                return self._mono_font
            if col == 7 and item.status in (
                ItemStatus.DOWNLOADING,
                ItemStatus.MERGING,
                ItemStatus.COMPLETE,
                ItemStatus.FAILED,
            ):
                return self._bold_font
            return None

        if role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground_color(item, col)

        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip_text(item)

        return None

    def _display_value(self, item: BookmarkItem, col: int) -> str:
        if col == 0:
            return str(item.index)
        if col == 1:
            return item.tweet_id
        if col == 2:
            return f"@{item.author_handle}"
        if col == 3:
            if item.created_at is None:
                return "--"
            return item.created_at.astimezone().strftime("%Y-%m-%d %H:%M")
        if col == 4:
            return item.media_type.value
        if col == 5:
            return item.details_summary
        if col == 6:
            if item.status in (ItemStatus.SKIPPED_NO_VIDEO, ItemStatus.SKIPPED_OUT_OF_RANGE):
                return "--"
            if item.status == ItemStatus.DOWNLOADING and item.speed_text:
                return f"{item.progress:.0f}% ({item.speed_text})"
            return f"{item.progress:.0f}%"
        if col == 7:
            return item.status.value
        if col == 8:
            if item.saved_filepath:
                return Path(item.saved_filepath).name
            if item.error_message:
                return item.error_message
            snippet = (item.text or "").replace("\n", " ").strip()
            return snippet[:95] + ("..." if len(snippet) > 95 else "")
        return ""

    def _sort_value(self, item: BookmarkItem, col: int) -> Any:
        if col == 0:
            return item.index
        if col == 1:
            return int(item.tweet_id) if item.tweet_id.isdigit() else item.tweet_id
        if col == 2:
            return item.author_handle.lower()
        if col == 3:
            return item.created_at.timestamp() if item.created_at else 0.0
        if col == 4:
            return item.media_type.value
        if col == 5:
            return item.duration_seconds if item.duration_seconds is not None else -1.0
        if col == 6:
            if item.status in (ItemStatus.SKIPPED_NO_VIDEO, ItemStatus.SKIPPED_OUT_OF_RANGE):
                return -1.0
            return item.progress
        if col == 7:
            return item.status.value
        if col == 8:
            return self._display_value(item, 8).lower()
        return ""

    def _foreground_color(self, item: BookmarkItem, col: int) -> Optional[QColor]:
        if item.status in (ItemStatus.SKIPPED_NO_VIDEO, ItemStatus.SKIPPED_OUT_OF_RANGE):
            return QColor("#7A828E")
        if col == 7:
            if item.status == ItemStatus.COMPLETE:
                return QColor("#186B14")
            if item.status in (ItemStatus.DOWNLOADING, ItemStatus.MERGING):
                return QColor("#184D8C")
            if item.status == ItemStatus.SKIPPED_ARCHIVE:
                return QColor("#3D628C")
            if item.status == ItemStatus.FAILED:
                return QColor("#A61E1E")
            if item.status == ItemStatus.CANCELLED:
                return QColor("#8B5A18")
        return None

    def _tooltip_text(self, item: BookmarkItem) -> str:
        lines = [
            f"Post: {item.url}",
            f"Author: {item.author_name} (@{item.author_handle})" if item.author_name else f"Author: @{item.author_handle}",
            f"Media: {item.media_type.value} ({item.details_summary})",
            f"Status: {item.status.value}",
        ]
        if item.saved_filepath:
            lines.append(f"Saved: {item.saved_filepath}")
        if item.error_message:
            lines.append(f"Error: {item.error_message}")
        if item.text:
            snippet = item.text.strip().replace("\n", " ")
            lines.append(f"Text: {snippet[:180]}")
        return "\n".join(lines)

    def add_or_update_item(self, item: BookmarkItem) -> None:
        """Insert a new BookmarkItem or update it in place if its tweet_id already exists."""
        existing_row = self._row_by_id.get(item.tweet_id)
        if existing_row is not None:
            self._items[existing_row] = item
            left = self.index(existing_row, 0)
            right = self.index(existing_row, len(COLUMNS) - 1)
            self.dataChanged.emit(left, right)
            return

        new_row = len(self._items)
        self.beginInsertRows(QModelIndex(), new_row, new_row)
        self._items.append(item)
        self._row_by_id[item.tweet_id] = new_row
        self.endInsertRows()

    def update_item(self, item: BookmarkItem) -> None:
        """Refresh the row corresponding to an updated BookmarkItem."""
        row = self._row_by_id.get(item.tweet_id)
        if row is None:
            self.add_or_update_item(item)
            return
        self._items[row] = item
        left = self.index(row, 0)
        right = self.index(row, len(COLUMNS) - 1)
        self.dataChanged.emit(left, right)

    def clear_all(self) -> None:
        """Remove all rows from the table model."""
        if not self._items:
            return
        self.beginResetModel()
        self._items.clear()
        self._row_by_id.clear()
        self.endResetModel()

    def clear_completed_and_skipped(self) -> None:
        """Remove completed, archived, and skipped rows while keeping active/failed items."""
        keep_statuses = {
            ItemStatus.QUEUED,
            ItemStatus.DOWNLOADING,
            ItemStatus.MERGING,
            ItemStatus.FAILED,
        }
        remaining = [it for it in self._items if it.status in keep_statuses]
        if len(remaining) == len(self._items):
            return
        self.beginResetModel()
        self._items = remaining
        self._row_by_id = {it.tweet_id: idx for idx, it in enumerate(self._items)}
        self.endResetModel()

    def get_item(self, row: int) -> Optional[BookmarkItem]:
        """Return the BookmarkItem at a given source row index."""
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def all_items(self) -> list[BookmarkItem]:
        """Return a shallow copy of all items currently stored in the model."""
        return list(self._items)


class BookmarkFilterProxyModel(QSortFilterProxyModel):
    """Supports hiding skipped rows and instant text filtering without mutating source rows."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._hide_skipped = False
        self._search_text = ""
        self.setSortRole(Qt.ItemDataRole.UserRole)

    def set_hide_skipped(self, hide: bool) -> None:
        if self._hide_skipped != hide:
            self._hide_skipped = hide
            self.invalidateFilter()

    def set_search_text(self, text: str) -> None:
        cleaned = text.strip().lower()
        if self._search_text != cleaned:
            self._search_text = cleaned
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if not isinstance(model, BookmarkTableModel):
            return True
        item = model.get_item(source_row)
        if item is None:
            return False

        if self._hide_skipped and item.status in (
            ItemStatus.SKIPPED_NO_VIDEO,
            ItemStatus.SKIPPED_OUT_OF_RANGE,
        ):
            return False

        if self._search_text:
            haystack = " ".join(
                [
                    item.tweet_id,
                    item.author_handle,
                    item.author_name,
                    item.media_type.value,
                    item.status.value,
                    item.text,
                    item.saved_filepath,
                ]
            ).lower()
            if self._search_text not in haystack:
                return False

        return True


class ProgressBarDelegate(QStyledItemDelegate):
    """Paints a crisp early-2010s glossy progress bar inside the Progress column."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        item: Optional[BookmarkItem] = index.data(ITEM_ROLE)
        if item is None:
            super().paint(painter, option, index)
            return

        # Let Qt draw standard row background / selection highlight first
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else None
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        painter.save()
        if item.status in (ItemStatus.SKIPPED_NO_VIDEO, ItemStatus.SKIPPED_OUT_OF_RANGE):
            painter.setPen(QColor("#8A929E"))
            painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, "--")
            painter.restore()
            return

        bar_rect = QRectF(option.rect).adjusted(4.0, 3.0, -4.0, -3.0)
        if bar_rect.width() <= 6 or bar_rect.height() <= 6:
            painter.restore()
            return

        # Sunken white track
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(QPen(QColor("#8C96A4"), 1.0))
        painter.drawRect(bar_rect)

        pct = max(0.0, min(100.0, float(item.progress)))
        if item.status == ItemStatus.MERGING:
            pct = 100.0
        elif item.status == ItemStatus.SKIPPED_ARCHIVE:
            pct = 100.0

        inner = bar_rect.adjusted(1.0, 1.0, -1.0, -1.0)
        fill_w = inner.width() * (pct / 100.0)
        if fill_w >= 1.0:
            fill_rect = QRectF(inner.left(), inner.top(), fill_w, inner.height())
            grad = QLinearGradient(fill_rect.topLeft(), fill_rect.bottomLeft())
            if item.status == ItemStatus.MERGING:
                grad.setColorAt(0.0, QColor("#FCE39C"))
                grad.setColorAt(0.49, QColor("#EAB844"))
                grad.setColorAt(0.5, QColor("#D69C24"))
                grad.setColorAt(1.0, QColor("#F0C55E"))
            elif item.status == ItemStatus.SKIPPED_ARCHIVE:
                grad.setColorAt(0.0, QColor("#DAE8F7"))
                grad.setColorAt(0.49, QColor("#AFCBEC"))
                grad.setColorAt(0.5, QColor("#92B7E1"))
                grad.setColorAt(1.0, QColor("#BED7F2"))
            elif item.status in (ItemStatus.FAILED, ItemStatus.CANCELLED):
                grad.setColorAt(0.0, QColor("#FAD4D4"))
                grad.setColorAt(0.49, QColor("#E38C8C"))
                grad.setColorAt(0.5, QColor("#CF6D6D"))
                grad.setColorAt(1.0, QColor("#E89B9B"))
            else:
                grad.setColorAt(0.0, QColor("#90EC83"))
                grad.setColorAt(0.49, QColor("#3CC933"))
                grad.setColorAt(0.5, QColor("#22B31B"))
                grad.setColorAt(1.0, QColor("#53D84A"))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(grad)
            painter.drawRect(fill_rect)

        # Label text
        if item.status == ItemStatus.DOWNLOADING:
            label = f"{pct:.0f}% {item.speed_text}".strip()
        elif item.status == ItemStatus.MERGING:
            label = "Merging..."
        elif item.status == ItemStatus.COMPLETE:
            label = "100%"
        elif item.status == ItemStatus.SKIPPED_ARCHIVE:
            label = "Archived"
        elif item.status == ItemStatus.QUEUED:
            label = "Queued"
        elif item.status == ItemStatus.FAILED:
            label = "Failed"
        elif item.status == ItemStatus.CANCELLED:
            label = "Stopped"
        else:
            label = f"{pct:.0f}%"

        font = QFont(option.font)
        font.setPointSizeF(7.8)
        painter.setFont(font)
        painter.setPen(QColor("#11161D"))
        painter.drawText(bar_rect, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()
