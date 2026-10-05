"""CapCut reading/writing, tested on a small fake project built in a temp folder."""

import json
import sys

import pytest

from sinhalasubs import config
from sinhalasubs.capcut import writer
from sinhalasubs.capcut.project import Draft, list_projects, list_timelines
from sinhalasubs.models import Cue
from sinhalasubs.style import SubtitleStyle

TL = "AAAA-1111"


def _draft(draft_id="D1", texts=()):
    return {
        "id": draft_id, "duration": 5_000_000, "canvas_config": {"width": 1080, "height": 1920},
        "materials": {
            "audios": [{"id": "M1", "path": "C:/media/voice.mp3", "type": "extract_music"}],
            "videos": [{"id": "M2", "path": "C:/media/pic.png", "type": "photo"}],
            "texts": list(texts),
        },
        "tracks": [
            {"id": "T1", "type": "video", "segments": [{"material_id": "M2", "target_timerange": {"start": 0, "duration": 5_000_000}}]},
            {"id": "T2", "type": "audio", "segments": [{
                "material_id": "M1", "speed": 1.0, "volume": 1.0,
                "source_timerange": {"start": 2_000_000, "duration": 3_000_000},
                "target_timerange": {"start": 1_000_000, "duration": 3_000_000}}]},
        ],
    }


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    folder = tmp_path / "drafts" / "My Video"
    tl = folder / "Timelines" / TL
    tl.mkdir(parents=True)
    raw = json.dumps(_draft())
    (folder / "draft_content.json").write_text(raw)
    (tl / "draft_content.json").write_text(raw)
    (tl / "draft_content.json.bak").write_text(raw)       # a twin: same draft id
    (tl / "template.tmp").write_text('{"other": true}')   # not a twin: must stay untouched
    (folder / "Timelines" / "project.json").write_text(json.dumps(
        {"main_timeline_id": TL, "timelines": [{"id": TL, "name": "Timeline 01", "is_marked_delete": False}]}))
    (folder / "draft_meta_info.json").write_text(json.dumps({"draft_name": "My Video", "tm_duration": 5_000_000}))
    return folder


STYLE = SubtitleStyle(font_path="C:/Fonts/FM-Abhaya.ttf", english_font_path="C:/Fonts/arialbd.ttf")
CUES = [Cue(0.5, 2.0, "අලුත් layer එකක්"), Cue(2.5, 7.25, "ආයුබෝවන්")]


def test_list_projects_and_timelines(project):
    [p] = list_projects(project.parent)
    assert p.name == "My Video" and p.duration == 5.0
    [t] = list_timelines(project)
    assert t.is_main and len(t.files) == 2


def test_audio_tracks_skip_photos_and_convert_times(project):
    draft = Draft(project, list_timelines(project)[0])
    [track] = draft.audio_tracks()
    assert track.type == "audio"
    [c] = track.clips
    assert (c.source_start, c.target_start, c.target_duration) == (2.0, 1.0, 3.0)


def test_content_json_uses_two_fonts_and_utf16_ranges():
    content = json.loads(writer.content_json("අලුත් layer එකක්", STYLE))
    runs = content["styles"]
    assert [r["font"]["path"] for r in runs] == ["C:/Fonts/FM-Abhaya.ttf", "C:/Fonts/arialbd.ttf", "C:/Fonts/FM-Abhaya.ttf"]
    assert runs[0]["range"][0] == 0 and runs[-1]["range"][1] == len(content["text"])
    assert "layer" in content["text"] and not any("\u0D80" <= ch <= "\u0DFF" for ch in content["text"])
    assert runs[0]["strokes"][0]["width"] == STYLE.stroke_width


def test_write_updates_every_copy_and_backs_up(project):
    tl = list_timelines(project)[0]
    result = writer.write_to_draft(project, tl, CUES, STYLE)
    assert result["added"] == 2 and result["files"] == 3

    for f in (project / "draft_content.json", project / "Timelines" / TL / "draft_content.json",
              project / "Timelines" / TL / "draft_content.json.bak"):
        data = json.loads(f.read_text(encoding="utf-8"))
        [track] = [t for t in data["tracks"] if t.get("name") == writer.TRACK_NAME]
        seg = track["segments"][1]
        assert seg["target_timerange"] == {"start": 2_500_000, "duration": 4_750_000}
        mat_ids = {m["id"] for m in data["materials"]["texts"]}
        assert all(s["material_id"] in mat_ids for s in track["segments"])
        assert data["duration"] == 7_250_000

    assert (project / "Timelines" / TL / "template.tmp").read_text() == '{"other": true}'
    meta = json.loads((project / "draft_meta_info.json").read_text())
    assert meta["tm_duration"] == 7_250_000
    assert (result["backup"] / "draft_content.json").is_file()


def test_writing_again_replaces_old_subtitles(project):
    tl = list_timelines(project)[0]
    writer.write_to_draft(project, tl, CUES, STYLE)
    result = writer.write_to_draft(project, tl, CUES[:1], STYLE)
    assert result["removed"] == 2 and result["added"] == 1
    data = json.loads((project / "draft_content.json").read_text(encoding="utf-8"))
    assert len(data["materials"]["texts"]) == 1
    assert len([t for t in data["tracks"] if t.get("name") == writer.TRACK_NAME]) == 1


def test_restore_backup(project):
    original = (project / "draft_content.json").read_text()
    tl = list_timelines(project)[0]
    writer.write_to_draft(project, tl, CUES, STYLE)
    writer.restore_backup(project, writer.list_backups(project)[0])
    assert (project / "draft_content.json").read_text() == original


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows only")
def test_api_key_is_encrypted_on_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    s = config.Settings()
    s.api_key = "AIza-test-key-1234"
    s.save()
    on_disk = config.Settings.path().read_text()
    assert "AIza-test-key-1234" not in on_disk
    assert config.Settings.load().api_key == "AIza-test-key-1234"
