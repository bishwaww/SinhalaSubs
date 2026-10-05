"""Languages we can make captions for.

Sinhala is special: CapCut cannot shape Sinhala Unicode, so it is written in FM-font
letters. Every other language is written as normal Unicode text with a font that has
its letters.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str                  # ISO 639-1, also what Whisper expects
    name: str                  # English name, used in the Gemini prompt
    native: str                # how speakers write it
    bcp47: str                 # language tag CapCut stores on captions
    script: str = ""           # regex character class of its own letters ("" = Latin, don't check)
    fonts: tuple[str, ...] = ("arialbd", "arial")   # font file name starts, first installed wins
    fm: bool = False           # write with FM (legacy Sinhala) fonts
    mixes_english: bool = True  # speakers often drop English words in (ask how to write them)


_INDIC = ("Nirmala", "NirmalaB")

LANGUAGES: list[Language] = [
    Language("si", "Sinhala", "සිංහල", "si-LK", r"඀-෿", ("FM-Abhaya", "FM-"), fm=True),
    Language("en", "English", "English", "en-US", mixes_english=False),
    Language("ta", "Tamil", "தமிழ்", "ta-IN", r"஀-௿", _INDIC),
    Language("hi", "Hindi", "हिन्दी", "hi-IN", r"ऀ-ॿ", _INDIC),
    Language("bn", "Bengali", "বাংলা", "bn-IN", r"ঀ-৿", _INDIC),
    Language("te", "Telugu", "తెలుగు", "te-IN", r"ఀ-౿", _INDIC),
    Language("ml", "Malayalam", "മലയാളം", "ml-IN", r"ഀ-ൿ", _INDIC),
    Language("ur", "Urdu", "اردو", "ur-PK", r"؀-ۿ", ("arialbd", "tahomabd")),
    Language("ar", "Arabic", "العربية", "ar-SA", r"؀-ۿ", ("arialbd", "tahomabd")),
    Language("zh", "Chinese (Simplified)", "中文", "zh-CN", r"一-鿿", ("msyhbd", "msyh")),
    Language("ja", "Japanese", "日本語", "ja-JP", r"぀-ヿ一-鿿", ("YuGothB", "YuGoth", "msgothic")),
    Language("ko", "Korean", "한국어", "ko-KR", r"가-힯", ("malgunbd", "malgun")),
    Language("th", "Thai", "ไทย", "th-TH", r"฀-๿", ("LeelaUIb", "leelawui")),
    Language("vi", "Vietnamese", "Tiếng Việt", "vi-VN"),
    Language("id", "Indonesian", "Bahasa Indonesia", "id-ID"),
    Language("ms", "Malay", "Bahasa Melayu", "ms-MY"),
    Language("tl", "Filipino", "Filipino", "fil-PH"),
    Language("es", "Spanish", "Español", "es-ES"),
    Language("pt", "Portuguese", "Português", "pt-BR"),
    Language("fr", "French", "Français", "fr-FR"),
    Language("de", "German", "Deutsch", "de-DE"),
    Language("it", "Italian", "Italiano", "it-IT"),
    Language("ru", "Russian", "Русский", "ru-RU", r"Ѐ-ӿ"),
    Language("tr", "Turkish", "Türkçe", "tr-TR"),
]
BY_CODE = {lang.code: lang for lang in LANGUAGES}


def get(code: str) -> Language:
    return BY_CODE.get(code, LANGUAGES[0])


def default_font(lang: Language) -> str:
    from .style import find_font
    return find_font(*lang.fonts) or find_font("arialbd", "arial", "segoeuib")
