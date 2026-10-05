"""The whole job, step by step: audio -> chunks -> Gemini -> clean subtitles.

The audio can come from a video file, or from a track of a CapCut project.
"""

from __future__ import annotations

import hashlib
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from . import audio
from .models import Cue
from .transcribe import (Log, TranscribeOptions, fix_script, friendly_error, is_busy, make_client,
                         model_chain, split_long, tidy, transcribe_chunk)


class Result(list):
    """A list of cues, plus the parts of the audio that could not be transcribed."""

    def __init__(self, cues=(), missing=()):
        super().__init__(cues)
        self.missing: list[tuple[float, float]] = list(missing)


def _silent_share(a: float, b: float, silences: list[tuple[float, float]]) -> float:
    quiet = sum(max(0.0, min(b, e) - max(a, s)) for s, e in silences)
    return quiet / max(b - a, 1e-6)


def uncovered_speech(cues: list[Cue], silences: list[tuple[float, float]], total: float,
                     min_len: float = 0.8, join_gap: float = 1.5) -> list[tuple[float, float]]:
    """Parts of the audio with speech but no subtitle (e.g. a chunk Gemini could not do)."""
    # speech = everything that is not silence
    speech, t = [], 0.0
    for s, e in sorted(silences):
        if s > t:
            speech.append((t, s))
        t = max(t, e)
    if t < total:
        speech.append((t, total))
    # remove the parts covered by subtitles
    holes = []
    for a, b in speech:
        for c in sorted(cues, key=lambda c: c.start):
            if c.end <= a or c.start >= b:
                continue
            if c.start > a:
                holes.append((a, c.start))
            a = max(a, c.end)
        if b > a:
            holes.append((a, b))
    # join holes close together, keep only real stretches of speech
    joined: list[list[float]] = []
    for a, b in holes:
        if joined and a - joined[-1][1] < join_gap:
            joined[-1][1] = b
        else:
            joined.append([a, b])
    return [(a, b) for a, b in joined if b - a >= min_len]


def _transcribe_ranges(wav: Path, ranges: list[tuple[float, float]], client, chain, opts: TranscribeOptions,
                       log: Log, tmp: Path, cancelled: Callable[[], bool]) -> Result:
    """Send each (start, end) range of the WAV to Gemini. Failed ranges end up in Result.missing."""
    def work(i: int, a: float, b: float) -> list[Cue]:
        if cancelled():
            return []
        mp3 = audio.export_chunk(wav, a, b, tmp / f"chunk_{i:03}.mp3")
        return chain.call(lambda m: transcribe_chunk(client, m, mp3, opts, offset=a, duration=b - a, log=log), log)

    result = Result()
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, opts.workers)) as pool:
        jobs = {pool.submit(work, i, a, b): (a, b) for i, (a, b) in enumerate(ranges)}
        for done, job in enumerate(as_completed(jobs), start=1):
            try:
                result += job.result()
            except Exception as e:  # noqa: BLE001 - keep going: one bad chunk must not lose the rest
                if not is_busy(e) and "busy" not in str(e) and "limit" not in str(e):
                    raise
                result.missing.append(jobs[job])
                errors.append(e)
            log(f"  Transcribed {done}/{len(ranges)}")
    if cancelled():
        raise RuntimeError("Cancelled.")
    if errors and not result:                 # nothing worked at all
        raise RuntimeError(friendly_error(errors[0]))
    result.missing.sort()
    return result


def _finish(cues: list[Cue], missing, client, chain, opts: TranscribeOptions, log: Log) -> Result:
    cues = tidy(split_long(tidy(cues), opts.max_chars))
    stats = fix_script(cues, client, chain, opts, log)
    if not stats.get("skipped"):
        log(f"Sinhala script accuracy: {stats['purity_before']:.1%} -> {stats['purity_after']:.1%}")
    log(f"Done: {len(cues)} subtitles.")
    if missing:
        spans = ", ".join(f"{int(a) // 60}:{int(a) % 60:02d}–{int(b) // 60}:{int(b) % 60:02d}" for a, b in missing)
        log(f"⚠ Gemini was too busy for {len(missing)} part(s): {spans}. "
            "Click Generate → 'Fill missing parts' to try them again.")
    return Result(cues, missing)


def _transcribe_wav(wav: Path, total: float, opts: TranscribeOptions, log: Log, tmp: Path,
                    cancelled: Callable[[], bool] = lambda: False) -> list[Cue]:
    if opts.engine == "whisper":
        return _whisper(wav, total, opts, log, cancelled)
    client = make_client(opts)
    chain = model_chain(client, opts)
    log(f"Model: {chain.first}  (if busy: {', '.join(chain.models[1:]) or 'no other model'})")

    silences = audio.detect_silences(wav)
    chunks = [(a, b) for a, b in audio.plan_chunks(total, silences, opts.chunk_len)
              if _silent_share(a, b, silences) < 0.97]  # skip chunks with no speech at all
    log(f"Split into {len(chunks)} chunk(s). Sending to Gemini…")
    result = _transcribe_ranges(wav, chunks, client, chain, opts, log, tmp, cancelled)
    return _finish(list(result), result.missing, client, chain, opts, log)


