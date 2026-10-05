"""About window: version, where files are kept, and the open-source parts we use."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import __version__
from ..config import app_data_dir

CREDITS = [
    ("PySide6 / Qt", "LGPL-3.0", "the window and everything you see"),
    ("FFmpeg (imageio-ffmpeg)", "GPL/LGPL", "reading and cutting audio"),
    ("Google Gen AI SDK", "Apache-2.0", "talking to Gemini"),
    ("faster-whisper, CTranslate2", "MIT", "offline speech recognition"),
    ("Pydantic", "MIT", "checking Gemini's answers"),
    ("FM font rules (UCSC LTRL)", "open source", "Sinhala Unicode → FM letters"),
]


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About SinhalaSubs")
        self.setMinimumWidth(460)

        icon = QLabel()
        icon.setPixmap(QPixmap(str(Path(__file__).parent.parent / "data" / "icon.png"))
                       .scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        title = QLabel(f"<b style='font-size:16pt'>SinhalaSubs</b><br>Version {__version__}")
        head = QHBoxLayout()
        head.addWidget(icon)
        head.addWidget(title, 1)

        text = QLabel(
            "Captions in Sinhala and 23 other languages for CapCut, made with Gemini or Whisper.<br><br>"
            "<b>Built with open-source software:</b><br>"
            + "<br>".join(f"• {name} <span style='color:#9A9FAB'>({lic})</span> – {why}" for name, lic, why in CREDITS)
            + "<br><br><span style='color:#9A9FAB'>Not made by or connected with CapCut or ByteDance.</span>")
        text.setWordWrap(True)
        text.setTextFormat(Qt.RichText)

        folder = QPushButton("Open my SinhalaSubs folder (settings, backups)")
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_data_dir()))))
        close = QPushButton("Close")
        close.setObjectName("Primary")
        close.clicked.connect(self.accept)

        lay = QVBoxLayout(self)
        lay.addLayout(head)
        lay.addWidget(text)
        lay.addWidget(folder)
        lay.addWidget(close, 0, Qt.AlignRight)
