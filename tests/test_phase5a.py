import json
import os
import wave
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sinhalasubs import timing  # noqa: E402
from sinhalasubs.capcut import metrics, writer  # noqa: E402
from sinhalasubs.models import Cue  # noqa: E402
from sinhalasubs.style import SubtitleStyle, find_font  # noqa: E402
from sinhalasubs.waveform import compute_peaks  # noqa: E402


def cues3():
    return [Cue(0, 2, "එක දෙක"), Cue(3, 5, "තුන හතර"), Cue(5, 7, "පහ හය")]


# --- timing -------------------------------------------------------------------------------------

def test_move_stops_at_neighbours():
    cues = cues3()
    used = timing.move(cues, [1], [(3, 5)], -5)       # try to move 5s left: only 1s is free
    assert used == -1 and (cues[1].start, cues[1].end) == (2, 4)
    used = timing.move(cues, [1], [(3, 5)], +3)       # right side is touching the next cue
    assert used == 0


def test_move_group_together():
    cues = cues3()
    timing.move(cues, [1, 2], [(3, 5), (5, 7)], -0.5)
    assert [(c.start, c.end) for c in cues[1:]] == [(2.5, 4.5), (4.5, 6.5)]


def test_trim_and_roll():
    cues = cues3()
    assert timing.trim(cues, 1, "start", 1.0) == 2      # can't go into the previous cue
    timing.trim(cues, 1, "end", 5.8, roll=True)         # roll pushes the touching neighbour
    assert cues[1].end == 5.8 and cues[2].start == 5.8
    timing.trim(cues, 0, "end", 0.0)
    assert cues[0].end == pytest.approx(timing.MIN_LEN)


def test_split_and_merge():
    cues = cues3()
    new = timing.split(cues, 0, 1.0)
    assert new == 1 and cues[0].text == "එක" and cues[1].text == "දෙක" and cues[1].start == 1.0
    i = timing.merge(cues, [0, 1])
    assert i == 0 and cues[0].text == "එක දෙක" and (cues[0].start, cues[0].end) == (0, 2)


def test_cleanup_tools():
    cues = [Cue(0, 3, "a"), Cue(2, 4, "b"), Cue(4.1, 4.3, "c")]
    assert timing.fix_overlaps(cues) == 1 and cues[0].end == 2
    assert timing.close_gaps(cues, 0.3) == 1 and cues[1].end == 4.1
    assert timing.min_duration(cues, 1.0) == 1 and cues[2].end == pytest.approx(5.1)
    timing.shift_all(cues, -10)
    assert cues[0].start == 0


# --- CapCut metrics --------------------------------------------------------------------------------

def test_span_formula_matches_capcut_measurement():
    # CapCut: 1080×1920, size 24.38, scale 0.56 → span ≈ 24.38 × 0.56 × 1080 / 150
    assert metrics.span_px(24.38, 0.56, (1080, 1920)) == pytest.approx(98.3, abs=0.1)


@pytest.mark.skipif(not find_font("arialbd"), reason="needs Arial Bold")
def test_english_run_gets_matched_size():
    style = SubtitleStyle(font_path=find_font("arialbd"), english_font_path=find_font("arialbd"), size=12)
    runs = json.loads(writer.content_json("මම layer", style))["styles"]
    assert runs[1]["size"] == 12          # same font → same size
    fm = find_font("FM-")
    if fm:
        style.font_path = fm
        runs = json.loads(writer.content_json("මම layer", style))["styles"]
        assert runs[1]["size"] == pytest.approx(metrics.matched_size(12, fm, find_font("arialbd")), abs=0.01)


def test_bad_font_file_gives_default_span(tmp_path):
    bad = tmp_path / "x.ttf"
    bad.write_bytes(b"not a font")
    assert metrics.span_ratio(str(bad)) == metrics.DEFAULT_SPAN


# --- waveform ----------------------------------------------------------------------------------------

def test_peaks_follow_loudness(tmp_path):
    import array
    path = tmp_path / "a.wav"
    loud = array.array("h", [20000, -20000] * 800)       # 0.1 s loud
    quiet = array.array("h", [0] * 1600)                  # 0.1 s silence
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(loud.tobytes() + quiet.tobytes())
    peaks = compute_peaks(path, 0.1)
    assert len(peaks) == 2 and peaks[0] > 200 and peaks[1] == 0


# --- window: timeline drag + undo -------------------------------------------------------------------

