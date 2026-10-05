"""`SinhalaSubs.exe --selftest`: check that the packed app has everything it needs.

The .exe has no console, so the result is written to a file (path printed/shown).
"""

from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path


def run() -> int:
    lines, ok = [], True

    def check(name, fn):
        nonlocal ok
        try:
            lines.append(f"OK    {name}: {fn()}")
        except Exception as e:  # noqa: BLE001
            ok = False
            lines.append(f"FAIL  {name}: {e!r}")
            lines.append(traceback.format_exc(limit=2))

    def ffmpeg():
        from . import audio
        r = audio.run_ffmpeg(["-version"])
        return r.stdout.splitlines()[0]

    def data_files():
        from .fm_converter import load_rules, unicode_to_fm
        from .animations import catalog
        from .capcut.writer import _template
        return f"{len(load_rules())} FM rules, {sum(map(len, catalog().values()))} animations, " \
               f"template {len(_template()['material'])} fields, 'අම්මා'→{unicode_to_fm('අම්මා')!r}"

    def qt():
        from PySide6.QtWidgets import QApplication
        from PySide6 import QtMultimedia  # noqa: F401
        app = QApplication.instance() or QApplication([])
        from .ui.main_window import MainWindow
        w = MainWindow()
        w.close()
        return f"window ok, {w.projects.count()} CapCut projects"

    def gemini_sdk():
        from google import genai  # noqa: F401
        return "google-genai imports"

    def whisper():
        import ctranslate2
        import faster_whisper
        vad = Path(faster_whisper.__file__).parent / "assets" / "silero_vad_v6.onnx"
        return f"faster-whisper {faster_whisper.__version__}, ctranslate2 {ctranslate2.__version__}, VAD model {vad.is_file()}"

    for name, fn in (("ffmpeg", ffmpeg), ("data files", data_files), ("Gemini SDK", gemini_sdk),
                     ("Whisper", whisper), ("Qt window", qt)):
        check(name, fn)

    report = Path(tempfile.gettempdir()) / "sinhalasubs_selftest.txt"
    report.write_text(("PASS\n" if ok else "FAIL\n") + "\n".join(lines), encoding="utf-8")
    if sys.stdout is not None:
        try:                                # an old console code page can't show Sinhala
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
        print(report.read_text(encoding="utf-8"))
    return 0 if ok else 1
