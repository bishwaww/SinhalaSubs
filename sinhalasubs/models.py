"""Subtitle cues and the .srt file format."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Cue:
    """One subtitle: shown from `start` to `end` seconds."""
    start: float
    end: float
    text: str
    # (start, end, word) for every word when the recogniser gave real word times (Whisper)
    words: list | None = field(default=None, compare=False, repr=False)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def srt_time(seconds: float) -> str:
    """75.5 -> '00:01:15,500'"""
    ms = round(max(0.0, seconds) * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def parse_srt_time(text: str) -> float:
    """'00:01:15,500' -> 75.5"""
    h, m, s = text.strip().replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def to_srt(cues: list[Cue]) -> str:
    blocks = [
        f"{i}\n{srt_time(c.start)} --> {srt_time(c.end)}\n{c.text}\n"
        for i, c in enumerate(cues, start=1)
    ]
    return "\n".join(blocks)


_BLOCK = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})[^\n]*\n(.*?)(?:\n\s*\n|\Z)",
    re.S,
)


def from_srt(text: str) -> list[Cue]:
    text = text.lstrip("﻿").replace("\r\n", "\n")
    return [
        Cue(parse_srt_time(a), parse_srt_time(b), body.strip())
        for a, b, body in _BLOCK.findall(text + "\n\n")
        if body.strip()
    ]
