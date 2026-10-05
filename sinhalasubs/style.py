"""How the subtitles look: font, size, colours, outline, shadow, box and position."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path


def font_dirs() -> list[Path]:
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        return [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", local / "Microsoft/Windows/Fonts"]
    return [Path("/Library/Fonts"), Path.home() / "Library/Fonts", Path("/System/Library/Fonts")]


def find_font(*names: str) -> str:
    """First installed font whose file name starts with one of `names` (case ignored)."""
    files = [f for d in font_dirs() if d.is_dir() for f in d.iterdir()
             if f.suffix.lower() in (".ttf", ".otf", ".ttc")]
    for name in names:
        for f in files:
            if f.name.lower().startswith(name.lower()):
                return f.as_posix()
    return ""


def fm_fonts() -> list[str]:
    """Every FM font installed on this computer."""
    return sorted({f.as_posix() for d in font_dirs() if d.is_dir() for f in d.iterdir()
                   if f.name.lower().startswith("fm") and f.suffix.lower() in (".ttf", ".otf")})


@dataclass
class SubtitleStyle:
    font_path: str = ""              # "" = FM-Abhaya if installed
    convert_to_fm: bool = True       # write FM text (needs an FM font)
    english_font_path: str = ""      # font for English words ("" = Arial Bold)
    size: float = 12.0               # CapCut's text size
    color: str = "#FFFFFF"
    bold: bool = False
    stroke_enabled: bool = True
    stroke_color: str = "#000000"
    stroke_width: float = 0.08       # 0–0.2, like CapCut's outline slider / 100
    shadow_enabled: bool = False
    shadow_color: str = "#000000"
    shadow_alpha: float = 0.65
    shadow_distance: float = 8.0
    shadow_angle: float = -45.0
    background_enabled: bool = False
    background_color: str = "#000000"
    background_alpha: float = 0.6
    pos_x: float = 0.0               # -1 left ... 1 right
    pos_y: float = -0.75             # -1 bottom ... 1 top
    scale: float = 1.0
    line_max_width: float = 0.82     # share of the video width before a line wraps

    # extra looks
    glow_enabled: bool = False       # a soft wide outline behind the letters
    glow_color: str = "#FFD60A"
    glow_width: float = 0.18
    glow_alpha: float = 0.45
    gradient_enabled: bool = False   # top-to-bottom colour fade: color → gradient_color
    gradient_color: str = "#FFD60A"

    # caption style (see captions.py)
    caption_mode: str = "classic"    # classic | karaoke | reveal | single | keyword
    words_per_caption: int = 0       # 0 = the whole subtitle at once
    text_case: str = "none"          # none | upper | lower (English letters only)
    hl_color: str = "#FFD60A"        # the word being spoken
    spoken_color: str = ""           # words already spoken ("" = same as color)
    hl_scale: float = 1.0            # the spoken word can be a bit bigger

    # animations (keys from data/animations.json, "" = none)
    intro: str = ""
    intro_duration: float = 0.35
    outro: str = ""
    outro_duration: float = 0.35
    loop: str = ""

    def resolved_font(self) -> str:
        font = self.font_path or find_font("FM-Abhaya", "FM-Malithi", "FM-Basuru", "FM-")
        if not font:
            raise RuntimeError("No FM font found. Install FM-Abhaya, or pick a font in the style.")
        return font

    def resolved_english_font(self) -> str:
        return self.english_font_path or find_font("arialbd", "arial", "segoeuib") or self.resolved_font()

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "SubtitleStyle":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in json.loads(text).items() if k in known})
