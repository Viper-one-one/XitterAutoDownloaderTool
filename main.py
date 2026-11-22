"""Application entry point for XitterAutoDownloaderTool."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow
from src.ui.theme import apply_classic_theme


def _configure_windows_taskbar_id() -> None:
    """Assign an explicit AppUserModelID so Windows taskbar uses our app icon."""
    if not sys.platform.startswith("win"):
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "XitterAutoDownloaderTool.BookmarkArchiver.1"
        )
    except Exception:
        pass


def main() -> int:
    """Initialize the Qt desktop application and show the main window."""
    _configure_windows_taskbar_id()

    app = QApplication(sys.argv)
    app.setApplicationName("XitterAutoDownloaderTool")
    app.setApplicationDisplayName("XitterAutoDownloaderTool")
    icon = apply_classic_theme(app)

    window = MainWindow()
    window.setWindowIcon(icon)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
