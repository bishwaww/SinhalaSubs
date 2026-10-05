"""Sinhala Unicode -> FM font text.

CapCut cannot shape Sinhala Unicode properly, so we write the text for
"FM" fonts (FM-Abhaya, FM-Malithi, FM-Derana ...). These old fonts draw
Sinhala letters in place of normal keyboard characters, e.g. the font
draws "ක" when the text says "l". All FM fonts share this layout.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

RULES_FILE = Path(__file__).parent / "data" / "fm_abhaya_rules.json"

# Punctuation must move too, because in FM fonts "," is the letter "ල".
# str.maketrans + str.translate replaces everything in ONE pass, so ":" -> "("
# is never turned again into "^" by the "(" -> "^" entry.
PUNCTUATION = str.maketrans({
    ",": '"', ".": "'", "(": "^", ")": "&", "%": "]", "/": "$", "?": "@",
    "=": "}", "+": "¬", ":": "(", ";": "¦", "!": "æ", "*": ")", "–": "¤",
    "÷": "­", "'": "Z", "’": "Z", "‘": "z", '"': "˜", "“": "˜", "”": "˜",
    "×": "«",
    "‌": None,  # zero-width non-joiner: FM fonts don't need it
})

SINHALA = re.compile(r"[඀-෿]")
LATIN = re.compile(r"[A-Za-z]")
TOKEN = re.compile(r"\S+\s*|\s+")


@lru_cache(maxsize=1)
def load_rules() -> list[tuple[str, str]]:
    """Ordered (unicode, fm) pairs. Longest letter groups come first."""
    data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    return [(uni, fm) for uni, fm in data["rules"]]


def unicode_to_fm(text: str) -> str:
    """Convert Sinhala Unicode text to FM font text."""
    text = text.translate(PUNCTUATION)
    for uni, fm in load_rules():
        if uni in text:
            text = text.replace(uni, fm)
    return text


def has_sinhala(text: str) -> bool:
    return bool(SINHALA.search(text))


def is_english_word(word: str) -> bool:
    return bool(LATIN.search(word)) and not SINHALA.search(word)


def script_runs(text: str) -> list[tuple[str, bool]]:
    """Split text into pieces of (chunk, is_english).

    An FM font can't show English letters (it would draw Sinhala instead),
    so English words must be written with a normal font.
    "අලුත් layer එකක්" -> [("අලුත් ", False), ("layer ", True), ("එකක්", False)]
    """
    runs: list[tuple[str, bool]] = []
    for token in TOKEN.findall(text):
        english = is_english_word(token.strip()) if token.strip() else (runs[-1][1] if runs else False)
        if runs and runs[-1][1] == english:
            runs[-1] = (runs[-1][0] + token, english)
        else:
            runs.append((token, english))
    return runs


def fm_runs(text: str) -> list[tuple[str, bool]]:
    """Like script_runs, but the Sinhala pieces are already converted to FM."""
    return [(chunk if english else unicode_to_fm(chunk), english)
            for chunk, english in script_runs(text)]
