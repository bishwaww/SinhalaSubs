import json
import os
import sys
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sinhalasubs import animations, caption_presets, captions  # noqa: E402
from sinhalasubs.capcut import writer  # noqa: E402
from sinhalasubs.models import Cue  # noqa: E402
from sinhalasubs.style import SubtitleStyle  # noqa: E402

FONTS = dict(font_path="C:/Fonts/FM-Abhaya.ttf", english_font_path="C:/Fonts/arialbd.ttf")
CUE = Cue(0.0, 4.0, "එක දෙක තුන හතර")


# --- captions -----------------------------------------------------------------------------------------

def test_karaoke_frames_cover_the_cue_and_move_the_highlight():
    fr = captions.frames(CUE, "karaoke")
    assert len(fr) == 4
    assert fr[0].start == 0.0 and fr[-1].end == 4.0
    assert all(a.end == b.start for a, b in zip(fr, fr[1:]))          # no gaps, no overlaps
    assert [r for _, r in fr[2].words] == ["spoken", "spoken", "active", "normal"]


def test_pages_reveal_single_keyword():
    pages = captions.frames(CUE, "karaoke", per_page=2)
    assert [len(f.words) for f in pages] == [2, 2, 2, 2]
    assert pages[2].words[0] == ("තුන", "active")
    reveal = captions.frames(CUE, "reveal")
    assert [len(f.words) for f in reveal] == [1, 2, 3, 4]
    single = captions.frames(CUE, "single")
    assert [f.words for f in single][1] == [("දෙක", "active")]
    [kw] = captions.frames(Cue(0, 2, "මම photoshop පාවිච්චි"), "keyword")
    assert kw.words[1] == ("photoshop", "active")


def test_text_case_only_changes_english():
    [f] = captions.frames(Cue(0, 1, "අලුත් layer එකක්"), "classic", case="upper")
    assert f.text == "අලුත් LAYER එකක්"


def test_real_word_times_follow_a_moved_cue():
    c = Cue(10.0, 12.0, "එක දෙක")
    c.words = [(10.0, 10.5, "එක"), (10.5, 12.0, "දෙක")]
    c.start, c.end = 20.0, 24.0                    # moved and stretched ×2 on the timeline
    w = captions.word_times(c)
    assert (w[1].start, w[1].end) == pytest.approx((21.0, 24.0))
    c.text = "එක තුන"                              # edited: fall back to estimated times
    assert captions.word_times(c)[0].end != pytest.approx(21.0)


# --- writer ---------------------------------------------------------------------------------------------

def _apply(style, cues):
    data = {"materials": {}, "tracks": [], "duration": 0}
    writer.apply_subtitles(data, cues, style)
    return data


def test_karaoke_writes_one_clip_per_frame_with_colours():
    style = SubtitleStyle(**FONTS, caption_mode="karaoke", hl_color="#FF0000", convert_to_fm=False)
    data = _apply(style, [CUE])
    [track] = data["tracks"]
    assert len(track["segments"]) == 4
    third = json.loads(data["materials"]["texts"][2]["content"])
    colors = [r["fill"]["content"]["solid"]["color"] for r in third["styles"]]
    assert colors[2] == [1.0, 0.0, 0.0] and colors[3] == [1.0, 1.0, 1.0]
    assert third["text"] == CUE.text


def test_animations_only_on_first_and_last_frame():
    style = SubtitleStyle(**FONTS, caption_mode="karaoke", intro="pop_up", outro="fade_out", loop="flash")
    data = _apply(style, [CUE])
    anims = data["materials"]["material_animations"]
    kinds = [[a["type"] for a in m["animations"]] for m in anims]
    assert kinds[0] == ["in", "loop"] and kinds[1] == ["loop"] and kinds[-1] == ["out", "loop"]
    first = anims[0]["animations"][0]
    assert first["resource_id"] == animations.get("pop_up").resource_id and first["category_id"] == "ruchang"


def test_short_clip_shares_time_between_in_and_out():
    style = SubtitleStyle(**FONTS, intro="fade_in", intro_duration=1.0, outro="fade_out", outro_duration=1.0)
    data = _apply(style, [Cue(0, 1.0, "කෙටි")])
    durs = [a["duration"] for a in data["materials"]["material_animations"][0]["animations"]]
    assert sum(durs) <= 1_000_000


def test_glow_is_a_capcut_bloom_effect_and_gradient_format():
    style = SubtitleStyle(**FONTS, glow_enabled=True, glow_alpha=0.5, glow_width=0.25, glow_color="#00FF66",
                          gradient_enabled=True, gradient_color="#000000")
    run = json.loads(writer.content_json("හරි", style))["styles"][0]
    assert len(run["strokes"]) == 1                            # CapCut draws one outline only
    grad = run["fill"]["content"]
    assert grad["render_type"] == "gradient" and grad["gradient"]["color"][1] == [0.0, 0.0, 0.0]

    data = _apply(style, [Cue(0, 2, "හරි")])
    [glow] = data["materials"]["effects"]
    assert glow["type"] == "bloom" and glow["panel_id"] == "text_glow"
    assert glow["bloom_params"] == {"color": "#00FF66", "strength": 0.5, "range": 0.25, "dir_x": 0.5, "dir_y": 0.5}
    [seg] = data["tracks"][0]["segments"]
    assert glow["id"] in seg["extra_material_refs"]
    assert data["materials"]["texts"][0]["check_flag"] & writer.GLOW_FLAG
    writer.remove_existing(data)
    assert data["materials"]["effects"] == []


