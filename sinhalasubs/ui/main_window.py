"""The main window: projects on the left, preview + timeline + subtitles in the middle, style on the right."""

from __future__ import annotations

import copy
import hashlib
import time
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QByteArray, QItemSelectionModel, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
                               QSplitter, QToolButton, QVBoxLayout, QWidget)

from .. import __version__, timing
from ..capcut.project import Draft, current_timeline, is_capcut_running, list_projects, list_timelines
from ..capcut.writer import list_backups, restore_backup, write_to_draft
from ..config import Settings, load_session, save_session
from ..fm_converter import unicode_to_fm
from ..models import Cue, from_srt, to_srt
from ..pipeline import fill_gaps, prepare_audio, wav_to_cues
from ..sinhala_script import has_foreign
from ..style import SubtitleStyle
from ..waveform import BUCKET, load_peaks
from .cue_table import CueTable, fmt_time
from .preview import PreviewCanvas
from .settings_dialog import SettingsDialog
from .style_panel import StylePanel
from .theme import PANEL_2
from .timeline import TimelineView
from .workers import Task

UNDO_LIMIT = 100


def _panel() -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("Panel")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(8)
    return f, lay


def _label(text: str, name: str = "") -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    return lbl


# --- background jobs (run on a Task thread) -------------------------------------------------------

def _audio_job(source, log, cancelled):
    wav, total = prepare_audio(source, log, cancelled)
    return wav, total, load_peaks(wav, cancelled)


def _generate_job(source, opts, existing, log, cancelled):
    """New subtitles for the whole audio, or (with `existing`) only for the parts without any."""
    wav, total = prepare_audio(source, log, cancelled)
    if existing:
        return fill_gaps(wav, total, existing, opts, log, cancelled)
    return wav_to_cues(wav, total, opts, log, cancelled=cancelled)


