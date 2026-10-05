"""Writing subtitles the way CapCut stores its own Auto captions."""

import json

from sinhalasubs.capcut import writer
from sinhalasubs.capcut.project import list_timelines
from sinhalasubs.models import Cue
from sinhalasubs.style import SubtitleStyle

from .test_phase3 import CUES, STYLE, TL, project  # noqa: F401


def _empty():
    return {"id": "D", "materials": {}, "tracks": [], "duration": 0, "config": {"subtitle_taskinfo": []}}


def test_captions_look_like_capcut_auto_captions():
    data = _empty()
    stats = writer.apply_subtitles(data, CUES, STYLE, as_captions=True)
    assert stats["as_captions"]
    [track] = data["tracks"]
    assert track["flag"] == 1                                   # CapCut's caption track
    mats = data["materials"]["texts"]
    assert {m["type"] for m in mats} == {"subtitle"}
    assert len({m["group_id"] for m in mats}) == 1              # one linked group ("apply to all")
    [task] = data["config"]["subtitle_taskinfo"]
    assert all(m["recognize_task_id"] == task["id"] for m in mats)


def test_caption_words_join_back_to_the_clip_text():
    data = _empty()
    writer.apply_subtitles(data, [Cue(1.0, 3.0, "අලුත් layer එකක්")], STYLE, as_captions=True)
    [m] = data["materials"]["texts"]
    body = json.loads(m["content"])["text"]
    w = m["words"]
    assert "".join(w["text"]) == body == m["recognize_text"]
    assert w["text"][1] == " " and w["start_time"][0] == 0 and w["end_time"][-1] == 2000
    assert w["start_time"] == sorted(w["start_time"])


def test_karaoke_falls_back_to_text_clips():
    style = SubtitleStyle(**{**STYLE.__dict__, "caption_mode": "karaoke"})
    data = _empty()
    stats = writer.apply_subtitles(data, CUES, style, as_captions=True)
    assert not stats["as_captions"] and data["tracks"][0]["flag"] == 0
    assert data["config"]["subtitle_taskinfo"] == []


def test_replacing_captions_removes_our_task_only():
    data = _empty()
    data["config"]["subtitle_taskinfo"].append({"id": "capcut_own_task"})
    writer.apply_subtitles(data, CUES, STYLE, as_captions=True)
    writer.apply_subtitles(data, CUES[:1], STYLE, as_captions=True)
    ids = [t["id"] for t in data["config"]["subtitle_taskinfo"]]
    assert ids[0] == "capcut_own_task" and len(ids) == 2
    assert len(data["tracks"]) == 1 and len(data["materials"]["texts"]) == 1


def test_all_copies_of_a_timeline_get_the_same_ids(project):  # noqa: F811
    writer.write_to_draft(project, list_timelines(project)[0], CUES, STYLE)
    a = json.loads((project / "draft_content.json").read_text(encoding="utf-8"))
    b = json.loads((project / "Timelines" / TL / "draft_content.json").read_text(encoding="utf-8"))
    assert a == b
