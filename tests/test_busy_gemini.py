"""When Gemini says 503 "high demand": switch models, keep finished work, fill the gaps later."""

from types import SimpleNamespace

import pytest

from sinhalasubs import audio, pipeline, transcribe
from sinhalasubs.models import Cue
from sinhalasubs.transcribe import ModelChain, TranscribeOptions, _Sub, fallback_models, friendly_error

BUSY = "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand.'}}"


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch, tmp_path):
    monkeypatch.setattr(transcribe.time, "sleep", lambda s: None)
    monkeypatch.setenv("APPDATA", str(tmp_path))          # busy-model memory goes to a temp folder


def test_fallback_order_prefers_other_flash_models():
    names = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro", "gemini-3-flash-preview",
             "gemini-3.5-transcribe", "gemini-3.7-flash", "gemini-3.8-flash"]
    assert fallback_models(names, "gemini-3.8-flash") == [
        "gemini-3.8-flash", "gemini-3.7-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]


def test_chain_switches_when_busy_and_remembers():
    calls = []

    def fn(model):
        calls.append(model)
        if model == "busy-model":
            raise RuntimeError(BUSY)
        return "ok from " + model

    chain = ModelChain(["busy-model", "free-model"])
    assert chain.call(fn, print) == "ok from free-model"
    assert calls.count("busy-model") == 1                    # no waiting: switched at once
    assert chain.first == "free-model"                       # the next request starts with the free one
    calls.clear()
    chain.call(fn, print)
    assert calls == ["free-model"]


def test_chain_does_not_hide_real_errors():
    def fn(model):
        raise ValueError("400 INVALID_ARGUMENT bad audio")
    with pytest.raises(ValueError):
        ModelChain(["a", "b"]).call(fn, print)


def test_all_busy_gives_a_friendly_message():
    with pytest.raises(RuntimeError, match="very busy"):
        ModelChain(["a", "b"]).call(lambda m: (_ for _ in ()).throw(RuntimeError(BUSY)), print)
    assert "free Gemini limit" in friendly_error(Exception("429 RESOURCE_EXHAUSTED"))


def test_uncovered_speech_finds_the_hole():
    silences = [(0.0, 1.0), (9.0, 10.0)]              # speech from 1 to 9 s
    cues = [Cue(1.0, 3.0, "a"), Cue(7.0, 9.0, "b")]
    assert pipeline.uncovered_speech(cues, silences, 10.0) == [(3.0, 7.0)]
    assert pipeline.uncovered_speech([Cue(1.0, 9.0, "all")], silences, 10.0) == []


@pytest.fixture
def speech_wav(tmp_path):
    """Two 'spoken' parts (tones) of 4 s with 2 s of silence between: 0–4 and 6–10 s."""
    wav = tmp_path / "speech.wav"
    r = audio.run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=300:duration=4",
                          "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=2",
                          "-f", "lavfi", "-i", "sine=frequency=300:duration=4",
                          "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1",
                          "-ac", "1", "-ar", "16000", "-y", str(wav)])
    assert r.returncode == 0
    return wav


class FakeGemini:
    """gemini-9-flash is always busy; gemini-8-flash answers with one subtitle per clip."""

    def __init__(self):
        self.models = SimpleNamespace(generate_content=self.generate, list=self.list)

    def list(self):
        return [SimpleNamespace(name=f"models/{n}", supported_actions=["generateContent"])
                for n in ("gemini-9-flash", "gemini-8-flash")]

    def generate(self, model, contents, config):
        if isinstance(contents, str):                                  # the polish pass
            import json
            lines = json.loads(contents[contents.index("["):])
            return SimpleNamespace(parsed=lines, text="")
        prompt = contents[0]
        if model == "gemini-9-flash":
            raise RuntimeError(BUSY)
        import re
        duration = float(re.search(r"\(([\d.]+) seconds long\)", prompt).group(1))
        return SimpleNamespace(parsed=[_Sub(start=0.2, end=min(duration, 3.5), text="කතාව")], text="")


def test_generate_keeps_going_and_fill_gaps(monkeypatch, speech_wav):
    fake = FakeGemini()
    monkeypatch.setattr(pipeline, "make_client", lambda opts: fake)
    opts = TranscribeOptions(api_key="x", chunk_len=5.0, workers=1)

    cues = pipeline.wav_to_cues(speech_wav, 10.0, opts, print)       # gemini-9 busy → gemini-8 does it
    assert len(cues) == 2 and cues.missing == []

    # lose the second subtitle, then ask to fill only what is missing
    fill = pipeline.fill_gaps(speech_wav, 10.0, cues[:1], opts, print)
    assert len(fill) == 2 and fill[1].start > 5.0


def test_busy_models_are_remembered_between_runs():
    def fn(model):
        if model == "busy-model":
            raise RuntimeError(BUSY)
        return model
    ModelChain(["busy-model", "free-model"]).call(fn, print)
    assert ModelChain(["busy-model", "free-model"]).first == "free-model"    # a new job, same app data


def test_retired_model_is_skipped_and_remembered():
    gone = "404 NOT_FOUND. {'error': {'code': 404, 'message': 'This model models/old is no longer available to new users.'}}"
    calls = []

    def fn(model):
        calls.append(model)
        if model == "old":
            raise RuntimeError(gone)
        return model
    assert ModelChain(["old", "new"]).call(fn, print) == "new"
    assert calls == ["old", "new"]                                  # no waiting on a 404
    assert ModelChain(["old", "new"]).first == "new"
    assert "retired" in friendly_error(Exception(gone))
