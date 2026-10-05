"""Where a subtitle's lines break.

CapCut wraps its Auto captions itself, but a normal text clip is never wrapped: a long
line just runs off the video. So we break lines ourselves, measuring each word with the
real font (capcut.metrics.text_width). The preview uses the same breaks, so what you see
in SinhalaSubs is what you get in CapCut.
"""

from __future__ import annotations

from .capcut import metrics
from .fm_converter import fm_runs
from .style import SubtitleStyle


def tokens(words: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(word, role) pairs → one entry per real word (a classic subtitle is one long 'word')."""
    return [(w, role) for text, role in words for w in text.split()]


def word_width(word: str, style: SubtitleStyle, em: float, en_em: float) -> float:
    font, en_font = style.resolved_font(), style.resolved_english_font()
    if not style.convert_to_fm:
        return metrics.text_width(word, font, em)
    return sum(metrics.text_width(t, en_font if english else font, en_em if english else em)
               for t, english in fm_runs(word))


def breaks(words: list[tuple[str, str]], style: SubtitleStyle, canvas: tuple[float, float]) -> set[int]:
    """Indexes of the words after which a new line starts (for `tokens(words)`)."""
    toks = tokens(words)
    if len(toks) < 2:
        return set()
    try:
        font = style.resolved_font()
    except RuntimeError:
        return set()
    en_font = style.resolved_english_font()
    em = metrics.em_px(style.size, 1.0, canvas, font)            # wrapping happens before clip scale
    en_size = metrics.matched_size(style.size, font, en_font)
    en_em = metrics.em_px(en_size, 1.0, canvas, en_font)
    space = metrics.text_width(" ", font, em)
    limit = style.line_max_width * canvas[0]

    widths = [word_width(w, style, em, en_em) * (style.hl_scale if role == "active" else 1.0)
              for w, role in toks]
    return balanced_breaks(widths, space, limit)


def balanced_breaks(widths: list[float], space: float, limit: float) -> set[int]:
    """Fewest lines that fit in `limit`, then as even as possible.

    Two even lines look better than a long line and one lonely word. n is small (a subtitle
    has ~10 words), so we simply try every split (dynamic programming).
    """
    n = len(widths)

    def line(i: int, j: int) -> float:                  # width of words i..j-1 on one line
        return sum(widths[i:j]) + space * (j - i - 1)

    # fewest lines: greedy
    lines, width = 1, 0.0
    for w in widths:
        if width and width + space + w > limit:
            lines, width = lines + 1, w
        else:
            width = w if not width else width + space + w

    # best[k][j]: smallest "widest line" when words 0..j-1 are put on k lines
    inf = float("inf")
    best = [[inf] * (n + 1) for _ in range(lines + 1)]
    cut = [[0] * (n + 1) for _ in range(lines + 1)]
    best[0][0] = 0.0
    for k in range(1, lines + 1):
        for j in range(1, n + 1):
            for i in range(k - 1, j):
                w = line(i, j)
                if w > limit and j - i > 1:            # a single too-long word is allowed alone
                    continue
                v = max(best[k - 1][i], w)
                if v < best[k][j]:
                    best[k][j], cut[k][j] = v, i
    if best[lines][n] == inf:
        return set(range(n - 1))
    out, j = set(), n
    for k in range(lines, 1, -1):
        i = cut[k][j]
        out.add(i - 1)
        j = i
    return out
