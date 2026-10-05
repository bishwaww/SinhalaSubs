"""How CapCut turns its style numbers into pixels, so our preview matches CapCut.

CapCut does not size text by the usual "em" box. It sizes each font so that its
*typographic span* (ascender + descender, read from the font file's OS/2 table)
has the same height:

    span_px = size × scale × short_side / 150      (short_side: the smaller canvas edge)
    em_px   = span_px / span_ratio(font)            (span_ratio = span / unitsPerEm)

Because every font gets the same span, two fonts on one line (FM Sinhala + Arial
for English) come out at different letter sizes unless we correct the size of
the second one — see matched_size().
"""

from __future__ import annotations

import struct
from functools import lru_cache
from pathlib import Path

SIZE_UNIT = 150            # short_side / SIZE_UNIT = pixels of span per size unit
DEFAULT_SPAN = 1.2         # typical span ratio, used when a font can't be read
LINE_SPACING = 0.02        # CapCut's default line spacing value in drafts


def _short(canvas: tuple[float, float]) -> float:
    return min(canvas)


def span_px(size: float, scale: float, canvas: tuple[float, float]) -> float:
    return size * scale * _short(canvas) / SIZE_UNIT


def em_px(size: float, scale: float, canvas: tuple[float, float], font_path: str) -> float:
    return span_px(size, scale, canvas) / span_ratio(font_path)


def row_px(size: float, scale: float, canvas: tuple[float, float], font_path: str,
           line_spacing: float = LINE_SPACING) -> float:
    """Distance between the baselines of two lines."""
    return span_px(size, scale, canvas) + line_spacing * em_px(size, scale, canvas, font_path)


def matched_size(size: float, font_path: str, other_path: str) -> float:
    """Size for text in `other_path` so its letters match `font_path` at `size`."""
    return size * span_ratio(other_path) / span_ratio(font_path)


# --- reading the font file ---------------------------------------------------------

def _tables(data: bytes, offset: int = 0) -> dict[str, tuple[int, int]]:
    """{tag: (offset, length)} of the tables in a TrueType/OpenType font."""
    if data[:4] == b"ttcf":                      # a collection: use the first font
        offset = struct.unpack_from(">I", data, 12)[0]
    num = struct.unpack_from(">H", data, offset + 4)[0]
    tables = {}
    for i in range(num):
        tag, _, off, length = struct.unpack_from(">4sIII", data, offset + 12 + 16 * i)
        tables[tag.decode("latin1")] = (off, length)
    return tables


@lru_cache(maxsize=16)
def _advances(font_path: str) -> tuple[int, dict[int, int], list[int]] | None:
    """(unitsPerEm, {char code: glyph id}, [advance width per glyph]) of a font file."""
    try:
        data = Path(font_path).read_bytes()
        t = _tables(data)
        upem = struct.unpack_from(">H", data, t["head"][0] + 18)[0]
        n_metrics = struct.unpack_from(">H", data, t["hhea"][0] + 34)[0]
        hmtx = t["hmtx"][0]
        adv = [struct.unpack_from(">H", data, hmtx + 4 * i)[0] for i in range(n_metrics)]
        return upem, _cmap(data, t["cmap"][0]), adv
    except (OSError, KeyError, struct.error, IndexError):
        return None


def _cmap(data: bytes, base: int) -> dict[int, int]:
    """Character → glyph map. Handles cmap formats 0, 4, 6 and 12 (all fonts we meet)."""
    n = struct.unpack_from(">H", data, base + 2)[0]
    records = [struct.unpack_from(">HHI", data, base + 4 + 8 * i) for i in range(n)]
    # prefer Unicode full / BMP, then Windows Symbol (FM fonts are "symbol" fonts: codes at U+F020…)
    order = {(3, 10): 0, (0, 4): 1, (3, 1): 2, (0, 3): 3, (3, 0): 4, (1, 0): 5}
    out: dict[int, int] = {}
    for pid, eid, off in sorted(records, key=lambda r: order.get((r[0], r[1]), 9)):
        sub = base + off
        fmt = struct.unpack_from(">H", data, sub)[0]
        m: dict[int, int] = {}
        if fmt == 0:
            m = {c: data[sub + 6 + c] for c in range(256)}
        elif fmt == 4:
            segs = struct.unpack_from(">H", data, sub + 6)[0] // 2
            ends = struct.unpack_from(f">{segs}H", data, sub + 14)
            starts = struct.unpack_from(f">{segs}H", data, sub + 16 + 2 * segs)
            deltas = struct.unpack_from(f">{segs}h", data, sub + 16 + 4 * segs)
            ro_pos = sub + 16 + 6 * segs
            offsets = struct.unpack_from(f">{segs}H", data, ro_pos)
            for i in range(segs):
                for c in range(starts[i], ends[i] + 1):
                    if c == 0xFFFF:
                        continue
                    if offsets[i] == 0:
                        g = (c + deltas[i]) & 0xFFFF
                    else:
                        g = struct.unpack_from(">H", data, ro_pos + 2 * i + offsets[i] + 2 * (c - starts[i]))[0]
                        g = (g + deltas[i]) & 0xFFFF if g else 0
                    m[c] = g
        elif fmt == 6:
            first, count = struct.unpack_from(">HH", data, sub + 6)
            m = {first + i: struct.unpack_from(">H", data, sub + 10 + 2 * i)[0] for i in range(count)}
        elif fmt == 12:
            groups = struct.unpack_from(">I", data, sub + 12)[0]
            for i in range(groups):
                s, e, g = struct.unpack_from(">III", data, sub + 16 + 12 * i)
                for c in range(s, min(e, s + 0xFFFF) + 1):
                    m[c] = g + c - s
        for c, g in m.items():
            out.setdefault(c, g)
    return out


def text_width(text: str, font_path: str, em: float) -> float:
    """Width in pixels of `text` drawn at `em` pixels in this font (no kerning: close enough to wrap)."""
    info = _advances(font_path)
    if not info:
        return len(text) * em * 0.55
    upem, cmap, adv = info
    total = 0
    for ch in text:
        c = ord(ch)
        g = cmap.get(c) or cmap.get(0xF000 + c) or 0      # symbol fonts keep ASCII at U+F0xx
        total += adv[min(g, len(adv) - 1)]
    return total * em / upem


@lru_cache(maxsize=64)
def span_ratio(font_path: str) -> float:
    """(ascender + descender) / unitsPerEm of a font file."""
    try:
        data = Path(font_path).read_bytes()
        t = _tables(data)
        upem = struct.unpack_from(">H", data, t["head"][0] + 18)[0]
        asc = desc = 0
        if "OS/2" in t and t["OS/2"][1] >= 72:
            asc, desc = struct.unpack_from(">hh", data, t["OS/2"][0] + 68)   # sTypoAscender/Descender
        if asc <= 0 and "hhea" in t:
            asc, desc = struct.unpack_from(">hh", data, t["hhea"][0] + 4)    # fall back to hhea
        ratio = (asc + abs(desc)) / upem if upem else 0
        return ratio if 0.4 < ratio < 3 else DEFAULT_SPAN
    except (OSError, KeyError, struct.error, IndexError):
        return DEFAULT_SPAN
