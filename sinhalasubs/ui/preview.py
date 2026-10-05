"""Live preview: draws a video frame with the subtitle, styled like CapCut will show it.

Handles word roles (karaoke highlight), outline, glow, gradient, shadow, box and
the intro/outro/loop animations, using the same numbers the writer puts in the draft.
"""

from __future__ import annotations

import math
import time
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPen)
from PySide6.QtWidgets import QWidget

from .. import animations, captions, layout
from ..capcut import metrics
from ..fm_converter import fm_runs
from ..models import Cue
from ..style import SubtitleStyle

SAMPLE = "සිංහල subtitles මෙතන පෙනේවි"


ROLES = ("normal", "spoken", "active")


def _length(v: QPointF) -> float:
    return math.hypot(v.x(), v.y())


@lru_cache(maxsize=64)
def font_family(path: str) -> str:
    """Load a font file into Qt and return its family name ("" if it can't be loaded)."""
    if not path or not Path(path).is_file():
        return ""
    fid = QFontDatabase.addApplicationFont(path)
    families = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
    return families[0] if families else ""


def _color(hex_color: str, alpha: float = 1.0) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def caption_paths(words: list[tuple[str, str]], style: SubtitleStyle, em: float, frame_size: tuple[float, float],
                  line_h: float) -> tuple[dict[str, QPainterPath], list[QRectF]]:
    """Words as vector outlines (so they can have strokes), one path per role, centred on (0, 0).

    Lines break exactly where the writer breaks them for CapCut (layout.breaks).
    """
    try:
        main_family = font_family(style.resolved_font())
    except RuntimeError:
        main_family = ""
    en_family = font_family(style.resolved_english_font())

    def qfont(english: bool, role: str) -> QFont:
        f = QFont(en_family if english and style.convert_to_fm else main_family or "Iskoola Pota")
        f.setPixelSize(max(1, round(em * (style.hl_scale if role == "active" else 1.0))))
        f.setBold(style.bold)
        return f

    # (text piece, font, role); a word may have a Sinhala and an English piece
    tokens: list[list[tuple[str, QFont, str]]] = []
    for word, role in words:
        for part in word.split():          # a classic subtitle is one "word" holding the whole line
            chunks = fm_runs(part) if style.convert_to_fm else [(part, False)]
            tokens.append([(t, qfont(en, role), role) for t, en in chunks if t.strip()])
    tokens = [t for t in tokens if t]

    def width_of(tok) -> float:
        return sum(QFontMetricsF(f).horizontalAdvance(t) for t, f, _ in tok)

    space = QFontMetricsF(qfont(False, "normal")).horizontalAdvance(" ")
    cuts = layout.breaks(words, style, frame_size)
    lines: list[list] = [[]]
    for i, tok in enumerate(tokens):
        lines[-1].append(tok)
        if i in cuts and i + 1 < len(tokens):
            lines.append([])

    paths = {r: QPainterPath() for r in ROLES}
    boxes = []
    top = -line_h * len(lines) / 2
    for i, line in enumerate(lines):
        total = sum(width_of(t) for t in line) + space * (len(line) - 1)
        x = -total / 2
        baseline = top + line_h * i + line_h * 0.78
        for tok in line:
            for text, f, role in tok:
                paths[role].addText(QPointF(x, baseline), f, text)
                x += QFontMetricsF(f).horizontalAdvance(text)
            x += space
        boxes.append(QRectF(-total / 2, top + line_h * i, total, line_h))
    return paths, boxes


def _reveal(words: list[tuple[str, str]], share: float) -> list[tuple[str, str]]:
    """Typewriter: only the first `share` of the letters."""
    if share >= 1:
        return words
    total = sum(len(w) for w, _ in words)
    left = int(total * share)
    out = []
    for w, r in words:
        if left <= 0:
            break
        out.append((w[:left], r))
        left -= len(w)
    return out