@pytest.fixture
def win(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    monkeypatch.setenv("APPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    from sinhalasubs.config import Settings
    (tmp_path / "no_projects").mkdir()
    Settings(drafts_root=str(tmp_path / "no_projects")).save()   # never read the real CapCut folder
    from sinhalasubs.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    app.processEvents()
    yield w
    w.close()


def test_timeline_drag_moves_cue_and_undo_restores(win):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    win.set_cues(cues3(), undoable=False)
    tl = win.timeline
    tl.set_duration(10)
    tl.pps, tl.offset = 50.0, 0.0                   # 50 px per second
    y = 22 + 20                                      # inside the subtitle lane
    # drag the middle of cue 2 (3–5 s → x 150–250) left by 25 px = 0.5 s
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(200, y))
    QTest.mouseMove(tl, QPoint(185, y))
    QTest.mouseMove(tl, QPoint(175, y))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(175, y))
    assert (win.cues[1].start, win.cues[1].end) == pytest.approx((2.5, 4.5))
    assert win.table.model_.data(win.table.model_.index(1, 1)) == "0:02.50"   # table follows

    win.undo()
    assert (win.cues[1].start, win.cues[1].end) == (3, 5)
    win.redo()
    assert win.cues[1].start == pytest.approx(2.5)


def test_timeline_edge_trim(win):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    win.set_cues(cues3(), undoable=False)
    tl = win.timeline
    tl.pps, tl.offset = 50.0, 0.0
    y = 42
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(100, y))   # end edge of cue 1 (2 s)
    QTest.mouseMove(tl, QPoint(120, y))
    QTest.mouseMove(tl, QPoint(125, y))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(125, y))
    assert win.cues[0].end == pytest.approx(2.5)


def test_table_edit_is_undoable(win):
    win.set_cues(cues3(), undoable=False)
    m = win.table.model_
    m.setData(m.index(0, 3), "වෙනස් කළා")
    assert win.cues[0].text == "වෙනස් කළා"
    win.undo()
    assert win.cues[0].text == "එක දෙක"


def test_prepare_audio_is_cached(tmp_path, monkeypatch):
    from sinhalasubs import audio, pipeline
    monkeypatch.setenv("APPDATA", str(tmp_path))
    src = tmp_path / "tone.wav"
    r = audio.run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=300:duration=2", "-y", str(src)])
    assert r.returncode == 0
    wav, total = pipeline.prepare_audio(src)
    assert abs(total - 2.0) < 0.1
    mtime = wav.stat().st_mtime_ns
    wav2, _ = pipeline.prepare_audio(src)
    assert wav2 == wav and Path(wav2).stat().st_size > 0 and wav.stat().st_mtime_ns >= mtime


def test_window_fits_the_screen(win):
    from PySide6.QtWidgets import QApplication
    win.fit_to_screen()
    avail = QApplication.primaryScreen().availableGeometry()
    least = win.minimumSizeHint()          # the test screen can be smaller than the window's minimum
    assert win.width() <= max(avail.width(), least.width())
    assert win.height() <= max(avail.height(), least.height())


def test_close_video_leaves_video_mode(win, tmp_path):
    from sinhalasubs import audio
    video = tmp_path / "clip.wav"
    assert audio.run_ffmpeg(["-f", "lavfi", "-i", "sine=duration=1", "-y", str(video)]).returncode == 0
    win.video = video
    win._set_session(str(video))
    win.set_cues(cues3())
    win._update_buttons()
    assert win.close_video_btn.isVisibleTo(win)
    win.close_video()
    assert win.video is None and win.cues == [] and not win.close_video_btn.isVisibleTo(win)
    win.video = video
    win._set_session(str(video))            # opening it again brings the subtitles back
    assert len(win.cues) == 3


def test_drag_caption_on_preview_moves_and_snaps(win):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    pv = win.preview
    pv.resize(800, 450)
    pv.show_cue(Cue(0, 2, "එක දෙක"))
    pv.repaint()
    r = pv.caption_rect
    assert r is not None
    start = r.center().toPoint()
    fr = pv.frame_rect()
    QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(pv, start + QPoint(0, -int(fr.height() / 4)))       # a quarter of the frame up
    QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, start + QPoint(0, -int(fr.height() / 4)))
    assert win.style_.pos_y == pytest.approx(-0.75 + 0.5, abs=0.02)     # moved up by half the half-height
    assert win.style_panel.pos_y.value() == round(win.style_.pos_y * 100)   # the panel follows
    assert win.style_.pos_x == 0.0                                       # stayed on the centre line

    pv.repaint()
    corner = pv.caption_rect.bottomRight().toPoint()
    far = corner + (corner - pv.caption_rect.center().toPoint())         # twice as far from the centre
    QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, corner)
    QTest.mouseMove(pv, far)
    QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, far)
    assert win.style_.scale == pytest.approx(2.0, abs=0.15)
