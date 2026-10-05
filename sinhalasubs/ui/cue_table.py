"""The subtitle list: an editable table of start, end and text."""

from __future__ import annotations

import re

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

from ..models import Cue
from ..sinhala_script import has_foreign

COLS = ("#", "Start", "End", "Text", "CPS")
MAX_CPS = 20  # characters per second above this are hard to read


def fmt_time(t: float) -> str:
    """75.5 -> '1:15.50'"""
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m)}:{s:05.2f}"


def parse_time(text: str) -> float:
    """'1:15.5', '75.5' or '0:01:15.5' -> seconds."""
    parts = [float(p) for p in re.split(r"[:]", text.strip().replace(",", "."))]
    t = 0.0
    for p in parts:
        t = t * 60 + p
    return t


def cps(c: Cue) -> float:
    letters = len(c.text.replace(" ", ""))
    return letters / c.duration if c.duration > 0 else 0.0


class CueModel(QAbstractTableModel):
    about_to_edit = Signal()   # before a cell changes (so the window can save an undo step)
    edited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cues: list[Cue] = []

    def set_cues(self, cues: list[Cue]) -> None:
        self.beginResetModel()
        self.cues = cues
        self.endResetModel()

    def refresh(self) -> None:
        """Redraw every row (after the cues were changed from outside, e.g. the timeline)."""
        if self.cues:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.cues) - 1, len(COLS) - 1))

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.cues)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        c = self.cues[index.row()]
        col = index.column()
        if role in (Qt.DisplayRole, Qt.EditRole):
            return (index.row() + 1, fmt_time(c.start), fmt_time(c.end), c.text, f"{cps(c):.0f}")[col]
        if role == Qt.BackgroundRole:
            if has_foreign(c.text):
                return QColor(229, 83, 75, 70)
            if col == 4 and cps(c) > MAX_CPS:
                return QColor(232, 163, 61, 70)
        if role == Qt.ToolTipRole:
            if has_foreign(c.text):
                return "Has letters from another script (Malayalam, Hindi…). Use 'Fix script'."
            if col == 4:
                return "Characters per second. Above 20 is hard to read."
        if role == Qt.TextAlignmentRole and col != 3:
            return int(Qt.AlignCenter)
        return None

    def flags(self, index):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return f | Qt.ItemIsEditable if index.column() in (1, 2, 3) else f

    def setData(self, index, value, role=Qt.EditRole) -> bool:
        if role != Qt.EditRole:
            return False
        c = self.cues[index.row()]
        if self.data(index, Qt.EditRole) == value:
            return False
        self.about_to_edit.emit()
        try:
            if index.column() == 1:
                c.start = min(parse_time(value), c.end - 0.05)
            elif index.column() == 2:
                c.end = max(parse_time(value), c.start + 0.05)
            elif index.column() == 3:
                c.text = str(value).strip()
            else:
                return False
        except ValueError:
            return False
        self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), len(COLS) - 1))
        self.edited.emit()
        return True


class CueTable(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_ = CueModel(self)
        self.setModel(self.model_)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setWordWrap(True)
        self.verticalHeader().hide()
        h = self.horizontalHeader()
        for col, mode in enumerate((QHeaderView.ResizeToContents, QHeaderView.ResizeToContents,
                                    QHeaderView.ResizeToContents, QHeaderView.Stretch,
                                    QHeaderView.ResizeToContents)):
            h.setSectionResizeMode(col, mode)

    def selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.selectionModel().selectedRows()})
