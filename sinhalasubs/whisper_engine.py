"""Offline speech recognition with Whisper (faster-whisper), no internet or API key needed.

The model is downloaded once (hundreds of MB) into %APPDATA%\\SinhalaSubs\\whisper and then
runs on this computer. Whisper's Sinhala is weaker than Gemini's, but it gives a real
time for every word, which makes karaoke captions exact.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from .config import app_data_dir
from .models import Cue

MODELS = {
    "small": "Small – fast, ~480 MB",
    "medium": "Medium – better, ~1.5 GB",
    "large-v3-turbo": "Large v3 Turbo – best speed/quality, ~1.6 GB",
    "large-v3": "Large v3 – most accurate, slow, ~3 GB",
}
_END = re.compile(r"[.!?។॥]$")
GAP = 0.6   # a pause this long always starts a new subtitle


def models_dir() -> Path:
    d = app_data_dir() / "whisper"
    d.mkdir(exist_ok=True)
    return d


def is_installed() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def is_downloaded(name: str) -> bool:
    return any(name in p.name for p in models_dir().glob("models--*"))


def words_to_cues(words: list[tuple[float, float, str]], max_chars: int, max_dur: float) -> list[Cue]:
    """Group timed words into subtitles: break at sentence ends, pauses, or when too long."""
    cues: list[Cue] = []
    line: list[tuple[float, float, str]] = []

    def flush() -> None:
        if line:
            c = Cue(line[0][0], line[-1][1], " ".join(w for _, _, w in line))
            c.words = list(line)
            cues.append(c)
            line.clear()

    for s, e, w in words:
        w = w.strip()
        if not w:
            continue
        if line:
            text_len = len(" ".join(x for _, _, x in line)) + 1 + len(w)
            if s - line[-1][1] > GAP or text_len > max_chars or e - line[0][0] > max_dur:
                flush()
        line.append((s, e, w))
        if _END.search(w):
            flush()
    flush()
    return cues


def transcribe(wav: Path, total: float, opts, log: Callable[[str], None],
               cancelled: Callable[[], bool] = lambda: False) -> list[Cue]:
    if not is_installed():
        raise RuntimeError("Whisper is not installed. Run: pip install faster-whisper")
    from faster_whisper import WhisperModel

    name = opts.whisper_model
    if not is_downloaded(name):
        log(f"Downloading the Whisper '{name}' model (only the first time – this can take a while)…")
    else:
        log(f"Loading Whisper '{name}'…")
    model = WhisperModel(name, device="auto", compute_type="int8", download_root=str(models_dir()))

    prompt = "මේ සිංහල කතාවකි." if opts.language == "si" else ""
    if opts.glossary:
        prompt = (prompt + " " + ", ".join(opts.glossary)).strip()
    segments, _info = model.transcribe(str(wav), language=opts.language, word_timestamps=True, vad_filter=True,
                                       beam_size=5, initial_prompt=prompt or None)
    words: list[tuple[float, float, str]] = []
    for seg in segments:                       # a generator: recognition happens while we loop
        if cancelled():
            raise RuntimeError("Cancelled.")
        words += [(w.start, w.end, w.word) for w in (seg.words or [])]
        log(f"  Transcribed {int(seg.end)}/{int(total)}")
    log(f"Whisper heard {len(words)} words.")
    return words_to_cues(words, opts.max_chars, opts.max_duration)
