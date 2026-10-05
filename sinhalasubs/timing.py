"""Timing edits for subtitles on one track: move, trim, split, merge and clean-up.

Subtitles are kept sorted and never overlap, because they all go on one CapCut text track.
All functions change the list in place.
"""

from __future__ import annotations

from .models import Cue

MIN_LEN = 0.1   # shortest subtitle we allow while dragging (seconds)


def move_limits(cues: list[Cue], idxs: list[int]) -> tuple[float, float]:
    """How far the selected cues may move (left as a negative number, right) before hitting a neighbour."""
    chosen = set(idxs)
    left, right = float("inf"), float("inf")
    for i in chosen:
        c = cues[i]
        prev_end = max((o.end for j, o in enumerate(cues) if j not in chosen and o.end <= c.start + 1e-9), default=0.0)
        next_start = min((o.start for j, o in enumerate(cues) if j not in chosen and o.start >= c.end - 1e-9),
                         default=float("inf"))
        left = min(left, c.start - prev_end)
        right = min(right, next_start - c.end)
    return -max(0.0, left), max(0.0, right)


def move(cues: list[Cue], idxs: list[int], originals: list[tuple[float, float]], delta: float) -> float:
    """Move the selected cues by `delta` seconds from where they were (`originals`), within limits."""
    for i, (s, e) in zip(idxs, originals):     # measure the limits from the original places
        cues[i].start, cues[i].end = s, e
    lo, hi = move_limits(cues, idxs)
    delta = max(lo, min(hi, delta))
    for i, (s, e) in zip(idxs, originals):
        cues[i].start, cues[i].end = s + delta, e + delta
    return delta


def trim(cues: list[Cue], i: int, edge: str, t: float, roll: bool = False) -> float:
    """Drag the 'start' or 'end' edge of cue i to time t. Returns the time actually used.

    roll=True also moves a touching neighbour's edge (CapCut calls this a roll edit).
    """
    c = cues[i]
    prev = cues[i - 1] if i > 0 else None
    nxt = cues[i + 1] if i + 1 < len(cues) else None
    if edge == "start":
        low = (prev.start + MIN_LEN) if (roll and prev) else (prev.end if prev else 0.0)
        t = max(low, min(t, c.end - MIN_LEN))
        if roll and prev and abs(prev.end - c.start) < 0.02:
            prev.end = t
        c.start = t
    else:
        high = (nxt.end - MIN_LEN) if (roll and nxt) else (nxt.start if nxt else float("inf"))
        t = min(high, max(t, c.start + MIN_LEN))
        if roll and nxt and abs(nxt.start - c.end) < 0.02:
            nxt.start = t
        c.end = t
    return t


def split(cues: list[Cue], i: int, t: float | None = None) -> int:
    """Split cue i at time t (default: where the words divide). Returns the new cue's index."""
    c = cues[i]
    words = c.text.split()
    if t is None or not (c.start + MIN_LEN < t < c.end - MIN_LEN):
        half = max(1, len(words) // 2)
        left = " ".join(words[:half])
        t = c.start + c.duration * len(left) / max(1, len(c.text))
    # Share the words in proportion to time.
    share = (t - c.start) / c.duration if c.duration else 0.5
    k = min(max(1, round(len(words) * share)), max(1, len(words) - 1)) if len(words) > 1 else 1
    right_text = " ".join(words[k:]) or c.text
    new = Cue(t, c.end, right_text)
    c.end, c.text = t, " ".join(words[:k])
    cues.insert(i + 1, new)
    return i + 1


def merge(cues: list[Cue], idxs: list[int]) -> int:
    """Join the selected cues (or cue + next when one is selected) into the first. Returns its index."""
    idxs = sorted(set(idxs))
    if len(idxs) == 1 and idxs[0] + 1 < len(cues):
        idxs.append(idxs[0] + 1)
    if len(idxs) < 2:
        return idxs[0] if idxs else -1
    first = cues[idxs[0]]
    rest = [cues[i] for i in idxs[1:]]
    first.text = " ".join([first.text] + [c.text for c in rest])
    first.end = max([first.end] + [c.end for c in rest])
    for i in reversed(idxs[1:]):
        del cues[i]
    return idxs[0]


def fix_overlaps(cues: list[Cue]) -> int:
    """Sort cues and end each one before the next starts. Returns how many changed."""
    cues.sort(key=lambda c: c.start)
    changed = 0
    for a, b in zip(cues, cues[1:]):
        if a.end > b.start:
            a.end = max(a.start + MIN_LEN, b.start)
            changed += 1
    return changed


def close_gaps(cues: list[Cue], max_gap: float = 0.3) -> int:
    """Stretch a cue to the next one when the gap between them is shorter than max_gap."""
    changed = 0
    for a, b in zip(cues, cues[1:]):
        if 0 < b.start - a.end < max_gap:
            a.end = b.start
            changed += 1
    return changed


def min_duration(cues: list[Cue], seconds: float = 1.0) -> int:
    """Lengthen cues shorter than `seconds`, as far as the next cue allows."""
    changed = 0
    for i, c in enumerate(cues):
        if c.duration < seconds:
            limit = cues[i + 1].start if i + 1 < len(cues) else float("inf")
            new_end = min(c.start + seconds, limit)
            if new_end > c.end:
                c.end = new_end
                changed += 1
    return changed


def shift_all(cues: list[Cue], delta: float) -> None:
    """Move every cue by delta seconds (never before 0)."""
    if cues:
        delta = max(delta, -cues[0].start)
    for c in cues:
        c.start += delta
        c.end += delta


def cue_at(cues: list[Cue], t: float) -> int:
    """Index of the cue showing at time t, or -1."""
    for i, c in enumerate(cues):
        if c.start <= t < c.end:
            return i
    return -1