def fill_gaps(wav: Path, total: float, cues: list[Cue], opts: TranscribeOptions, log: Log = print,
              cancelled: Callable[[], bool] = lambda: False) -> list[Cue]:
    """Transcribe only the speech that has no subtitle yet, and add it to `cues`."""
    silences = audio.detect_silences(wav)
    holes = uncovered_speech(cues, silences, total)
    if not holes:
        log("Every part with speech already has a subtitle.")
        return Result(cues)
    ranges = []
    for a, b in holes:                         # pad a little so first/last words are not cut
        a, b = max(0.0, a - 0.25), min(total, b + 0.25)
        ranges += [(x + a, y + a) for x, y in audio.plan_chunks(b - a, [], opts.chunk_len)]
    log(f"Filling {len(ranges)} part(s) without subtitles ({sum(b - a for a, b in ranges):.0f}s of audio)…")
    client = make_client(opts)
    chain = model_chain(client, opts)
    with tempfile.TemporaryDirectory(prefix="sinhalasubs_") as tmp:
        result = _transcribe_ranges(wav, ranges, client, chain, opts, log, Path(tmp), cancelled)
    new = [c for c in result if not any(o.start <= (c.start + c.end) / 2 < o.end for o in cues)]
    new = tidy(split_long(new, opts.max_chars))
    fix_script(new, client, chain, opts, log)
    log(f"Added {len(new)} subtitle(s).")
    merged = tidy([*cues, *new])
    return Result(merged, result.missing)


def _whisper(wav: Path, total: float, opts: TranscribeOptions, log: Log,
             cancelled: Callable[[], bool]) -> list[Cue]:
    """Offline recognition, then the same clean-up. Gemini polish only if a key is set."""
    from . import whisper_engine

    cues = whisper_engine.transcribe(wav, total, opts, log, cancelled)
    client = model = None
    if opts.polish:
        try:
            client = make_client(opts)
            model = model_chain(client, opts)
        except Exception:  # noqa: BLE001 - no key or no internet: letter mapping only
            log("(No Gemini key/internet: skipping the polish pass, using letter mapping only.)")
            client = None
    words = [c.words for c in cues]
    stats = fix_script(cues, client, model or "", opts, log)
    for c, w in zip(cues, words):      # keep word times where the polish did not change the words
        c.words = w
    if not stats.get("skipped"):
        log(f"Sinhala script accuracy: {stats['purity_before']:.1%} -> {stats['purity_after']:.1%}")
    log(f"Done: {len(cues)} subtitles.")
    return cues


def video_to_cues(video: Path, opts: TranscribeOptions, log: Log = print, **kw) -> list[Cue]:
    if not video.is_file():
        raise FileNotFoundError(f"File not found: {video}")
    with tempfile.TemporaryDirectory(prefix="sinhalasubs_") as tmp:
        wav = Path(tmp) / "audio.wav"
        total = audio.extract_audio(video, wav)
        log(f"Audio: {total:.1f}s")
        return _transcribe_wav(wav, total, opts, log, Path(tmp), **kw)


def clips_to_cues(clips, opts: TranscribeOptions, log: Log = print, **kw) -> list[Cue]:
    """Subtitles for the clips of one CapCut track, timed to the CapCut timeline."""
    with tempfile.TemporaryDirectory(prefix="sinhalasubs_") as tmp:
        wav = Path(tmp) / "track.wav"
        total = audio.render_track(clips, wav, log)
        return _transcribe_wav(wav, total, opts, log, Path(tmp), **kw)


# --- audio kept on disk for the timeline, playback and later transcriptions -------------------

KEEP_AUDIO = 15   # newest cached WAVs to keep


def _audio_cache(key: str) -> Path:
    from .config import app_data_dir

    folder = app_data_dir() / "audio"
    folder.mkdir(exist_ok=True)
    old = sorted(folder.glob("*.wav"), key=lambda f: f.stat().st_mtime, reverse=True)[KEEP_AUDIO:]
    for f in old:   # free disk space: drop the least recently used audio
        for extra in (f, f.with_suffix(".peaks.json")):
            extra.unlink(missing_ok=True)
    return folder / (hashlib.sha1(key.encode()).hexdigest()[:16] + ".wav")


def prepare_audio(source, log: Log = print, cancelled: Callable[[], bool] = lambda: False) -> tuple[Path, float]:
    """WAV of a video file (Path) or of CapCut clips (list). Re-used while the source is unchanged."""
    if isinstance(source, Path):
        st = source.stat()
        key = f"video|{source}|{st.st_size}|{st.st_mtime_ns}"
    else:
        key = "clips|" + "|".join(f"{c.path}:{c.source_start}:{c.source_duration}:{c.target_start}:"
                                  f"{c.speed}:{c.volume}" for c in source)
    wav = _audio_cache(key)
    if wav.is_file() and wav.stat().st_size > 44:
        wav.touch()   # mark as recently used
        return wav, audio.media_duration(wav)
    tmp = wav.with_suffix(".part.wav")
    total = audio.extract_audio(source, tmp) if isinstance(source, Path) else audio.render_track(source, tmp, log)
    tmp.replace(wav)
    return wav, total


def wav_to_cues(wav: Path, total: float, opts: TranscribeOptions, log: Log = print, **kw) -> list[Cue]:
    """Subtitles for an already prepared WAV (see prepare_audio)."""
    with tempfile.TemporaryDirectory(prefix="sinhalasubs_") as tmp:
        return _transcribe_wav(wav, total, opts, log, Path(tmp), **kw)