def paint_caption(p: QPainter, frame: QRectF, style: SubtitleStyle, cue: Cue | None,
                  t: float | None = None, text: str = SAMPLE) -> QRectF | None:
    """Draw a subtitle inside the video frame `frame`.

    With a cue and a time `t` (seconds on the timeline) we draw exactly that moment:
    the karaoke frame and the animation. Without `t` we draw a typical moment.
    """
    if cue is not None:
        local = (t - cue.start) if t is not None else cue.duration * 0.55
        f = captions.frame_at(cue, cue.start + local, style.caption_mode, style.words_per_caption, style.text_case)
        words = f.words if f else []
        fx = animations.effect_at(style.intro, style.intro_duration, style.outro, style.outro_duration,
                                  style.loop, local, cue.duration) if t is not None else animations.Fx()
    else:
        demo = Cue(0, 3, text)
        f = captions.frame_at(demo, 1.6, style.caption_mode, style.words_per_caption, style.text_case)
        words = f.words if f else [(text, "normal")]
        fx = animations.Fx()
    words = _reveal(words, fx.reveal)
    if not words or fx.alpha <= 0.01:
        return None

    # Same maths as CapCut (see capcut/metrics.py), on the frame as it is drawn on screen.
    size = (frame.width(), frame.height())
    try:
        font = style.resolved_font()
    except RuntimeError:
        font = ""
    em = metrics.em_px(style.size, style.scale, size, font)
    line_h = metrics.row_px(style.size, style.scale, size, font)
    paths, boxes = caption_paths(words, style, em, size, line_h)
    everything = QPainterPath()
    for path in paths.values():
        everything.addPath(path)
    if everything.isEmpty():
        return None

    p.save()
    p.translate(frame.center().x() + style.pos_x * frame.width() / 2 + fx.dx * em,
                frame.center().y() - style.pos_y * frame.height() / 2 + fx.dy * em)
    p.scale(fx.scale, fx.scale)
    p.setOpacity(fx.alpha)
    p.setRenderHint(QPainter.Antialiasing)
    area = everything.boundingRect()
    for b in boxes:
        area = area.united(b)
    drawn = p.transform().mapRect(area.adjusted(-em * 0.2, -em * 0.1, em * 0.2, em * 0.1))

    if style.background_enabled:
        p.setPen(Qt.NoPen)
        p.setBrush(_color(style.background_color, style.background_alpha))
        pad = em * 0.25
        for b in boxes:
            p.drawRoundedRect(b.adjusted(-pad, 0, pad, 0), pad, pad)
    if style.shadow_enabled:
        d = style.shadow_distance / 100 * em * 1.5
        a = math.radians(style.shadow_angle)
        p.save()
        p.translate(d * math.cos(a), -d * math.sin(a))
        p.fillPath(everything, _color(style.shadow_color, style.shadow_alpha))
        p.restore()
    outline = style.stroke_width * em * 1.6 if style.stroke_enabled else 0.0
    if style.glow_enabled and style.glow_width > 0:
        for k, share in ((1.0, 0.35), (0.7, 0.6), (0.45, 1.0)):     # soft edge: three layers
            pen = QPen(_color(style.glow_color, style.glow_alpha * share), outline + style.glow_width * em * 1.6 * k)
            pen.setJoinStyle(Qt.RoundJoin)
            p.strokePath(everything, pen)
    if outline:
        pen = QPen(_color(style.stroke_color), outline)
        pen.setJoinStyle(Qt.RoundJoin)
        p.strokePath(everything, pen)

    colors = {"normal": style.color, "active": style.hl_color, "spoken": style.spoken_color or style.color}
    bounds = everything.boundingRect()
    for role in ROLES:
        path = paths[role]
        if path.isEmpty():
            continue
        if style.gradient_enabled and role != "active":
            g = QLinearGradient(0, bounds.top(), 0, bounds.bottom())
            g.setColorAt(0, _color(colors[role]))
            g.setColorAt(1, _color(style.gradient_color))
            p.fillPath(path, g)
        else:
            p.fillPath(path, _color(colors[role]))
    p.restore()
    return drawn


HANDLE = 7       # half size of the corner squares
SNAP_PX = 8      # how close to the centre lines the caption snaps


