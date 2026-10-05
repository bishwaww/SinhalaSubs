"""Caption looks: turn one subtitle into the "frames" a caption style needs.

A frame is a short stretch of time with the words to show and a role for each word:
  normal  – not spoken yet (or a classic subtitle)
  active  – being spoken now (highlight colour, can be bigger)
  spoken  – already spoken (karaoke fill colour)

CapCut has no open format for per-word timing in plain text clips, so each frame
becomes its own text clip when we write to CapCut.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Cue

MODES = {
    "classic": "Classic (whole line)",
    "karaoke": "Karaoke (highlight spoken word)",
    "reveal": "Reveal (words appear one by one)",
    "single": "One word at a time",
    "keyword": "Emphasise one keyword",
}
MIN_FRAME = 0.05   # seconds


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Frame:
    start: float
    end: float
    words: list[tuple[str, str]] = field(default_factory=list)   # (text, role)

    @property
    def text(self) -> str:
        return " ".join(w for w, _ in self.words)


def apply_case(text: str, mode: str) -> str:
    """Change the case of English letters only (Sinhala has no capitals)."""
    if mode == "upper":
        return re.sub(r"[A-Za-z]+", lambda m: m.group().upper(), text)
    if mode == "lower":
        return re.sub(r"[A-Za-z]+", lambda m: m.group().lower(), text)
    return text


def word_times(cue: Cue) -> list[Word]:
    """When each word is spoken. Uses real timings if the cue has them, else shares time by length."""
    words = cue.text.split()
    real = getattr(cue, "words", None)
    if real and [w.strip() for _, _, w in real] == words:     # still the same words (not edited)
        # the subtitle may have been moved or trimmed since: stretch the times onto it
        s0, e0 = real[0][0], real[-1][1]
        k = cue.duration / (e0 - s0) if e0 > s0 else 0.0
        out = [Word(w.strip(), cue.start + (s - s0) * k, cue.start + (e - s0) * k) for s, e, w in real]
        out[0].start, out[-1].end = cue.start, cue.end
        return out
    if not words:
        return []
    weights = [len(w) + 2 for w in words]           # +2: even short words take a moment
    total, t, out = sum(weights), cue.start, []
    for w, wt in zip(words, weights):
        end = t + cue.duration * wt / total
        out.append(Word(w, t, end))
        t = end
    out[-1].end = cue.end
    return out


def keyword_index(words: list[Word]) -> int:
    """The word to emphasise: the longest one."""
    return max(range(len(words)), key=lambda i: len(words[i].text)) if words else -1


def _pages(words: list[Word], per_page: int) -> list[list[Word]]:
    if per_page <= 0 or per_page >= len(words):
        return [words] if words else []
    return [words[i:i + per_page] for i in range(0, len(words), per_page)]


def frames(cue: Cue, mode: str = "classic", per_page: int = 0, case: str = "none") -> list[Frame]:
    """Every frame of one subtitle, in time order, covering cue.start … cue.end."""
    src = cue
    if case != "none":
        src = Cue(cue.start, cue.end, apply_case(cue.text, case))
        if cue.words:
            src.words = [(s, e, apply_case(w, case)) for s, e, w in cue.words]
    words = word_times(src)
    if mode == "classic" or not words:
        return [Frame(cue.start, cue.end, [(apply_case(cue.text, case), "normal")])]

    out: list[Frame] = []
    pages = _pages(words, per_page)
    for n, page in enumerate(pages):
        p_start = page[0].start if n else cue.start
        p_end = pages[n + 1][0].start if n + 1 < len(pages) else cue.end
        if mode == "keyword":
            k = keyword_index(page)
            out.append(Frame(p_start, p_end, [(w.text, "active" if i == k else "normal") for i, w in enumerate(page)]))
            continue
        for i, w in enumerate(page):
            f_start = p_start if i == 0 else w.start
            f_end = page[i + 1].start if i + 1 < len(page) else p_end
            if mode == "karaoke":
                roles = [(x.text, "spoken" if j < i else "active" if j == i else "normal") for j, x in enumerate(page)]
            elif mode == "reveal":
                roles = [(x.text, "active" if j == i else "normal") for j, x in enumerate(page[:i + 1])]
            else:  # single
                roles = [(w.text, "active")]
            out.append(Frame(f_start, f_end, roles))

    # never produce frames too short for CapCut; give the time to the neighbour instead
    merged: list[Frame] = []
    for f in out:
        if merged and f.end - f.start < MIN_FRAME:
            merged[-1].end = f.end
        else:
            merged.append(f)
    return merged


def frame_at(cue: Cue, t: float, mode: str, per_page: int = 0, case: str = "none") -> Frame | None:
    for f in frames(cue, mode, per_page, case):
        if f.start <= t < f.end:
            return f
    return None