def test_long_lines_are_broken_for_capcut():
    from sinhalasubs import layout
    style = SubtitleStyle(**FONTS, convert_to_fm=False, size=20)
    words = [("අද අපි අලුත් video එකක් හදලා ඒක ගැන කතා කරමු", "normal")]
    cuts = layout.breaks(words, style, (1080, 1920))
    assert cuts                                                  # too long for one line on a phone video
    data = {"materials": {}, "tracks": [], "duration": 0, "canvas_config": {"width": 1080, "height": 1920}}
    writer.apply_subtitles(data, [Cue(0, 3, words[0][0])], style, as_captions=False)
    text = json.loads(data["materials"]["texts"][0]["content"])["text"]
    assert text.count("\n") == len(cuts)


def test_balanced_breaks():
    from sinhalasubs.layout import balanced_breaks
    assert balanced_breaks([10, 10, 10], 1, 100) == set()               # fits: one line
    assert balanced_breaks([30, 30, 30, 30], 2, 70) == {1}              # 2 + 2, not 3 + 1... (fits 2 per line)
    assert balanced_breaks([40, 40, 40, 5], 2, 90) == {1}               # even split: 82 | 47


# --- looks ----------------------------------------------------------------------------------------------

def test_look_keeps_font_size_and_position():
    mine = SubtitleStyle(**FONTS, size=20, pos_y=0.5, glow_enabled=True)
    look = next(l for l in caption_presets.BUILTIN if l.name == "Yellow Box")
    out = look.apply(mine)
    assert (out.size, out.pos_y, out.font_path) == (20, 0.5, FONTS["font_path"])
    assert out.background_enabled and not out.glow_enabled          # old look settings are reset


def test_user_looks_and_favourites(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    caption_presets.save_user_look("මගේ look", SubtitleStyle(color="#123456"))
    [mine] = caption_presets.user_looks()
    assert mine.values["color"] == "#123456" and "size" not in mine.values
    caption_presets.set_favourite("මගේ look", True)
    assert "මගේ look" in caption_presets.favourites()
    caption_presets.delete_user_look("මගේ look")
    assert caption_presets.user_looks() == []


# --- whisper -------------------------------------------------------------------------------------------

def test_whisper_words_group_into_subtitles():
    from sinhalasubs.whisper_engine import words_to_cues
    words = [(0.0, 0.4, " මම"), (0.4, 0.9, " ගෙදර"), (0.9, 1.3, " ගියා."),     # sentence end
             (1.4, 1.8, " අද"), (3.0, 3.5, " හෙට")]                               # long pause before හෙට
    cues = words_to_cues(words, max_chars=40, max_dur=6)
    assert [c.text for c in cues] == ["මම ගෙදර ගියා.", "අද", "හෙට"]
    assert cues[0].words[1] == (0.4, 0.9, "ගෙදර")


def test_whisper_engine_with_fake_model(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from sinhalasubs import whisper_engine
    from sinhalasubs.transcribe import TranscribeOptions

    class FakeModel:
        def __init__(self, name, **kw):
            self.name = name

        def transcribe(self, path, **kw):
            assert kw["language"] == "si" and kw["word_timestamps"]
            w = SimpleNamespace
            seg = w(start=0.0, end=1.0, words=[w(start=0.0, end=0.5, word=" ආයුබෝවන්"),
                                               w(start=0.5, end=1.0, word=" ලංකාව")])
            return iter([seg]), None

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeModel))
    cues = whisper_engine.transcribe(tmp_path / "a.wav", 1.0, TranscribeOptions(engine="whisper"), print)
    assert [c.text for c in cues] == ["ආයුබෝවන් ලංකාව"]


# --- UI -------------------------------------------------------------------------------------------------

@pytest.fixture
def qapp(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_every_look_renders(qapp):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    from sinhalasubs.ui.preview import paint_caption
    img = QImage(480, 270, QImage.Format_ARGB32)
    for look in caption_presets.BUILTIN:
        style = look.apply(SubtitleStyle())
        for t in (0.05, 1.0, 3.9):
            img.fill(0)
            p = QPainter(img)
            paint_caption(p, QRectF(0, 0, 480, 270), style, CUE, t)
            p.end()


def test_caption_studio_applies_a_look(qapp):
    from sinhalasubs.ui.caption_studio import CaptionStudio
    d = CaptionStudio(SubtitleStyle(size=18))
    assert d.grid.count() == len(caption_presets.all_looks())
    for i in range(d.grid.count()):
        if d.grid.item(i).data(0x0100).name == "Neon Pink":      # Qt.UserRole
            d.grid.setCurrentRow(i)
    assert d.result_style.glow_enabled and d.result_style.glow_color == "#FF4FD8"
    assert d.result_style.size == 18
    d.cats.button(caption_presets.CATEGORIES.index("Karaoke")).click()
    assert all(d.grid.item(i).data(0x0100).category == "Karaoke" for i in range(d.grid.count()))
    d.reject()
