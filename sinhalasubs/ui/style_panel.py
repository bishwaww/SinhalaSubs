"""Controls for SubtitleStyle. Every change is sent out as a new style right away."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox,
                               QVBoxLayout, QWidget)

from .. import animations
from ..captions import MODES
from ..style import SubtitleStyle, find_font, fm_fonts


class ColorButton(QPushButton):
    changed = Signal(str)

    def __init__(self, color: str):
        super().__init__()
        self.setFixedSize(34, 24)
        self.clicked.connect(self._pick)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        self.color = color
        self.setStyleSheet(f"background:{color or '#00000000'}; border:1px solid #555; border-radius:5px;")

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self.color or "#FFFFFF"), self, "Colour")
        if c.isValid():
            self.set_color(c.name().upper())
            self.changed.emit(self.color)


def _slider(lo: int, hi: int) -> QSlider:
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    return s


def _section(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setObjectName("Section")
    return lbl


def _anim_combo(kind: str) -> QComboBox:
    c = QComboBox()
    c.addItem("None", "")
    for a in animations.catalog()[kind]:
        c.addItem(a.name, a.key)
    return c


class StylePanel(QWidget):
    style_changed = Signal(object)     # SubtitleStyle
    studio_requested = Signal()

    def __init__(self, style: SubtitleStyle, parent=None):
        super().__init__(parent)
        self.style_ = style
        self._loading = False

        studio = QPushButton("🎨  Caption Studio…")
        studio.setToolTip("Ready-made looks: karaoke, neon, boxes, animations…")
        studio.clicked.connect(self.studio_requested)

        # Text ------------------------------------------------------------------------------
        self.font = QComboBox()
        self.font.setMinimumContentsLength(10)
        self.font.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for path in fm_fonts():
            self.font.addItem(Path(path).stem, path)
        from ..languages import LANGUAGES, default_font
        for path in dict.fromkeys(filter(None, (default_font(lang) for lang in LANGUAGES))):
            if self.font.findData(path) < 0:
                self.font.addItem(Path(path).stem, path)
        self.font.addItem("Other font file…", "__other__")
        self.fm = QCheckBox("Convert to FM font text")
        self.size = QDoubleSpinBox(minimum=2, maximum=60, singleStep=0.5, decimals=1)
        self.bold = QCheckBox("Bold")
        self.color = ColorButton(style.color)
        self.gradient = QCheckBox("Fade to")
        self.gradient_color = ColorButton(style.gradient_color)

        # Caption (word) style ------------------------------------------------------------------
        self.mode = QComboBox()
        for key, label in MODES.items():
            self.mode.addItem(label, key)
        self.per_page = QSpinBox(minimum=0, maximum=12, specialValueText="Whole subtitle")
        self.per_page.setSuffix(" words")
        self.case = QComboBox()
        for key, label in (("none", "As written"), ("upper", "ENGLISH CAPS"), ("lower", "english lower")):
            self.case.addItem(label, key)
        self.hl_color = ColorButton(style.hl_color)
        self.spoken = QCheckBox("Colour spoken words")
        self.spoken_color = ColorButton(style.spoken_color or style.hl_color)
        self.hl_scale = _slider(100, 150)

        # Look ------------------------------------------------------------------------------
        self.stroke = QCheckBox("Outline")
        self.stroke_color = ColorButton(style.stroke_color)
        self.stroke_w = _slider(0, 20)
        self.glow = QCheckBox("Glow")
        self.glow_color = ColorButton(style.glow_color)
        self.glow_w = _slider(5, 40)
        self.shadow = QCheckBox("Shadow")
        self.shadow_color = ColorButton(style.shadow_color)
        self.shadow_d = _slider(0, 30)
        self.box = QCheckBox("Background box")
        self.box_color = ColorButton(style.background_color)
        self.box_a = _slider(0, 100)

        # Animation ---------------------------------------------------------------------------
        self.intro = _anim_combo("in")
        self.intro_d = QDoubleSpinBox(minimum=0.1, maximum=3, singleStep=0.05, decimals=2, suffix=" s")
        self.outro = _anim_combo("out")
        self.outro_d = QDoubleSpinBox(minimum=0.1, maximum=3, singleStep=0.05, decimals=2, suffix=" s")
        self.loop = _anim_combo("loop")

        # Position ------------------------------------------------------------------------------
        self.pos_y = _slider(-100, 100)
        self.pos_x = _slider(-100, 100)
        self.scale = _slider(30, 250)
        self.width_ = _slider(30, 100)
        presets = QHBoxLayout()
        for name, y in (("Bottom", -0.75), ("Middle", 0.0), ("Top", 0.75)):
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, y=y: self.pos_y.setValue(round(y * 100)))
            presets.addWidget(b)

        def row(*widgets) -> QHBoxLayout:
            h = QHBoxLayout()
            stretchy = False
            for w in widgets:
                grow = isinstance(w, (QSlider, QComboBox, QDoubleSpinBox, QSpinBox))
                stretchy |= grow
                h.addWidget(w, 1 if grow else 0)
            if not stretchy:
                h.addStretch(1)   # keep small buttons next to their label, not pushed off the edge
            return h

        form = QFormLayout()
        form.addRow(studio)
        form.addRow(_section("Text"))
        form.addRow("Font", self.font)
        form.addRow("", self.fm)
        form.addRow("Size", row(self.size, self.bold))
        form.addRow("Colour", row(self.color, self.gradient, self.gradient_color))
        form.addRow(_section("Caption"))
        form.addRow("Style", self.mode)
        form.addRow("Show", self.per_page)
        form.addRow("English", self.case)
        form.addRow("Highlight", row(self.hl_color, self.spoken, self.spoken_color))
        form.addRow("Pop size", self.hl_scale)
        form.addRow(_section("Look"))
        form.addRow(row(self.stroke, self.stroke_color))
        form.addRow("Width", self.stroke_w)
        form.addRow(row(self.glow, self.glow_color))
        form.addRow("Glow size", self.glow_w)
        form.addRow(row(self.shadow, self.shadow_color))
        form.addRow("Distance", self.shadow_d)
        form.addRow(row(self.box, self.box_color))
        form.addRow("Opacity", self.box_a)
        form.addRow(_section("Animation"))
        form.addRow("In", row(self.intro, self.intro_d))
        form.addRow("Out", row(self.outro, self.outro_d))
        form.addRow("Loop", self.loop)
        form.addRow(_section("Position"))
        form.addRow(presets)
        form.addRow("Up / down", self.pos_y)
        form.addRow("Left / right", self.pos_x)
        form.addRow("Scale", self.scale)
        form.addRow("Line width", self.width_)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(form)
        lay.addStretch(1)

        self.set_style(style)
        for sig in (self.fm.toggled, self.bold.toggled, self.stroke.toggled, self.shadow.toggled,
                    self.box.toggled, self.glow.toggled, self.gradient.toggled, self.spoken.toggled,
                    self.size.valueChanged, self.stroke_w.valueChanged, self.glow_w.valueChanged,
                    self.shadow_d.valueChanged, self.box_a.valueChanged, self.pos_y.valueChanged,
                    self.pos_x.valueChanged, self.scale.valueChanged, self.width_.valueChanged,
                    self.hl_scale.valueChanged, self.per_page.valueChanged,
                    self.intro_d.valueChanged, self.outro_d.valueChanged,
                    self.mode.currentIndexChanged, self.case.currentIndexChanged,
                    self.intro.currentIndexChanged, self.outro.currentIndexChanged,
                    self.loop.currentIndexChanged,
                    self.color.changed, self.stroke_color.changed, self.shadow_color.changed,
                    self.box_color.changed, self.glow_color.changed, self.gradient_color.changed,
                    self.hl_color.changed, self.spoken_color.changed):
            sig.connect(self._emit)
        self.font.activated.connect(self._font_chosen)

    @staticmethod
    def _select(combo: QComboBox, data) -> None:
        combo.setCurrentIndex(max(0, combo.findData(data)))

    def set_style(self, style: SubtitleStyle) -> None:
        self._loading = True
        s = self.style_ = style
        font = s.font_path or find_font("FM-Abhaya", "FM-")
        idx = self.font.findData(font)
        if idx < 0 and font:
            self.font.insertItem(self.font.count() - 1, Path(font).stem, font)
            idx = self.font.findData(font)
        self.font.setCurrentIndex(max(0, idx))
        self.fm.setChecked(s.convert_to_fm)
        self.size.setValue(s.size)
        self.bold.setChecked(s.bold)
        self.color.set_color(s.color)
        self.gradient.setChecked(s.gradient_enabled)
        self.gradient_color.set_color(s.gradient_color)
        self._select(self.mode, s.caption_mode)
        self.per_page.setValue(s.words_per_caption)
        self._select(self.case, s.text_case)
        self.hl_color.set_color(s.hl_color)
        self.spoken.setChecked(bool(s.spoken_color))
        self.spoken_color.set_color(s.spoken_color or s.hl_color)
        self.hl_scale.setValue(round(s.hl_scale * 100))
        self.stroke.setChecked(s.stroke_enabled)
        self.stroke_color.set_color(s.stroke_color)
        self.stroke_w.setValue(round(s.stroke_width * 100))
        self.glow.setChecked(s.glow_enabled)
        self.glow_color.set_color(s.glow_color)
        self.glow_w.setValue(round(s.glow_width * 100))
        self.shadow.setChecked(s.shadow_enabled)
        self.shadow_color.set_color(s.shadow_color)
        self.shadow_d.setValue(round(s.shadow_distance))
        self.box.setChecked(s.background_enabled)
        self.box_color.set_color(s.background_color)
        self.box_a.setValue(round(s.background_alpha * 100))
        self._select(self.intro, s.intro)
        self.intro_d.setValue(s.intro_duration)
        self._select(self.outro, s.outro)
        self.outro_d.setValue(s.outro_duration)
        self._select(self.loop, s.loop)
        self.pos_y.setValue(round(s.pos_y * 100))
        self.pos_x.setValue(round(s.pos_x * 100))
        self.scale.setValue(round(s.scale * 100))
        self.width_.setValue(round(s.line_max_width * 100))
        self._update_enabled()
        self._loading = False

    def _update_enabled(self) -> None:
        """Grey out controls that do nothing with the current choices."""
        words = self.mode.currentData() != "classic"
        for w in (self.per_page, self.hl_color, self.hl_scale, self.spoken):
            w.setEnabled(words)
        self.spoken_color.setEnabled(words and self.spoken.isChecked())
        self.gradient_color.setEnabled(self.gradient.isChecked())
        self.intro_d.setEnabled(bool(self.intro.currentData()))
        self.outro_d.setEnabled(bool(self.outro.currentData()))

    def _font_chosen(self, index: int) -> None:
        if self.font.itemData(index) == "__other__":
            path, _ = QFileDialog.getOpenFileName(self, "Font file", "", "Fonts (*.ttf *.otf)")
            if path:
                self.font.insertItem(index, Path(path).stem, Path(path).as_posix())
                self.font.setCurrentIndex(index)
                self.fm.setChecked(Path(path).name.lower().startswith("fm"))
            else:
                self.font.setCurrentIndex(0)
        self._emit()

    def _emit(self, *_) -> None:
        if self._loading:
            return
        self._update_enabled()
        font = self.font.currentData()
        self.style_ = replace(
            self.style_,
            font_path=font if font and font != "__other__" else "",
            convert_to_fm=self.fm.isChecked(), size=self.size.value(), bold=self.bold.isChecked(),
            color=self.color.color, gradient_enabled=self.gradient.isChecked(),
            gradient_color=self.gradient_color.color,
            caption_mode=self.mode.currentData(), words_per_caption=self.per_page.value(),
            text_case=self.case.currentData(), hl_color=self.hl_color.color,
            spoken_color=self.spoken_color.color if self.spoken.isChecked() else "",
            hl_scale=self.hl_scale.value() / 100,
            stroke_enabled=self.stroke.isChecked(), stroke_color=self.stroke_color.color,
            stroke_width=self.stroke_w.value() / 100,
            glow_enabled=self.glow.isChecked(), glow_color=self.glow_color.color,
            glow_width=self.glow_w.value() / 100,
            shadow_enabled=self.shadow.isChecked(), shadow_color=self.shadow_color.color,
            shadow_distance=float(self.shadow_d.value()), background_enabled=self.box.isChecked(),
            background_color=self.box_color.color, background_alpha=self.box_a.value() / 100,
            intro=self.intro.currentData(), intro_duration=self.intro_d.value(),
            outro=self.outro.currentData(), outro_duration=self.outro_d.value(),
            loop=self.loop.currentData(),
            pos_y=self.pos_y.value() / 100, pos_x=self.pos_x.value() / 100,
            scale=self.scale.value() / 100, line_max_width=self.width_.value() / 100,
        )
        self.style_changed.emit(self.style_)
