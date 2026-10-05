"""Captions in other languages."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sinhalasubs import languages  # noqa: E402
from sinhalasubs.capcut import writer  # noqa: E402
from sinhalasubs.models import Cue  # noqa: E402
from sinhalasubs.style import SubtitleStyle  # noqa: E402
from sinhalasubs.transcribe import TRANSCRIBE_PROMPT, TranscribeOptions, fix_script, language_rules  # noqa: E402


def _prompt(code):
    who, script, english = language_rules(TranscribeOptions(language=code))
    return TRANSCRIBE_PROMPT.format(who=who, duration=10, max_chars=42, max_dur=6,
                                    script_rules=script, english_rule=english, glossary="")


def test_prompts_follow_the_language():
    assert "Sinhala Unicode letters" in _prompt("si")
    ta = _prompt("ta")
    assert "Tamil (தமிழ்)" in ta and "Sinhala" not in ta and "English letters" in ta
    en = _prompt("en")
    assert "English videos" in en and "English word" not in en      # no code-mixing rule for English


def test_sinhala_repair_only_for_sinhala():
    cues = [Cue(0, 1, "हिन्दी")]
    stats = fix_script(cues, None, "", TranscribeOptions(language="hi", polish=False), print)
    assert stats.get("skipped") and cues[0].text == "हिन्दी"


def test_every_language_has_a_font_and_tag():
    for lang in languages.LANGUAGES:
        assert languages.default_font(lang), lang.code
        assert "-" in lang.bcp47


def test_unicode_captions_get_their_language_tag():
    style = SubtitleStyle(font_path="C:/Windows/Fonts/arialbd.ttf", english_font_path="C:/Windows/Fonts/arialbd.ttf",
                          convert_to_fm=False)
    data = {"materials": {}, "tracks": [], "duration": 0, "config": {}}
    writer.apply_subtitles(data, [Cue(0, 2, "வணக்கம் நண்பர்களே")], style, as_captions=True, language="ta")
    [m] = data["materials"]["texts"]
    assert m["language"] == "ta-IN" and m["group_id"].startswith("ta-IN_")
    assert json.loads(m["content"])["text"] == "வணக்கம் நண்பர்களே"   # real Unicode, no FM
