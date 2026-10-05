"""Waveform peaks for the timeline: how loud each small slice of the audio is."""

from __future__ import annotations

import array
import json
import wave
from pathlib import Path
from typing import Callable

BUCKET = 0.02   # seconds per peak (50 peaks per second)


def compute_peaks(wav_path: Path, bucket_s: float = BUCKET,
                  cancelled: Callable[[], bool] = lambda: False) -> list[int]:
    """Loudest sample (0–255) in each `bucket_s` slice of a 16-bit mono WAV."""
    peaks = []
    with wave.open(str(wav_path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("Expected a 16-bit WAV file.")
        per_bucket = max(1, int(w.getframerate() * bucket_s))
        while not cancelled():
            raw = w.readframes(per_bucket)
            if not raw:
                break
            samples = array.array("h", raw)
            loud = max(max(samples), -min(samples)) if samples else 0
            peaks.append(min(255, loud * 510 // 32768))   # ×2 so quiet speech is still visible
    return peaks


def load_peaks(wav_path: Path, cancelled: Callable[[], bool] = lambda: False) -> list[int]:
    """Peaks, cached next to the WAV and recomputed when the WAV changes."""
    cache = wav_path.with_suffix(".peaks.json")
    stamp = f"{wav_path.stat().st_size}-{wav_path.stat().st_mtime_ns}"
    try:
        data = json.loads(cache.read_text())
        if data.get("stamp") == stamp:
            return data["peaks"]
    except (OSError, ValueError):
        pass
    peaks = compute_peaks(wav_path, cancelled=cancelled)
    if not cancelled():
        cache.write_text(json.dumps({"stamp": stamp, "peaks": peaks}))
    return peaks
