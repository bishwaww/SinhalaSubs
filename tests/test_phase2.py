from pathlib import Path
from types import SimpleNamespace

import pytest

from sinhalasubs import audio
from sinhalasubs.models import Cue, from_srt, srt_time, to_srt
from sinhalasubs.sinhala_script import _CONSONANTS, _SIGNS, _VOWELS, has_foreign, purity, transliterate
from sinhalasubs.transcribe import (TranscribeOptions, _Sub, pick_model, split_long, tidy,
                                    transcribe_chunk)


# --- .srt -------------------------------------------------------------------

def test_srt_time():
    assert srt_time(75.5) == "00:01:15,500"
    assert srt_time(3725.004) == "01:02:05,004"


def test_srt_round_trip():
    cues = [Cue(0.5, 2.0, "ආයුබෝවන්"), Cue(2.5, 4.25, "අලුත් layer එකක්")]
    back = from_srt(to_srt(cues))
    assert [(c.start, c.end, c.text) for c in back] == [(0.5, 2.0, "ආයුබෝවන්"), (2.5, 4.25, "අලුත් layer එකක්")]


# --- wrong-script repair ----------------------------------------------------

def test_lookalike_tables_line_up():
    for group in (_CONSONANTS, _VOWELS, _SIGNS):
        sizes = {len(v) for v in group.values()}
        assert len(sizes) == 1, group


def test_malayalam_letters_become_sinhala():
    bad = "හോමප"  # Malayalam ോ inside a Sinhala word
    assert has_foreign(bad)
    fixed = transliterate(bad)
    assert fixed == "හෝමප"
    assert not has_foreign(fixed)


def test_digits_inside_words_are_dropped():
    assert transliterate("මම3ගෙදර") == "මමගෙදර"
    assert transliterate("පාඩම 3") == "පාඩම 3"


def test_purity():
    assert purity(["අම්මා"]) == 1.0
    assert purity(["අമ"]) == 0.5


# --- cue clean-up -----------------------------------------------------------

def test_split_long_keeps_all_words_and_time():
    c = Cue(0, 10, "එක දෙක තුන හතර පහ හය හත අට නමය දහය")
    parts = split_long([c], max_chars=12)
    assert len(parts) > 1
    assert " ".join(p.text for p in parts) == c.text
    assert parts[0].start == 0 and abs(parts[-1].end - 10) < 1e-9
    assert all(len(p.text) <= 12 for p in parts)


def test_tidy_removes_overlap_and_sorts():
    cues = tidy([Cue(3, 5, "b"), Cue(0, 4, "a"), Cue(6, 6.1, "c"), Cue(7, 8, " ")])
    assert [c.text for c in cues] == ["a", "b", "c"]
    assert cues[0].end <= cues[1].start
    assert cues[2].duration == pytest.approx(0.6)  # decimals are never exact in computers


def test_pick_model_prefers_newest_stable_flash():
    names = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite",
             "gemini-2.5-pro", "gemini-3.0-flash-preview"]
    assert pick_model(names) == "gemini-2.5-flash"


# --- Gemini call with a fake client ------------------------------------------

class FakeModels:
    def __init__(self, subs):
        self.subs, self.calls = subs, []

    def generate_content(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(parsed=self.subs, text="")


def test_transcribe_chunk_adds_offset_and_clamps(tmp_path):
    mp3 = tmp_path / "c.mp3"
    mp3.write_bytes(b"fake")
    fake = FakeModels([_Sub(start=1, end=2.5, text=" ආයුබෝවන් "), _Sub(start=58, end=70, text="අවසානය"),
                       _Sub(start=3, end=4, text="  ")])
    client = SimpleNamespace(models=fake)
    cues = transcribe_chunk(client, "gemini-x", mp3, TranscribeOptions(glossary=["Kasun"]),
                            offset=100, duration=60, log=print)
    assert [(c.start, c.end, c.text) for c in cues] == [(101, 102.5, "ආයුබෝවන්"), (158, 160, "අවසානය")]
    assert "Kasun" in fake.calls[0]["contents"][0]


# --- FFmpeg (real) ------------------------------------------------------------

@pytest.fixture(scope="module")
def beep_wav(tmp_path_factory) -> Path:
    """3s tone, 2s silence, 3s tone."""
    wav = tmp_path_factory.mktemp("a") / "beep.wav"
    r = audio.run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                          "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=2",
                          "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                          "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1",
                          "-ac", "1", "-ar", "16000", "-y", str(wav)])
    assert r.returncode == 0, r.stderr
    return wav


def test_duration_and_silence(beep_wav):
    assert abs(audio.media_duration(beep_wav) - 8.0) < 0.1
    silences = audio.detect_silences(beep_wav)
    assert len(silences) == 1
    s, e = silences[0]
    assert abs(s - 3) < 0.2 and abs(e - 5) < 0.2


def test_chunks_cut_inside_silence(beep_wav):
    chunks = audio.plan_chunks(8.0, audio.detect_silences(beep_wav), chunk_len=4.0)
    assert len(chunks) == 2
    assert 3 < chunks[0][1] < 5  # the cut is in the quiet part


def test_export_chunk(beep_wav, tmp_path):
    out = audio.export_chunk(beep_wav, 1.0, 3.0, tmp_path / "c.mp3")
    assert abs(audio.media_duration(out) - 2.0) < 0.15
