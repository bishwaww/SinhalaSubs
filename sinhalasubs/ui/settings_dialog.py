"""Settings window: Gemini API key, model and transcription options."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout)

from ..config import Settings
from .workers import Task

AUTO = "Automatic (newest Flash)"


def _fetch_models(key: str, log, cancelled):
    from ..transcribe import TranscribeOptions, list_models, make_client
    return list_models(make_client(TranscribeOptions(api_key=key)))


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)
        self.settings = settings
        self._task: Task | None = None

        # API key -----------------------------------------------------------------
        self.key = QLineEdit(settings.api_key)
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Paste your Gemini API key (starts with AIza…)")
        show = QPushButton("Show")
        show.setCheckable(True)
        show.toggled.connect(lambda on: (self.key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
                                         show.setText("Hide" if on else "Show")))
        self.test_btn = QPushButton("Test key")
        self.test_btn.clicked.connect(self.test_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key, 1)
        key_row.addWidget(show)
        key_row.addWidget(self.test_btn)
        link = QLabel('Get a free key at <a href="https://aistudio.google.com/apikey" '
                      'style="color:#E8A33D">aistudio.google.com/apikey</a>. '
                      "It is saved encrypted on this PC only.")
        link.setObjectName("Muted")
        link.setOpenExternalLinks(True)
        link.setWordWrap(True)
        self.key_status = QLabel("")
        self.key_status.setObjectName("Muted")

        # Transcription -----------------------------------------------------------
        from .. import whisper_engine

        self.engine = QComboBox()
        self.engine.addItem("Gemini – online, best Sinhala (needs the key)", "gemini")
        self.engine.addItem("Whisper – offline, free, exact word times", "whisper")
        self.engine.setCurrentIndex(max(0, self.engine.findData(settings.engine)))
        self.whisper = QComboBox()
        for key, label in whisper_engine.MODELS.items():
            done = " ✓ downloaded" if whisper_engine.is_downloaded(key) else ""
            self.whisper.addItem(label + done, key)
        self.whisper.setCurrentIndex(max(0, self.whisper.findData(settings.whisper_model)))
        self.engine.currentIndexChanged.connect(
            lambda: self.whisper.setEnabled(self.engine.currentData() == "whisper"))
        self.whisper.setEnabled(settings.engine == "whisper")
        if not whisper_engine.is_installed():
            self.engine.model().item(1).setEnabled(False)
        self.model = QComboBox()
        self.model.addItem(AUTO, "")
        if settings.model:
            self.model.addItem(settings.model, settings.model)
            self.model.setCurrentIndex(1)
        self.english = QComboBox()
        self.english.addItem("English letters  (අලුත් layer එකක්)", "english")
        self.english.addItem("Sinhala letters  (අලුත් ලේයර් එකක්)", "sinhala")
        self.english.setCurrentIndex(0 if settings.english_mode == "english" else 1)
        self.max_chars = QSpinBox(minimum=10, maximum=120, value=settings.max_chars)
        self.chunk = QDoubleSpinBox(minimum=15, maximum=300, value=settings.chunk_len, suffix=" s", decimals=0)
        self.workers = QSpinBox(minimum=1, maximum=8, value=settings.workers)
        self.polish = QCheckBox("Second Gemini pass to fix wrong letters and English words")
        self.polish.setChecked(settings.polish)
        self.glossary = QPlainTextEdit("\n".join(settings.glossary))
        self.glossary.setPlaceholderText("One per line: names and words Gemini must spell exactly\n"
                                         "e.g. කසුන්\nPhotoshop")
        self.glossary.setFixedHeight(80)

        # CapCut ----------------------------------------------------------------------
        self.drafts = QLineEdit(settings.drafts_root)
        self.drafts.setPlaceholderText("Automatic")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.choose_drafts)
        drafts_row = QHBoxLayout()
        drafts_row.addWidget(self.drafts, 1)
        drafts_row.addWidget(browse)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.addRow("Gemini API key", key_row)
        form.addRow("", link)
        form.addRow("", self.key_status)
        form.addRow("Speech engine", self.engine)
        form.addRow("Whisper model", self.whisper)
        form.addRow("Gemini model", self.model)
        form.addRow("English words", self.english)
        form.addRow("Max characters", self.max_chars)
        form.addRow("Audio per request", self.chunk)
        form.addRow("Parallel requests", self.workers)
        form.addRow("", self.polish)
        form.addRow("Glossary", self.glossary)
        form.addRow("CapCut drafts folder", drafts_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

    def choose_drafts(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "CapCut drafts folder", self.drafts.text())
        if folder:
            self.drafts.setText(folder)

    def test_key(self) -> None:
        if not self.key.text().strip():
            self.key_status.setText("Paste a key first.")
            return
        self.test_btn.setEnabled(False)
        self.key_status.setText("Checking…")
        self._task = Task(_fetch_models, self.key.text().strip(), parent=self)
        self._task.succeeded.connect(self._got_models)
        self._task.failed.connect(lambda msg: (self.key_status.setText(f"✗ {msg[:160]}"),
                                               self.test_btn.setEnabled(True)))
        self._task.start()

    def _got_models(self, names: list[str]) -> None:
        from ..transcribe import pick_model

        self.test_btn.setEnabled(True)
        current = self.model.currentData()
        self.model.clear()
        self.model.addItem(f"{AUTO} → {pick_model(names)}" if names else AUTO, "")
        for n in names:
            self.model.addItem(n, n)
        idx = self.model.findData(current)
        self.model.setCurrentIndex(max(0, idx))
        self.key_status.setText(f"✓ Key works – {len(names)} models available.")

    def done(self, result: int) -> None:
        if self._task and self._task.isRunning():
            self._task.wait(15_000)  # a thread must finish before its dialog is deleted
        super().done(result)

    def accept(self) -> None:
        s = self.settings
        s.api_key = self.key.text()
        s.model = self.model.currentData() or ""
        s.engine = self.engine.currentData()
        s.whisper_model = self.whisper.currentData()
        s.english_mode = self.english.currentData()
        s.max_chars = self.max_chars.value()
        s.chunk_len = self.chunk.value()
        s.workers = self.workers.value()
        s.polish = self.polish.isChecked()
        s.glossary = [w.strip() for w in self.glossary.toPlainText().replace(",", "\n").splitlines() if w.strip()]
        s.drafts_root = self.drafts.text().strip()
        s.save()
        super().accept()