def _fix_script_job(cues: list[Cue], opts, log, cancelled) -> list[Cue]:
    from ..transcribe import fix_script, make_client, model_chain

    cues = copy.deepcopy(cues)
    client, model = None, ""
    if opts.polish:
        try:
            client = make_client(opts)
            model = model_chain(client, opts)
        except RuntimeError as e:          # no key: letter mapping only
            log(f"({e} Using letter mapping only.)")
            client = None
    stats = fix_script(cues, client, model, opts, log)
    log(f"Sinhala script accuracy: {stats['purity_before']:.1%} -> {stats['purity_after']:.1%}")
    return cues


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"SinhalaSubs {__version__}")
        self.settings = Settings.load()
        try:
            self.style_ = SubtitleStyle(**self.settings.style)
        except TypeError:
            self.style_ = SubtitleStyle()
        self.task: Task | None = None          # generate / fix script
        self.audio_task: Task | None = None    # preparing the waveform + playback audio
        self.draft: Draft | None = None
        self.project = None                    # ProjectInfo of the chosen CapCut project
        self.video: Path | None = None
        self.wav: Path | None = None
        self.session_key = ""
        self._undo: list[list[Cue]] = []
        self._redo: list[list[Cue]] = []
        self._syncing = False
        self._save_timer = QTimer(self, singleShot=True, interval=800, timeout=self._save_session)
        self._build_player()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_right())
        splitter.setSizes([290, 800, 330])
        splitter.setChildrenCollapsible(False)
        root = QWidget()
        lay = QHBoxLayout(root)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addWidget(splitter)
        self.setCentralWidget(root)
        self._build_shortcuts()

        self._restore_window()
        self.refresh_projects()
        self._update_buttons()
        if not self.settings.api_key:
            self.log("👋 Welcome! Open Settings (⚙) and paste your Gemini API key to start.")

    # --- window size ----------------------------------------------------------------------------

    def _restore_window(self) -> None:
        """Last size and place if it still fits a screen; otherwise as big as the screen allows."""
        if self.settings.window and self.restoreGeometry(QByteArray.fromBase64(self.settings.window.encode())):
            return
        self.fit_to_screen()

    def fit_to_screen(self) -> None:
        avail = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        # leave room for the window's title bar and border (they are outside the size we set)
        w, h = min(1440, avail.width() - 40), min(900, avail.height() - 60)
        self.resize(max(w, 800), max(h, 500))
        self.move(avail.center() - self.rect().center())
        self.start_maximized = avail.height() < 900

    # --- layout ---------------------------------------------------------------------------------

    def _build_left(self) -> QWidget:
        panel, lay = _panel()
        head = QHBoxLayout()
        head.addWidget(_label("SinhalaSubs", "Title"), 1)
        refresh = QToolButton(text="⟳", toolTip="Reload the CapCut project list")
        refresh.clicked.connect(self.refresh_projects)
        gear = QToolButton(text="⚙", toolTip="Settings (Gemini API key, model…)")
        gear.clicked.connect(self.open_settings)
        about = QToolButton(text="ⓘ", toolTip="About SinhalaSubs")
        about.clicked.connect(lambda: __import__("sinhalasubs.ui.about_dialog", fromlist=["AboutDialog"])
                              .AboutDialog(self).exec())
        head.addWidget(refresh)
        head.addWidget(gear)
        head.addWidget(about)
        lay.addLayout(head)

        lay.addWidget(_label("CAPCUT PROJECTS", "Section"))
        self.search = QLineEdit(placeholderText="Search projects…")
        self.search.textChanged.connect(self._filter_projects)
        lay.addWidget(self.search)
        self.projects = QListWidget()
        self.projects.setIconSize(QSize(56, 56))
        self.projects.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.projects.setWordWrap(True)
        self.projects.currentItemChanged.connect(self._project_chosen)
        lay.addWidget(self.projects, 1)

        self.timeline_box = QComboBox()
        self.timeline_box.currentIndexChanged.connect(self._timeline_chosen)
        self.track = QComboBox()
        self.track.setToolTip("The track with the speech")
        self.track.currentIndexChanged.connect(self._track_chosen)
        lay.addWidget(_label("Timeline"))
        lay.addWidget(self.timeline_box)
        lay.addWidget(_label("Speech track"))
        lay.addWidget(self.track)

        video_btn = QPushButton("…or open a video file")
        video_btn.clicked.connect(self.open_video)
        lay.addWidget(video_btn)

        self.source_label = _label("No project chosen", "Muted")
        self.source_label.setWordWrap(True)
        self.close_video_btn = QToolButton(text="✕", toolTip="Close this video (its subtitles stay saved)")
        self.close_video_btn.clicked.connect(self.close_video)
        src_row = QHBoxLayout()
        src_row.addWidget(self.source_label, 1)
        src_row.addWidget(self.close_video_btn, 0, Qt.AlignTop)
        lay.addLayout(src_row)

        from ..languages import LANGUAGES
        self.language = QComboBox()
        for lang in LANGUAGES:
            label = lang.name if lang.native == lang.name else f"{lang.name} · {lang.native}"
            self.language.addItem(label, lang.code)
        self.language.setCurrentIndex(max(0, self.language.findData(self.settings.language)))
        self.language.setToolTip("The language spoken in the video")
        self.language.currentIndexChanged.connect(self._language_chosen)
        lay.addWidget(_label("Spoken language"))
        lay.addWidget(self.language)

        self.generate_btn = QPushButton("✨ Generate captions")
        self.generate_btn.setObjectName("Primary")
        self.generate_btn.clicked.connect(self.generate)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_task)
        self.progress = QProgressBar()
        lay.addWidget(self.generate_btn)
        lay.addWidget(self.cancel_btn)
        lay.addWidget(self.progress)
        return panel

    def _build_center(self) -> QWidget:
        panel, lay = _panel()
        self.preview = PreviewCanvas()
        self.preview.set_style(self.style_)
        self.preview.setToolTip("Drag the subtitle to move it · drag a corner or use the wheel to resize")
        self.preview.style_dragged.connect(self._style_dragged)

        # transport: play, time, follow, undo/redo, timing tools
        bar = QHBoxLayout()
        self.play_btn = QPushButton("▶  Play")
        self.play_btn.setToolTip("Play / pause (Ctrl+Space, or Space on the timeline)")
        self.play_btn.clicked.connect(self.toggle_play)
        self.time_label = _label("0:00.00 / 0:00.00", "Muted")
        self.animate_btn = QPushButton("⟲ Animate", checkable=True)
        self.animate_btn.setToolTip("Replay the selected subtitle with its animation while you change the style")
        self.animate_btn.toggled.connect(self.preview_animate)
        self.follow_box = QCheckBox("Follow playhead")
        self.follow_box.setChecked(True)
        self.follow_box.toggled.connect(lambda on: setattr(self.timeline, "follow", on and self.playing()))
        undo = QToolButton(text="↶", toolTip="Undo (Ctrl+Z)")
        undo.clicked.connect(self.undo)
        redo = QToolButton(text="↷", toolTip="Redo (Ctrl+Y)")
        redo.clicked.connect(self.redo)
        tools = QPushButton("Timing ▾")
        menu = QMenu(tools)
        menu.addAction("Fix overlaps", lambda: self._timing_tool(timing.fix_overlaps, "overlaps fixed"))
        menu.addAction("Close gaps shorter than 0.3 s",
                       lambda: self._timing_tool(lambda c: timing.close_gaps(c, 0.3), "gaps closed"))
        menu.addAction("Make every subtitle at least 1 s",
                       lambda: self._timing_tool(lambda c: timing.min_duration(c, 1.0), "subtitles lengthened"))
        menu.addSeparator()
        menu.addAction("Shift all subtitles…", self.shift_all)
        tools.setMenu(menu)
        for w in (self.play_btn, self.animate_btn, self.time_label):
            bar.addWidget(w)
        bar.addStretch(1)
        for w in (self.follow_box, undo, redo, tools):
            bar.addWidget(w)

        self.timeline = TimelineView()
        self.timeline.seek.connect(self.seek)
        self.timeline.selection_changed.connect(self._timeline_selected)
        self.timeline.edit_started.connect(self.checkpoint)
        self.timeline.cues_changing.connect(self._timeline_changing)
        self.timeline.edit_finished.connect(self._cues_edited)

        # subtitle list and its buttons
        list_bar = QHBoxLayout()
        for text, tip, slot in (
            ("+ Add", "Add a subtitle at the playhead", self.add_cue),
            ("Delete", "Delete the selected subtitles (Del)", self.delete_cues),
            ("Merge", "Join the selected subtitles into one", self.merge_cues),
            ("Split", "Cut the selected subtitle at the playhead (or in the middle)", self.split_cue),
            ("Fix script", "Repair Malayalam/Hindi look-alike letters (red rows)", self.fix_script),
        ):
            b = QPushButton(text, toolTip=tip)
            b.clicked.connect(slot)
            list_bar.addWidget(b)
        list_bar.addStretch(1)
        srt_btn = QPushButton("SRT ▾")
        srt_menu = QMenu(srt_btn)
        srt_menu.addAction("Import .srt…", self.import_srt)
        srt_menu.addAction("Export .srt (Unicode)…", lambda: self.export_srt(fm=False))
        srt_menu.addAction("Export .srt (FM font text)…", lambda: self.export_srt(fm=True))
        srt_btn.setMenu(srt_menu)
        list_bar.addWidget(srt_btn)

        self.table = CueTable()
        self.table.model_.about_to_edit.connect(self.checkpoint)
        self.table.model_.edited.connect(self._cues_edited)
        self.table.selectionModel().selectionChanged.connect(self._table_selected)
        self.count_label = _label("", "Muted")
        self.log_box = QPlainTextEdit(readOnly=True)
        self.log_box.setMaximumBlockCount(2000)

        bottom = QWidget()
        b = QVBoxLayout(bottom)
        b.setContentsMargins(0, 0, 0, 0)
        b.addLayout(list_bar)
        b.addWidget(self.table, 1)
        b.addWidget(self.count_label)

        top = QWidget()
        t = QVBoxLayout(top)
        t.setContentsMargins(0, 0, 0, 0)
        t.addWidget(self.preview, 1)
        t.addLayout(bar)

        split = QSplitter(Qt.Vertical)
        for w in (top, self.timeline, bottom, self.log_box):
            split.addWidget(w)
        split.setSizes([330, 150, 260, 80])
        split.setChildrenCollapsible(False)
        lay.addWidget(split)
        return panel

    def _build_right(self) -> QWidget:
        panel, lay = _panel()
        lay.addWidget(_label("Style", "Title"))
        self.style_panel = StylePanel(self.style_)
        self.style_panel.style_changed.connect(self._style_changed)
        self.style_panel.studio_requested.connect(self.open_studio)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.style_panel)
        lay.addWidget(scroll, 1)

        self.captions_box = QCheckBox("Write as CapCut captions")
        self.captions_box.setChecked(self.settings.as_captions)
        self.captions_box.setToolTip(
            "Stored like CapCut's own Auto captions: in CapCut you can change one caption's style and\n"
            "'Apply to all', and they show in the Captions list.\n"
            "Word styles (karaoke, one word…) are always written as text clips.")
        self.replace_box = QCheckBox("Replace subtitles added before")
        self.replace_box.setChecked(True)
        self.replace_box.setToolTip("Removes the old SinhalaSubs track first, so you never get two")
        self.write_btn = QPushButton("⬇ Write to CapCut")
        self.write_btn.setObjectName("Primary")
        self.write_btn.clicked.connect(self.write_capcut)
        self.restore_btn = QPushButton("↶ Undo last write (restore backup)")
        self.restore_btn.setObjectName("Danger")
        self.restore_btn.clicked.connect(self.restore)
        lay.addWidget(self.captions_box)
        lay.addWidget(self.replace_box)
        lay.addWidget(self.write_btn)
        lay.addWidget(self.restore_btn)
        return panel

    def _build_player(self) -> None:
        self.player = None
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:        # QtMultimedia missing: the app still works, just without sound
            return
        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.player.playbackStateChanged.connect(self._play_state_changed)
        self._tick = QTimer(self, interval=30, timeout=self._on_tick)

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Space"), self, self.toggle_play)
        QShortcut(QKeySequence.Undo, self, self.undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, self.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self.redo)
        for widget in (self.table, self.timeline):
            QShortcut(QKeySequence.Delete, widget, self.delete_cues, context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Space"), self.timeline, self.toggle_play, context=Qt.WidgetShortcut)
        QShortcut(QKeySequence("S"), self.timeline, self.split_cue, context=Qt.WidgetShortcut)

    # --- cues, undo and selection -------------------------------------------------------------------

    @property
    def cues(self) -> list[Cue]:
        return self.table.model_.cues

    def set_cues(self, cues: list[Cue], undoable: bool = True) -> None:
        if undoable:
            self.checkpoint()
        self.table.model_.set_cues(cues)
        self.timeline.set_cues(cues)
        self._cues_edited()

    def checkpoint(self) -> None:
        """Remember the subtitles as they are now, so Undo can bring them back."""
        self._undo.append(copy.deepcopy(self.cues))
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()

    def undo(self) -> None:
        if self._undo:
            self._redo.append(copy.deepcopy(self.cues))
            self.set_cues(self._undo.pop(), undoable=False)

    def redo(self) -> None:
        if self._redo:
            self._undo.append(copy.deepcopy(self.cues))
            self.set_cues(self._redo.pop(), undoable=False)

    def _cues_edited(self) -> None:
        n = len(self.cues)
        red = sum(has_foreign(c.text) for c in self.cues)
        self.count_label.setText(f"{n} subtitles" + (f" · {red} need fixing (red)" if red else ""))
        self.table.model_.refresh()
        self.timeline.set_cues(self.cues)
        self._save_timer.start()
        self._update_buttons()
        self._update_preview()

    def _timeline_changing(self) -> None:
        self.table.model_.refresh()
        self._update_preview()

    def _table_selected(self, *_) -> None:
        if self._syncing:
            return
        rows = self.table.selected_rows()
        self._syncing = True
        self.timeline.set_selection(rows)
        self._syncing = False
        if rows and not self.playing():
            self.seek(self.cues[rows[0]].start, update_selection=False)
        self._update_preview()

    def _timeline_selected(self, rows: list[int]) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.table.clearSelection()
        for r in rows:
            self.table.selectionModel().select(self.table.model_.index(r, 0),
                                               QItemSelectionModel.Select | QItemSelectionModel.Rows)
        if rows:
            self.table.scrollTo(self.table.model_.index(rows[0], 0))
        self._syncing = False
        self._update_preview()

    def _update_preview(self) -> None:
        if self.playing():
            t = self.timeline.playhead
            i = timing.cue_at(self.cues, t)
            self.preview.show_cue(self.cues[i] if i >= 0 else None, t, placeholder=False)
            return
        rows = self.table.selected_rows()
        i = rows[0] if rows else timing.cue_at(self.cues, self.timeline.playhead)
        self.preview.show_cue(self.cues[i] if 0 <= i < len(self.cues) else (self.cues[0] if self.cues else None))

    def _language_chosen(self, *_) -> None:
        """New spoken language: remember it, and switch to a font that has its letters."""
        from dataclasses import replace

        from ..languages import default_font, get
        lang = get(self.language.currentData())
        self.settings.language = lang.code
        self.settings.save()
        style = replace(self.style_, font_path=default_font(lang), convert_to_fm=lang.fm)
        self.style_panel.set_style(style)
        self._style_changed(style)
        self.log(f"Language: {lang.name}. Font: {Path(style.font_path).stem}"
                 + (" (FM letters)" if lang.fm else ""))

    def _style_dragged(self, style: SubtitleStyle) -> None:
        """The subtitle was moved/resized on the preview: show the new numbers in the style panel."""
        self.style_ = style
        self.style_panel.set_style(style)

    def _style_changed(self, style: SubtitleStyle) -> None:
        self.style_ = style
        self.preview.set_style(style)

    # --- playback ---------------------------------------------------------------------------------

    def playing(self) -> bool:
        if not self.player:
            return False
        from PySide6.QtMultimedia import QMediaPlayer
        return self.player.playbackState() == QMediaPlayer.PlayingState

    def toggle_play(self) -> None:
        if not (self.player and self.wav):
            self.log("The audio is not ready yet.")
            return
        if self.playing():
            self.player.pause()
        else:
            self.player.setPosition(int(self.timeline.playhead * 1000))
            self.player.play()

    def seek(self, t: float, update_selection: bool = True) -> None:
        self.timeline.set_playhead(t)
        if self.player and self.wav:
            self.player.setPosition(int(t * 1000))
        self._show_time()
        if update_selection and not self.playing():
            self._update_preview()

    def _play_state_changed(self, _state) -> None:
        on = self.playing()
        self.play_btn.setText("⏸  Pause" if on else "▶  Play")
        self.timeline.follow = on and self.follow_box.isChecked()
        if on:
            self.animate_btn.setChecked(False)
            self._tick.start()
        else:
            self._tick.stop()
            self._update_preview()

    def _on_tick(self) -> None:
        self.timeline.set_playhead(self.player.position() / 1000)
        self._show_time()
        self._update_preview()

    def _show_time(self) -> None:
        self.time_label.setText(f"{fmt_time(self.timeline.playhead)} / {fmt_time(self.timeline.duration)}")

    # --- helpers ---------------------------------------------------------------------------------------

    def log(self, text: str) -> None:
        self.log_box.appendPlainText(text)

    def _update_buttons(self) -> None:
        busy = self.task is not None
        preparing = self.audio_task is not None
        has_source = self.video is not None or (self.draft is not None and self.track.count() > 0)
        self.generate_btn.setEnabled(has_source and not busy and not preparing)
        self.generate_btn.setText("Preparing audio…" if preparing else "✨ Generate captions")
        self.write_btn.setEnabled(self.draft is not None and bool(self.cues) and not busy)
        self.restore_btn.setEnabled(self.project is not None and not busy)
        self.play_btn.setEnabled(self.wav is not None and self.player is not None)
        self.cancel_btn.setVisible(busy)
        self.progress.setVisible(busy)
        self.close_video_btn.setVisible(self.video is not None)
        for w in (self.timeline_box, self.track):
            w.setEnabled(self.video is None)

    def _save_session(self) -> None:
        if self.session_key:
            save_session(self.session_key, self.cues)

    def _set_session(self, key: str) -> None:
        self._save_session()
        self.session_key = hashlib.sha1(key.encode()).hexdigest()[:10] + "-" + Path(key).name[:40]
        self._undo.clear()
        self._redo.clear()
        cues = load_session(self.session_key)
        self.set_cues(cues, undoable=False)
        if cues:
            self.log(f"Loaded your last {len(cues)} subtitles for this project.")

    # --- projects and audio ------------------------------------------------------------------------

    def refresh_projects(self) -> None:
        root = Path(self.settings.drafts_root) if self.settings.drafts_root else None
        self.projects.clear()
        for p in list_projects(root):
            mins, secs = divmod(int(p.duration), 60)
            when = time.strftime("%d %b %Y", time.localtime(p.modified))
            item = QListWidgetItem(f"{p.name}\n{mins}:{secs:02d} · {when}")
            item.setData(Qt.UserRole, p)
            item.setIcon(self._thumb(p.cover))
            self.projects.addItem(item)
        if self.projects.count() == 0:
            self.log("No CapCut projects found. If you moved CapCut's drafts folder, set it in Settings.")
        self._filter_projects(self.search.text())

    @staticmethod
    def _thumb(cover: Path | None) -> QIcon:
        """A square 56×56 thumbnail (a dark tile when the project has no cover)."""
        square = QPixmap(56, 56)
        square.fill(QColor(PANEL_2))
        pix = QPixmap(str(cover)) if cover else QPixmap()
        if not pix.isNull():
            pix = pix.scaled(56, 56, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p = QPainter(square)
            p.drawPixmap(0, 0, pix, (pix.width() - 56) // 2, (pix.height() - 56) // 2, 56, 56)
            p.end()
        return QIcon(square)

    def _filter_projects(self, text: str) -> None:
        for i in range(self.projects.count()):
            item = self.projects.item(i)
            item.setHidden(text.lower() not in item.text().lower())

    def _project_chosen(self, item: QListWidgetItem | None, _prev=None) -> None:
        if item is None:
            return
        self.project = item.data(Qt.UserRole)
        self.video = None
        self.timeline_box.blockSignals(True)
        self.timeline_box.clear()
        try:
            timelines = list_timelines(self.project.folder)
            for t in timelines:
                self.timeline_box.addItem(f"{t.name} · {fmt_time(t.duration)}" + ("  (main)" if t.is_main else ""), t)
            self.timeline_box.setCurrentIndex(max(0, current_timeline(timelines, self.project.duration)))
        finally:
            self.timeline_box.blockSignals(False)
        self._timeline_chosen()

    def _timeline_chosen(self, *_) -> None:
        self.track.blockSignals(True)
        self.track.clear()
        self.track.blockSignals(False)
        self.draft = None
        t = self.timeline_box.currentData()
        if not (self.project and t):
            self._update_buttons()
            return
        try:
            self.draft = Draft(self.project.folder, t)
        except (RuntimeError, OSError, ValueError) as e:
            self.log(f"⚠ {e}")
            self.source_label.setText(str(e))
            self._update_buttons()
            return
        self.track.blockSignals(True)
        for tr in self.draft.audio_tracks():
            self.track.addItem(tr.label, tr)
        self.track.blockSignals(False)
        self.preview.set_canvas(self.draft.canvas, self.project.cover)
        self.timeline.set_duration(self.draft.duration)
        self.source_label.setText(f"CapCut: {self.project.name} · {t.name}")
        if self.track.count() == 0:
            self.log("This timeline has no audio or video clips to listen to.")
        self._set_session(f"{self.project.folder}|{t.id}")
        self._track_chosen()

    def _track_chosen(self, *_) -> None:
        track = self.track.currentData()
        if track:
            self._prepare_audio(track.clips)

    def open_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Video or audio file", "",
            "Media (*.mp4 *.mov *.mkv *.avi *.webm *.mp3 *.wav *.m4a *.aac);;All files (*)")
        if not path:
            return
        self.projects.clearSelection()
        self.project, self.draft, self.video = None, None, Path(path)
        self.timeline_box.clear()
        self.track.clear()
        self.preview.set_canvas((1920, 1080), None)
        self.source_label.setText(f"Video: {self.video.name}\n(Export the result as .srt)")
        self._set_session(str(self.video))
        self._prepare_audio(self.video)

    def close_video(self) -> None:
        """Leave video mode. The subtitles are saved and come back if the video is opened again."""
        if self.task:
            QMessageBox.information(self, "Busy", "Wait for the current job to finish (or Cancel it) first.")
            return
        if self.audio_task:
            self.audio_task.cancel()
            self.audio_task.wait(5000)
            self.audio_task = None
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())
        self._save_session()
        self.session_key = ""
        self.video = self.wav = None
        self.table.model_.set_cues([])
        self._undo.clear()
        self._redo.clear()
        self.timeline.set_peaks([], BUCKET)
        self.timeline.set_duration(60)
        self.seek(0.0)
        self.preview.set_canvas((1920, 1080), None)
        self.source_label.setText("No project chosen")
        self._cues_edited()
        self.log("Video closed. Pick a CapCut project or open another video.")

    def _audio_source(self):
        return self.video if self.video else (self.track.currentData().clips if self.track.currentData() else None)

    def _prepare_audio(self, source) -> None:
        """Make the WAV + waveform in the background; playback and Generate use it."""
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())
        self.wav = None
        self.timeline.set_peaks([], BUCKET)
        if self.audio_task:
            self.audio_task.cancel()
            self.audio_task.wait(5000)
        task = Task(_audio_job, source, parent=self)
        task.log.connect(self.log)
        task.succeeded.connect(lambda res, t=task: self._audio_ready(t, res))
        task.failed.connect(lambda msg: self.log(f"⚠ Audio: {msg}"))
        task.finished.connect(lambda t=task: self._audio_task_done(t))
        self.audio_task = task
        task.start()
        self._update_buttons()

    def _audio_ready(self, task: Task, result) -> None:
        if task is not self.audio_task:
            return        # an older job for a source the user already left
        self.wav, total, peaks = result
        self.timeline.set_duration(total)
        self.timeline.set_peaks(peaks, BUCKET)
        if self.player:
            self.player.setSource(QUrl.fromLocalFile(str(self.wav)))
        self._show_time()

    def _audio_task_done(self, task: Task) -> None:
        if task is self.audio_task:
            self.audio_task = None
        self._update_buttons()

    # --- long jobs -------------------------------------------------------------------------------------

    def _start(self, task: Task, on_done) -> None:
        self.task = task
        task.log.connect(self.log)
        task.progress.connect(lambda d, n: (self.progress.setMaximum(n), self.progress.setValue(d)))
        task.succeeded.connect(on_done)
        task.failed.connect(self._task_failed)
        task.finished.connect(self._task_finished)
        self.progress.setRange(0, 0)   # "busy" animation until the first chunk is done
        task.start()
        self._update_buttons()

    def _task_failed(self, msg: str) -> None:
        from ..transcribe import friendly_error
        QMessageBox.warning(self, "Something went wrong", friendly_error(Exception(msg)))

    def _task_finished(self) -> None:
        self.task = None
        self._update_buttons()

    def cancel_task(self) -> None:
        if self.task:
            self.task.cancel()
            self.log("Cancelling after the current step…")

    def _need_key(self) -> bool:
        if self.settings.api_key or self.settings.engine == "whisper":
            return False
        QMessageBox.information(self, "Gemini API key needed",
                                "Paste your Gemini API key in Settings first. It's free at aistudio.google.com/apikey.")
        self.open_settings()
        return not self.settings.api_key

    def _need_key_for_polish(self) -> bool:
        """Fix script without a key: offer letter mapping only. True = go ahead."""
        return QMessageBox.question(
            self, "No Gemini key",
            "Without a Gemini key only simple letter mapping is used (less accurate).\nContinue?") == QMessageBox.Yes

    def generate(self) -> None:
        source = self._audio_source()
        if source is None or self._need_key():
            return
        existing = None
        if self.cues:
            box = QMessageBox(QMessageBox.Question, "You already have subtitles",
                              "Fill only the parts that have no subtitle yet (for example parts Gemini "
                              "skipped because it was busy), or make everything again?", parent=self)
            fill = box.addButton("Fill missing parts", QMessageBox.AcceptRole)
            again = box.addButton("Replace all", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(fill)
            box.exec()
            if box.clickedButton() not in (fill, again):
                return
            if box.clickedButton() is fill:
                existing = copy.deepcopy(self.cues)
        self.log("—" * 30)
        self._start(Task(_generate_job, source, self.settings.transcribe_options(), existing, parent=self),
                    self._generated)

    def _generated(self, cues: list[Cue]) -> None:
        missing = getattr(cues, "missing", [])
        self.set_cues(list(cues))
        if missing:
            secs = sum(b - a for a, b in missing)
            QMessageBox.information(
                self, "Some parts are missing",
                f"Gemini was too busy for {len(missing)} part(s) (about {secs:.0f} seconds of audio).\n"
                "Everything else is done and kept.\n\n"
                "Try again in a few minutes: click Generate and choose 'Fill missing parts'.")
        else:
            self.log("✓ Check the subtitles, fix anything red, then Write to CapCut.")

    def fix_script(self) -> None:
        if not self.cues:
            return
        if self.settings.polish and not self.settings.api_key and not self._need_key_for_polish():
            return
        self._start(Task(_fix_script_job, self.cues, self.settings.transcribe_options(), parent=self), self.set_cues)

    # --- editing -----------------------------------------------------------------------------------------

    def _edit(self, fn) -> None:
        """Run fn on a copy of the cues and keep the result (one undo step)."""
        cues = copy.deepcopy(self.cues)
        select = fn(cues)
        self.set_cues(cues)
        if isinstance(select, int) and 0 <= select < len(cues):
            self.table.selectRow(select)

    def add_cue(self) -> None:
        def add(cues):
            t = self.timeline.playhead
            i = timing.cue_at(cues, t)
            start = cues[i].end + 0.05 if i >= 0 else t
            nxt = min((c.start for c in cues if c.start >= start), default=start + 2.0)
            cues.append(Cue(start, min(start + 2.0, nxt) if nxt > start + 0.2 else start + 2.0, "නව subtitle"))
            cues.sort(key=lambda c: c.start)
            timing.fix_overlaps(cues)
            return next(k for k, c in enumerate(cues) if c.start == start)
        self._edit(add)

    def delete_cues(self) -> None:
        rows = set(self.table.selected_rows())

        def delete(cues):
            cues[:] = [c for i, c in enumerate(cues) if i not in rows]
        if rows:
            self._edit(delete)

    def merge_cues(self) -> None:
        rows = self.table.selected_rows()
        if rows:
            self._edit(lambda cues: timing.merge(cues, rows))

    def split_cue(self) -> None:
        rows = self.table.selected_rows()
        if len(rows) != 1:
            i = timing.cue_at(self.cues, self.timeline.playhead)
            rows = [i] if i >= 0 else []
        if rows and len(self.cues[rows[0]].text.split()) > 1:
            t = self.timeline.playhead
            self._edit(lambda cues: timing.split(cues, rows[0], t))

    def _timing_tool(self, fn, what: str) -> None:
        cues = copy.deepcopy(self.cues)
        n = fn(cues)
        self.set_cues(cues)
        self.log(f"{n} {what}.")

    def shift_all(self) -> None:
        delta, ok = QInputDialog.getDouble(self, "Shift all subtitles",
                                           "Seconds (negative = earlier):", 0.0, -600, 600, 2)
        if ok and delta:
            self._edit(lambda cues: timing.shift_all(cues, delta))

    # --- files ---------------------------------------------------------------------------------------------

    def import_srt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import subtitles", "", "Subtitles (*.srt)")
        if path:
            self.set_cues(from_srt(Path(path).read_text(encoding="utf-8-sig")))
            self.log(f"Imported {len(self.cues)} subtitles from {Path(path).name}")

    def export_srt(self, fm: bool) -> None:
        if not self.cues:
            return
        name = self.video.stem if self.video else self.project.name if self.project else "subtitles"
        path, _ = QFileDialog.getSaveFileName(self, "Export subtitles", f"{name}{'.fm' if fm else ''}.srt",
                                              "Subtitles (*.srt)")
        if path:
            cues = [Cue(c.start, c.end, unicode_to_fm(c.text)) for c in self.cues] if fm else self.cues
            Path(path).write_text(to_srt(cues), encoding="utf-8")
            self.log(f"Saved {path}")

    def write_capcut(self) -> None:
        if not (self.draft and self.cues):
            return
        if is_capcut_running() and QMessageBox.question(
                self, "CapCut is open",
                f"Make sure '{self.project.name}' is CLOSED in CapCut (go back to CapCut's home screen).\n\n"
                "If the project is open, CapCut will overwrite the subtitles. Continue?") != QMessageBox.Yes:
            return
        try:
            result = write_to_draft(self.project.folder, self.draft.timeline, self.cues, self.style_,
                                    replace=self.replace_box.isChecked(),
                                    as_captions=self.captions_box.isChecked(),
                                    language=self.settings.language)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Could not write to CapCut", str(e))
            return
        self.settings.style = asdict(self.style_)
        self.settings.as_captions = self.captions_box.isChecked()
        self.settings.save()
        kind = "CapCut captions" if result.get("as_captions") else "text clips"
        msg = f"✓ Wrote {result['added']} {kind} into '{self.project.name}'."
        if result["removed"]:
            msg += f" Replaced {result['removed']} old ones."
        self.log(msg + f" Backup: {result['backup']}")
        QMessageBox.information(self, "Done", msg + "\n\nOpen the project in CapCut to see them.")

    def restore(self) -> None:
        if not self.project:
            return
        backups = list_backups(self.project.folder)
        if not backups:
            QMessageBox.information(self, "No backup", "This project has no backups from SinhalaSubs yet.")
            return
        when = time.strftime("%d %b %Y %H:%M:%S", time.strptime(backups[0].name, "%Y%m%d-%H%M%S"))
        if QMessageBox.question(self, "Restore backup?",
                                f"Put '{self.project.name}' back the way it was on {when}?") != QMessageBox.Yes:
            return
        n = restore_backup(self.project.folder, backups[0])
        self.log(f"↶ Restored {n} file(s) from the backup of {when}.")
        self._timeline_chosen()

    # --- settings and closing ---------------------------------------------------------------------------

    def preview_animate(self, on: bool) -> None:
        if on and self.playing():
            self.player.pause()
        self.preview.set_animate(on)
        self._update_preview()

    def open_studio(self) -> None:
        from .caption_studio import CaptionStudio

        canvas = self.draft.canvas if self.draft else (1920, 1080)
        cover = self.project.cover if self.project else None
        studio = CaptionStudio(self.style_, canvas, cover, self)
        if studio.exec():
            self.style_panel.set_style(studio.result_style)
            self._style_changed(studio.result_style)

    def open_settings(self) -> None:
        old_root = self.settings.drafts_root
        if SettingsDialog(self.settings, self).exec() and self.settings.drafts_root != old_root:
            self.refresh_projects()

    def closeEvent(self, event) -> None:
        for task in (self.task, self.audio_task):
            if task:
                task.cancel()
                task.wait(10_000)
        if self.player:
            self.player.stop()
        self._save_session()
        self.settings.style = asdict(self.style_)
        self.settings.window = bytes(self.saveGeometry().toBase64()).decode()
        self.settings.save()
        super().closeEvent(event)
