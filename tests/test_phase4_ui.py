"""The window, driven by code with an invisible ("offscreen") screen."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from sinhalasubs.capcut import writer  # noqa: E402
from sinhalasubs.config import Settings  # noqa: E402
from sinhalasubs.models import Cue  # noqa: E402

from .test_phase3 import TL, project  # noqa: E402,F401  (re-use the fake CapCut project)


def wait_until(condition, seconds: float = 15.0) -> None:
    import time
    end = time.monotonic() + seconds
    while not condition() and time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    assert condition()


@pytest.fixture
def window(project, monkeypatch):  # noqa: F811
    app = QApplication.instance() or QApplication([])
    s = Settings(drafts_root=str(project.parent))
    s.save()
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr("sinhalasubs.ui.main_window.is_capcut_running", lambda: False)
    from sinhalasubs.ui.main_window import MainWindow
    w = MainWindow()
    yield w
    w.close()
    app.processEvents()


def test_project_list_and_tracks(window):
    assert window.projects.count() == 1
    window.projects.setCurrentRow(0)
    assert window.timeline_box.count() == 1
    assert window.track.count() == 1
    assert not window.generate_btn.isEnabled()   # waits while the audio is being prepared
    wait_until(lambda: window.audio_task is None)
    assert window.generate_btn.isEnabled()
    assert not window.write_btn.isEnabled()      # nothing to write yet


def test_edit_merge_split_and_write(window, project):
    window.projects.setCurrentRow(0)
    window.set_cues([Cue(0.5, 2.0, "අලුත් layer"), Cue(2.5, 4.0, "එකක් හදමු")])
    model = window.table.model_

    model.setData(model.index(0, 3), "ආයුබෝවන් ලංකාව")
    model.setData(model.index(1, 2), "0:05.00")
    assert window.cues[0].text == "ආයුබෝවන් ලංකාව" and window.cues[1].end == 5.0

    window.table.selectRow(0)
    window.merge_cues()
    assert len(window.cues) == 1 and window.cues[0].text == "ආයුබෝවන් ලංකාව එකක් හදමු"
    window.table.selectRow(0)
    window.split_cue()
    assert len(window.cues) == 2

    window.write_capcut()
    data = json.loads((project / "Timelines" / TL / "draft_content.json").read_text(encoding="utf-8"))
    [track] = [t for t in data["tracks"] if t.get("name") == writer.TRACK_NAME]
    assert len(track["segments"]) == 2


def test_red_rows_for_wrong_script(window):
    window.set_cues([Cue(0, 1, "හോමප"), Cue(1, 2, "හරි")])
    model = window.table.model_
    assert model.data(model.index(0, 3), Qt.BackgroundRole) is not None
    assert model.data(model.index(1, 3), Qt.BackgroundRole) is None
    assert "1 need fixing" in window.count_label.text()


def test_session_survives_restart(window, project):
    window.projects.setCurrentRow(0)
    window.set_cues([Cue(0, 1, "මතක තියාගන්න")])
    window._save_session()
    from sinhalasubs.ui.main_window import MainWindow
    again = MainWindow()
    again.projects.setCurrentRow(0)
    assert [c.text for c in again.cues] == ["මතක තියාගන්න"]
    again.close()


def test_settings_dialog_saves_encrypted_key(window):
    from sinhalasubs.ui.settings_dialog import SettingsDialog
    d = SettingsDialog(window.settings, window)
    d.key.setText("AIza-from-dialog")
    d.glossary.setPlainText("කසුන්, Photoshop")
    d.accept()
    loaded = Settings.load()
    assert loaded.api_key == "AIza-from-dialog"
    assert loaded.glossary == ["කසුන්", "Photoshop"]
    assert "AIza-from-dialog" not in Settings.path().read_text()
