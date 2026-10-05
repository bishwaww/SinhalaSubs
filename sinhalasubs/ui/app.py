"""Start the desktop app."""

from __future__ import annotations

import sys


def apply_theme(app) -> None:
    from PySide6.QtGui import QFont

    from .theme import STYLESHEET

    # Segoe UI has no Sinhala letters; Nirmala UI (in Windows 10/11) does. Qt tries the
    # families in order for every letter, so English uses Segoe UI and Sinhala Nirmala UI.
    font = QFont()
    font.setFamilies(["Segoe UI", "Nirmala UI", "Iskoola Pota", "Segoe UI Symbol", "Segoe UI Emoji"])
    font.setPointSizeF(10)
    app.setFont(font)
    app.setStyleSheet(STYLESHEET)


def run() -> int:
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    from pathlib import Path

    from PySide6.QtGui import QIcon

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("SinhalaSubs")
    app.setWindowIcon(QIcon(str(Path(__file__).parent.parent / "data" / "icon.ico")))
    if sys.platform == "win32":   # own taskbar icon instead of Python's
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SinhalaSubs.App")
    apply_theme(app)
    window = MainWindow()
    if getattr(window, "start_maximized", False):   # small screen: use all of it
        window.showMaximized()
    else:
        window.show()
    return app.exec()
