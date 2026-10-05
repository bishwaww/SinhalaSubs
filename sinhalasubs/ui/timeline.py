"""Timeline editor: ruler, subtitle clips, audio waveform and playhead.

Mouse:  click = select / move the playhead · drag a clip = move it · drag an edge = trim
        Alt + drag an edge = roll it with a touching neighbour · Ctrl+click = add to selection
Wheel:  scroll left/right · Ctrl + wheel = zoom
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .. import timing
from ..models import Cue
from ..sinhala_script import has_foreign
from . import theme

EDGE_PX = 6          # how close to a clip edge counts as grabbing the edge
RULER_H = 22
SUB_H = 46


def fmt_ruler(t: float, step: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:04.1f}" if step < 1 else f"{int(m)}:{int(s):02d}"


class TimelineView(QWidget):
    seek = Signal(float)                 # user clicked a time
    selection_changed = Signal(list)     # row indexes
    edit_started = Signal()              # before a drag changes cues (for undo)
    cues_changing = Signal()             # during a drag
    edit_finished = Signal()             # after a drag

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.cues: list[Cue] = []
        self.selected: set[int] = set()
        self.peaks: list[int] = []
        self.peak_step = 0.02
        self.duration = 60.0
        self.pps = 40.0                  # pixels per second (zoom)
        self.offset = 0.0                # seconds at the left edge (scroll)
        self.playhead = 0.0
        self.follow = False              # keep the playhead in view while playing
        self._drag = None

    # --- data in -------------------------------------------------------------------------------

    def set_cues(self, cues: list[Cue]) -> None:
        self.cues = cues
        self.selected = {i for i in self.selected if i < len(cues)}
        self.update()

    def set_selection(self, rows: list[int]) -> None:
        self.selected = set(rows)
        if rows:
            c = self.cues[rows[0]]
            left, right = self.offset, self.offset + self.width() / self.pps
            if not (left <= c.start <= right):
                self.offset = max(0.0, c.start - 1.0)
        self.update()

    def set_peaks(self, peaks: list[int], step: float) -> None:
        self.peaks, self.peak_step = peaks, step
        self.update()

    def set_duration(self, d: float) -> None:
        self.duration = max(1.0, d)
        self.pps = max(self.min_pps(), min(self.pps, 400))
        self.update()

    def set_playhead(self, t: float) -> None:
        self.playhead = t
        if self.follow:
            right = self.offset + self.width() / self.pps
            if t > right - 1 or t < self.offset:
                self.offset = max(0.0, t - 1.0)
        self.update()

    # --- coordinates -------------------------------------------------------------------------------

    def min_pps(self) -> float:
        return max(2.0, self.width() / self.span())

    def span(self) -> float:
        end = max([self.duration] + [c.end for c in self.cues])
        return end + 1.0

    def x_of(self, t: float) -> float:
        return (t - self.offset) * self.pps

    def t_of(self, x: float) -> float:
        return max(0.0, self.offset + x / self.pps)

    def _clamp_offset(self) -> None:
        self.offset = max(0.0, min(self.offset, self.span() - self.width() / self.pps))

    def hit(self, pos: QPointF) -> tuple[int, str]:
        """(cue index, 'start' | 'end' | 'body') under the mouse, or (-1, '')."""
        if not (RULER_H <= pos.y() <= RULER_H + SUB_H):
            return -1, ""
        for i, c in enumerate(self.cues):
            x1, x2 = self.x_of(c.start), self.x_of(c.end)
            if x1 - EDGE_PX <= pos.x() <= x2 + EDGE_PX:
                if abs(pos.x() - x1) <= EDGE_PX:
                    return i, "start"
                if abs(pos.x() - x2) <= EDGE_PX:
                    return i, "end"
                if x1 <= pos.x() <= x2:
                    return i, "body"
        return -1, ""

    # --- mouse -------------------------------------------------------------------------------------

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.LeftButton:
            return
        i, part = self.hit(e.position())
        if i < 0:
            self.selected.clear()
            self.selection_changed.emit([])
            self.seek.emit(self.t_of(e.position().x()))
            self.update()
            return
        if e.modifiers() & Qt.ControlModifier:
            self.selected ^= {i}
        elif i not in self.selected or part != "body":
            self.selected = {i}
        self.selection_changed.emit(sorted(self.selected))
        idxs = sorted(self.selected) if part == "body" else [i]
        self._drag = {
            "part": part, "i": i, "idxs": idxs, "x0": e.position().x(),
            "orig": [(self.cues[k].start, self.cues[k].end) for k in idxs],
            "roll": bool(e.modifiers() & Qt.AltModifier), "moved": False,
        }
        self.update()

    def mouseMoveEvent(self, e) -> None:
        if not self._drag:
            _, part = self.hit(e.position())
            self.setCursor(Qt.SizeHorCursor if part in ("start", "end") else
                           Qt.OpenHandCursor if part == "body" else Qt.ArrowCursor)
            return
        d = self._drag
        dx = e.position().x() - d["x0"]
        if not d["moved"]:
            if abs(dx) < 3:
                return
            d["moved"] = True
            self.edit_started.emit()
        if d["part"] == "body":
            timing.move(self.cues, d["idxs"], d["orig"], dx / self.pps)
        else:
            timing.trim(self.cues, d["i"], d["part"], self.t_of(e.position().x()), roll=d["roll"])
        self.cues_changing.emit()
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        d, self._drag = self._drag, None
        if d and d["moved"]:
            self.edit_finished.emit()
        elif d:
            self.seek.emit(self.t_of(e.position().x()))

    def wheelEvent(self, e) -> None:
        delta = e.angleDelta().y() or e.angleDelta().x()
        if e.modifiers() & Qt.ControlModifier:             # zoom around the mouse
            t = self.t_of(e.position().x())
            factor = 1.25 if delta > 0 else 0.8
            self.pps = max(self.min_pps(), min(400.0, self.pps * factor))
            self.offset = t - e.position().x() / self.pps
        else:                                              # scroll
            self.offset -= delta / 120 * 60 / self.pps
        self._clamp_offset()
        self.update()

    def resizeEvent(self, e) -> None:
        self.pps = max(self.pps, self.min_pps())
        self._clamp_offset()
        super().resizeEvent(e)

    # --- drawing -----------------------------------------------------------------------------------

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(theme.PANEL))
        self._paint_ruler(p, w)
        self._paint_wave(p, QRectF(0, RULER_H + SUB_H + 4, w, h - RULER_H - SUB_H - 6))
        self._paint_cues(p)
        x = self.x_of(self.playhead)
        p.setPen(QPen(QColor(theme.ACCENT), 1.5))
        p.drawLine(QPointF(x, 0), QPointF(x, h))
        p.setBrush(QColor(theme.ACCENT))
        p.setPen(Qt.NoPen)
        p.drawPolygon([QPointF(x - 5, 0), QPointF(x + 5, 0), QPointF(x, 7)])
        p.end()

    def _paint_ruler(self, p: QPainter, w: int) -> None:
        p.fillRect(QRectF(0, 0, w, RULER_H), QColor(theme.PANEL_2))
        # choose a tick step that leaves ~80px between labels
        step = next((s for s in (0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300)
                     if s * self.pps >= 80), 600)
        t = (self.offset // step) * step
        p.setPen(QColor(theme.MUTED))
        while self.x_of(t) < w:
            x = self.x_of(t)
            p.drawLine(QPointF(x, RULER_H - 6), QPointF(x, RULER_H))
            p.drawText(QPointF(x + 3, RULER_H - 8), fmt_ruler(t, step))
            t += step

    def _paint_wave(self, p: QPainter, r: QRectF) -> None:
        if not self.peaks:
            p.setPen(QColor(theme.MUTED))
            p.drawText(r, Qt.AlignCenter, "Waveform appears when the audio is ready")
            return
        mid = r.center().y()
        color = QColor(theme.ACCENT)
        color.setAlpha(120)
        p.setPen(QPen(color, 1))
        first = max(0, int(self.offset / self.peak_step))
        per_px = 1 / (self.pps * self.peak_step)           # peaks per pixel
        for x in range(int(r.width())):
            a = first + int(x * per_px)
            b = max(a + 1, first + int((x + 1) * per_px))
            if a >= len(self.peaks):
                break
            v = max(self.peaks[a:b]) / 255 * r.height() / 2
            p.drawLine(QPointF(x, mid - v), QPointF(x, mid + v))

    def _paint_cues(self, p: QPainter) -> None:
        fm = QFontMetrics(self.font())
        top = RULER_H + 3
        for i, c in enumerate(self.cues):
            x1, x2 = self.x_of(c.start), self.x_of(c.end)
            if x2 < 0 or x1 > self.width():
                continue
            rect = QRectF(x1, top, max(2.0, x2 - x1), SUB_H - 6)
            sel = i in self.selected
            fill = QColor(theme.DANGER if has_foreign(c.text) else "#3B4150")
            if sel:
                fill = QColor(theme.ACCENT)
            p.setPen(QPen(QColor(theme.ACCENT) if sel else QColor(theme.BORDER), 1))
            p.setBrush(fill)
            p.drawRoundedRect(rect, 4, 4)
            if rect.width() > 14:
                p.setPen(QColor("#1A1206") if sel else QColor(theme.TEXT))
                text = fm.elidedText(c.text, Qt.ElideRight, int(rect.width() - 8))
                p.drawText(rect.adjusted(4, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
