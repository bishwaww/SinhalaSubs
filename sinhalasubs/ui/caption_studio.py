"""Caption Studio: a library of caption looks with live, animated thumbnails."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QButtonGroup, QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QStyle,
                               QStyledItemDelegate, QVBoxLayout)

from .. import caption_presets as presets
from ..models import Cue
from ..style import SubtitleStyle
from . import theme
from .preview import PreviewCanvas, paint_caption

TILE = QSize(230, 150)
DEMO = Cue(0.0, 2.6, "අද අපි අලුත් video එකක් හදමු")


class TileDelegate(QStyledItemDelegate):
    """Draws a look as a small card with its caption playing live."""

    def __init__(self, studio: "CaptionStudio"):
        super().__init__(studio)
        self.studio = studio

    def sizeHint(self, option, index) -> QSize:
        return TILE

    def paint(self, p: QPainter, option, index) -> None:
        look: presets.Look = index.data(Qt.UserRole)
        r = QRectF(option.rect).adjusted(5, 5, -5, -5)
        selected = bool(option.state & QStyle.State_Selected)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(theme.ACCENT if selected else theme.BORDER), 2 if selected else 1))
        p.setBrush(QColor("#0B0C0E"))
        p.drawRoundedRect(r, 8, 8)
        frame = r.adjusted(4, 4, -4, -24)
        if self.studio.cover and not self.studio.cover.isNull():
            img = self.studio.cover.scaled(frame.size().toSize(), Qt.KeepAspectRatioByExpanding)
            p.drawImage(frame, img, QRectF(0, 0, frame.width(), frame.height()))
            p.fillRect(frame, QColor(0, 0, 0, 90))
        style = look.apply(self.studio.base_style)
        style.pos_y, style.pos_x, style.scale = 0.0, 0.0, 1.0
        style.size = 26.0                                  # thumbnails need bigger letters
        p.setClipRect(frame)
        paint_caption(p, frame, style, DEMO, self.studio.demo_time())
        p.setClipping(False)
        p.setPen(QColor(theme.TEXT))
        star = "★ " if look.name in self.studio.favs else ""
        p.drawText(r.adjusted(8, 0, -8, -4), Qt.AlignBottom | Qt.AlignLeft, star + look.name)
        p.setPen(QColor(theme.MUTED))
        p.drawText(r.adjusted(8, 0, -8, -4), Qt.AlignBottom | Qt.AlignRight, look.category)
        p.restore()


class CaptionStudio(QDialog):
    """Pick a look; `result_style` is the chosen style when the dialog is accepted."""

    def __init__(self, style: SubtitleStyle, canvas: tuple[int, int] = (1920, 1080),
                 cover: Path | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Caption Studio")
        self.resize(1100, 720)
        self.base_style = style
        self.result_style = style
        self.cover = QImage(str(cover)) if cover and Path(cover).is_file() else None
        self.favs = presets.favourites()
        self._t0 = time.monotonic()

        # categories + search
        top = QHBoxLayout()
        self.cats = QButtonGroup(self)
        for i, name in enumerate(presets.CATEGORIES):
            b = QPushButton(name, checkable=True)
            b.setChecked(i == 0)
            self.cats.addButton(b, i)
            top.addWidget(b)
        self.cats.idClicked.connect(lambda _: self.refill())
        top.addStretch(1)
        self.search = QLineEdit(placeholderText="Search looks…")
        self.search.textChanged.connect(lambda _: self.refill())
        top.addWidget(self.search)

        # the grid of tiles
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.IconMode)
        self.grid.setResizeMode(QListWidget.Adjust)
        self.grid.setMovement(QListWidget.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setGridSize(TILE)
        self.grid.setItemDelegate(TileDelegate(self))
        self.grid.currentItemChanged.connect(self._chosen)
        self.grid.itemDoubleClicked.connect(lambda _: self.accept())

        # big preview of the chosen look with the user's own font, size and position
        self.preview = PreviewCanvas(editable=False)
        self.preview.set_canvas(canvas, cover)
        self.preview.set_style(style)
        self.preview.show_cue(Cue(0.0, 3.2, DEMO.text))
        self.preview.set_animate(True)
        self.preview.setMinimumWidth(360)
        self.name_label = QLabel("")
        self.name_label.setObjectName("Title")

        self.fav_btn = QPushButton("☆ Favourite", checkable=True)
        self.fav_btn.toggled.connect(self._toggle_fav)
        save_btn = QPushButton("Save my current style as a look…")
        save_btn.clicked.connect(self.save_current)
        self.del_btn = QPushButton("Delete look")
        self.del_btn.setObjectName("Danger")
        self.del_btn.clicked.connect(self.delete_look)
        apply_btn = QPushButton("Use this look")
        apply_btn.setObjectName("Primary")
        apply_btn.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)

        side = QVBoxLayout()
        side.addWidget(self.name_label)
        side.addWidget(self.preview, 1)
        hint = QLabel("A look changes colours, outline, glow, box, word highlight and animation.\n"
                      "Your font, size and position stay the same.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        side.addWidget(hint)
        row = QHBoxLayout()
        row.addWidget(self.fav_btn)
        row.addWidget(self.del_btn)
        side.addLayout(row)
        side.addWidget(save_btn)
        row2 = QHBoxLayout()
        row2.addStretch(1)
        row2.addWidget(cancel)
        row2.addWidget(apply_btn)
        side.addLayout(row2)

        body = QHBoxLayout()
        body.addWidget(self.grid, 3)
        body.addLayout(side, 2)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(body, 1)

        self._timer = QTimer(self, interval=66, timeout=self.grid.viewport().update)   # ~15 fps thumbnails
        self._timer.start()
        self.refill()

    def demo_time(self) -> float:
        cycle = DEMO.duration + 0.5
        return min(DEMO.end - 1e-3, (time.monotonic() - self._t0) % cycle)

    def refill(self) -> None:
        cat = presets.CATEGORIES[max(0, self.cats.checkedId())]
        current = self.grid.currentItem().data(Qt.UserRole).name if self.grid.currentItem() else ""
        self.grid.clear()
        for look in presets.all_looks():
            if cat == "Favourites" and look.name not in self.favs:
                continue
            if cat not in ("All", "Favourites") and look.category != cat:
                continue
            if not look.matches(self.search.text()):
                continue
            item = QListWidgetItem()
            item.setData(Qt.UserRole, look)
            item.setSizeHint(TILE)
            self.grid.addItem(item)
            if look.name == current:
                self.grid.setCurrentItem(item)
        if not self.grid.currentItem() and self.grid.count():
            self.grid.setCurrentRow(0)

    def _chosen(self, item, _prev=None) -> None:
        if not item:
            return
        look: presets.Look = item.data(Qt.UserRole)
        self.result_style = look.apply(self.base_style)
        self.preview.set_style(self.result_style)
        self.name_label.setText(look.name)
        self.fav_btn.blockSignals(True)
        self.fav_btn.setChecked(look.name in self.favs)
        self.fav_btn.setText("★ Favourite" if look.name in self.favs else "☆ Favourite")
        self.fav_btn.blockSignals(False)
        self.del_btn.setEnabled(not look.builtin)

    def _toggle_fav(self, on: bool) -> None:
        item = self.grid.currentItem()
        if not item:
            return
        name = item.data(Qt.UserRole).name
        presets.set_favourite(name, on)
        self.favs = presets.favourites()
        self.fav_btn.setText("★ Favourite" if on else "☆ Favourite")
        self.grid.viewport().update()

    def save_current(self) -> None:
        name, ok = QInputDialog.getText(self, "Save look", "Name for your look:")
        if ok and name.strip():
            presets.save_user_look(name.strip(), self.base_style)
            self.cats.button(presets.CATEGORIES.index("Mine")).setChecked(True)
            self.refill()

    def delete_look(self) -> None:
        item = self.grid.currentItem()
        if not item or item.data(Qt.UserRole).builtin:
            return
        name = item.data(Qt.UserRole).name
        if QMessageBox.question(self, "Delete look", f"Delete '{name}'?") == QMessageBox.Yes:
            presets.delete_user_look(name)
            self.refill()

    def done(self, result: int) -> None:
        self._timer.stop()
        self.preview.set_animate(False)
        super().done(result)
