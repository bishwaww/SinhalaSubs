"""Run slow jobs (ffmpeg, Gemini) on a background thread so the window never freezes.

Qt widgets may only be touched from the main thread, so the worker talks back
through signals: Qt delivers them safely to the main thread.
"""

from __future__ import annotations

import re
import traceback
from typing import Callable

from PySide6.QtCore import QThread, Signal

_PROGRESS = re.compile(r"Transcribed (\d+)/(\d+)")


class Task(QThread):
    log = Signal(str)
    progress = Signal(int, int)          # done, total
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable, *args, parent=None, **kwargs):
        """Runs fn(*args, log=..., cancelled=..., **kwargs) when started."""
        super().__init__(parent)
        self._fn, self._args, self._kwargs = fn, args, kwargs
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def cancelled(self) -> bool:
        return self._cancel

    def _log(self, text: str) -> None:
        self.log.emit(text)
        m = _PROGRESS.search(text)
        if m:
            self.progress.emit(int(m.group(1)), int(m.group(2)))

    def run(self) -> None:
        try:
            result = self._fn(*self._args, log=self._log, cancelled=self.cancelled, **self._kwargs)
        except Exception as e:  # noqa: BLE001 - show every failure to the user
            self.log.emit(traceback.format_exc(limit=3))
            self.failed.emit(str(e) or e.__class__.__name__)
        else:
            self.succeeded.emit(result)