class PreviewCanvas(QWidget):
    """A video frame with the subtitle drawn on it.

    Like in CapCut: drag the caption to move it, drag a corner to resize it, or use the mouse
    wheel over it. It snaps to the centre lines. Every change is sent out with `style_dragged`.
    """

    style_dragged = Signal(object)     # SubtitleStyle with a new position / scale

    def __init__(self, parent=None, editable: bool = True):
        super().__init__(parent)
        self.setMinimumSize(320, 200)
        self.editable = editable
        self.setMouseTracking(editable)
        self.caption_rect: QRectF | None = None
        self._hover = False
        self._drag: dict | None = None
        self._snap = (False, False)       # showing the vertical / horizontal guide
        self.style_ = SubtitleStyle()
        self.canvas = (1920, 1080)
        self.cover: QImage | None = None
        self.cue: Cue | None = None
        self.t: float | None = None
        self.placeholder = True
        self._loop = QTimer(self, interval=33, timeout=self.update)   # "animate" mode
        self._loop_t0 = 0.0

    def set_style(self, style: SubtitleStyle) -> None:
        self.style_ = style
        self.update()

    def set_canvas(self, size: tuple[int, int], cover: Path | None = None) -> None:
        self.canvas = size
        self.cover = QImage(str(cover)) if cover and cover.is_file() else None
        self.update()

    def show_cue(self, cue: Cue | None, t: float | None = None, placeholder: bool = True) -> None:
        """Show `cue` at time t (None: a typical moment). No cue: sample text, or nothing while playing."""
        self.cue, self.t, self.placeholder = cue, t, placeholder
        self.update()

    def set_animate(self, on: bool) -> None:
        """Replay the shown subtitle again and again, so style and animation changes can be seen."""
        self._loop_t0 = time.monotonic()
        self._loop.start() if on else self._loop.stop()
        self.update()

    def animating(self) -> bool:
        return self._loop.isActive()

    def frame_rect(self) -> QRectF:
        w, h = self.canvas
        area = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        scale = min(area.width() / w, area.height() / h)
        fw, fh = w * scale, h * scale
        return QRectF(area.center().x() - fw / 2, area.center().y() - fh / 2, fw, fh)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        fr = self.frame_rect()
        p.fillRect(fr, QColor("#0B0C0E"))
        if self.cover and not self.cover.isNull():
            img = self.cover.scaled(fr.size().toSize(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            src = QRectF((img.width() - fr.width()) / 2, (img.height() - fr.height()) / 2, fr.width(), fr.height())
            p.drawImage(fr, img, src)
            p.fillRect(fr, QColor(0, 0, 0, 70))
        p.setClipRect(fr)
        self.caption_rect = None
        cue, t = self.cue, self.t
        if self._loop.isActive():
            cue = cue or Cue(0, 3, SAMPLE)
            cycle = cue.duration + 0.6                     # a short pause before it starts again
            t = cue.start + (time.monotonic() - self._loop_t0) % cycle
            if t >= cue.end:                               # the pause: the subtitle has gone
                p.end()
                return
        if cue is not None:
            self.caption_rect = paint_caption(p, fr, self.style_, cue, t)
        elif self.placeholder:
            self.caption_rect = paint_caption(p, fr, self.style_, None)
        if self.editable and self.caption_rect is not None and (self._hover or self._drag):
            self._paint_handles(p, fr)
        p.end()

    # --- dragging (CapCut-style) ------------------------------------------------------------------

    def _corners(self) -> list[QPointF]:
        r = self.caption_rect
        return [r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()] if r else []

    def _paint_handles(self, p: QPainter, fr: QRectF) -> None:
        from . import theme
        accent = QColor(theme.ACCENT)
        if self._drag and self._snap[0]:
            p.setPen(QPen(accent, 1, Qt.DashLine))
            p.drawLine(QPointF(fr.center().x(), fr.top()), QPointF(fr.center().x(), fr.bottom()))
        if self._drag and self._snap[1]:
            p.setPen(QPen(accent, 1, Qt.DashLine))
            p.drawLine(QPointF(fr.left(), fr.center().y()), QPointF(fr.right(), fr.center().y()))
        p.setPen(QPen(QColor(255, 255, 255, 220), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(self.caption_rect)
        p.setBrush(QColor("white"))
        for c in self._corners():
            p.drawRect(QRectF(c.x() - HANDLE / 2, c.y() - HANDLE / 2, HANDLE, HANDLE))

    def _hit(self, pos: QPointF) -> str:
        """'corner', 'body' or '' for the mouse position."""
        if not (self.editable and self.caption_rect):
            return ""
        if any(abs(pos.x() - c.x()) <= HANDLE and abs(pos.y() - c.y()) <= HANDLE for c in self._corners()):
            return "corner"
        return "body" if self.caption_rect.adjusted(-4, -4, 4, 4).contains(pos) else ""

    def _emit(self, **changes) -> None:
        from dataclasses import replace
        self.style_ = replace(self.style_, **changes)
        self.update()
        self.style_dragged.emit(self.style_)

    def mousePressEvent(self, e) -> None:
        part = self._hit(e.position())
        if e.button() != Qt.LeftButton or not part:
            return super().mousePressEvent(e)
        r = self.caption_rect
        self._drag = {"part": part, "start": e.position(), "x": self.style_.pos_x, "y": self.style_.pos_y,
                      "scale": self.style_.scale, "center": r.center(),
                      "dist": max(8.0, _length(e.position() - r.center()))}
        self.update()

    def mouseMoveEvent(self, e) -> None:
        pos = e.position()
        if not self._drag:
            part = self._hit(pos)
            self.setCursor(Qt.SizeFDiagCursor if part == "corner" else Qt.SizeAllCursor if part else Qt.ArrowCursor)
            if self._hover != bool(part):
                self._hover = bool(part)
                self.update()
            return
        d, fr = self._drag, self.frame_rect()
        if d["part"] == "corner":
            scale = d["scale"] * _length(pos - d["center"]) / d["dist"]
            self._emit(scale=round(max(0.2, min(4.0, scale)), 3))
            return
        delta = pos - d["start"]
        x = d["x"] + delta.x() / (fr.width() / 2)
        y = d["y"] - delta.y() / (fr.height() / 2)
        snap_x = abs(x) * fr.width() / 2 < SNAP_PX       # close to the vertical centre line
        snap_y = abs(y) * fr.height() / 2 < SNAP_PX
        self._snap = (snap_x, snap_y)
        self._emit(pos_x=0.0 if snap_x else round(max(-1.2, min(1.2, x)), 4),
                   pos_y=0.0 if snap_y else round(max(-1.2, min(1.2, y)), 4))

    def mouseReleaseEvent(self, e) -> None:
        if self._drag:
            self._drag = None
            self._snap = (False, False)
            self.update()
        super().mouseReleaseEvent(e)

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def wheelEvent(self, e) -> None:
        if self._hit(e.position()):
            steps = (e.angleDelta().y() or e.angleDelta().x()) / 120
            self._emit(scale=round(max(0.2, min(4.0, self.style_.scale * 1.05 ** steps)), 3))
        else:
            super().wheelEvent(e)
