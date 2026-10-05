"""Ready-made caption looks for the Caption Studio, plus the user's own saved looks.

A look only sets how the text looks (colours, outline, glow, box, word highlight,
animation). The font, size and position the user picked are kept.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, replace

from .config import app_data_dir
from .style import SubtitleStyle

# Fields a look controls. Everything else (font, size, position, FM) stays the user's choice.
KEEP = {"font_path", "convert_to_fm", "english_font_path", "size", "pos_x", "pos_y", "scale", "line_max_width"}
LOOK_FIELDS = [f.name for f in fields(SubtitleStyle) if f.name not in KEEP]
CATEGORIES = ["All", "Favourites", "Clean", "Boxed", "Glow", "Karaoke", "Animated", "Mine"]


@dataclass
class Look:
    name: str
    category: str
    values: dict = field(default_factory=dict)
    builtin: bool = True

    def apply(self, style: SubtitleStyle) -> SubtitleStyle:
        """`style` with this look: look fields reset to defaults, then the look's values."""
        base = SubtitleStyle()
        reset = {k: getattr(base, k) for k in LOOK_FIELDS}
        return replace(style, **{**reset, **{k: v for k, v in self.values.items() if k in LOOK_FIELDS}})

    def matches(self, query: str) -> bool:
        q = query.lower().strip()
        return not q or q in self.name.lower() or q in self.category.lower()


def _l(name: str, category: str, **values) -> Look:
    return Look(name, category, values)


BUILTIN = [
    # Clean
    _l("Classic White", "Clean"),
    _l("Soft Shadow", "Clean", stroke_enabled=False, shadow_enabled=True, shadow_alpha=0.8, shadow_distance=6),
    _l("Sunny Yellow", "Clean", color="#FFE14D", stroke_width=0.1),
    _l("Bold Outline", "Clean", bold=True, stroke_width=0.14),
    _l("Gold Fade", "Clean", gradient_enabled=True, color="#FFFFFF", gradient_color="#F5B700",
       stroke_color="#3A2400", stroke_width=0.1),
    # Boxed
    _l("Black Box", "Boxed", stroke_enabled=False, background_enabled=True, background_alpha=0.65),
    _l("Yellow Box", "Boxed", color="#111111", stroke_enabled=False, background_enabled=True,
       background_color="#FFD60A", background_alpha=1.0),
    _l("White Box", "Boxed", color="#111111", stroke_enabled=False, background_enabled=True,
       background_color="#FFFFFF", background_alpha=0.92),
    # Glow
    _l("Neon Blue", "Glow", stroke_enabled=False, glow_enabled=True, glow_color="#3AB0FF", glow_alpha=0.6),
    _l("Neon Pink", "Glow", stroke_enabled=False, glow_enabled=True, glow_color="#FF4FD8", glow_alpha=0.6),
    _l("Warm Glow", "Glow", color="#FFF4D6", stroke_color="#5A3300", stroke_width=0.06,
       glow_enabled=True, glow_color="#FF9A1F", glow_alpha=0.5),
    # Karaoke / word styles
    _l("Karaoke Yellow", "Karaoke", caption_mode="karaoke", hl_color="#FFD60A", spoken_color="#FFD60A",
       stroke_width=0.1),
    _l("Green Pop", "Karaoke", caption_mode="karaoke", words_per_caption=4, hl_color="#3CFF6B",
       hl_scale=1.15, stroke_width=0.12, bold=True),
    _l("Reels 3 Words", "Karaoke", caption_mode="karaoke", words_per_caption=3, text_case="upper",
       hl_color="#00E5FF", stroke_width=0.12, bold=True),
    _l("One Word Pop", "Karaoke", caption_mode="single", hl_color="#FFFFFF", hl_scale=1.2,
       stroke_width=0.14, intro="pop_up", intro_duration=0.15),
    _l("Word Reveal", "Karaoke", caption_mode="reveal", hl_color="#FFD60A"),
    _l("Red Keyword", "Karaoke", caption_mode="keyword", hl_color="#FF4040", hl_scale=1.2, bold=True),
    # Animated
    _l("Fade In & Out", "Animated", intro="fade_in", outro="fade_out"),
    _l("Slide Up", "Animated", intro="slide_up", outro="fade_out"),
    _l("Pop Up", "Animated", intro="pop_up", outro="blur_out", stroke_width=0.12),
    _l("Typewriter", "Animated", intro="typewriter", intro_duration=0.8, background_enabled=True,
       background_alpha=0.55, stroke_enabled=False),
]


# --- the user's own looks and favourites ------------------------------------------------------

def _file():
    return app_data_dir() / "looks.json"


def _read() -> dict:
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    _file().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def user_looks() -> list[Look]:
    return [Look(d["name"], "Mine", d.get("values", {}), builtin=False) for d in _read().get("looks", [])]


def save_user_look(name: str, style: SubtitleStyle) -> Look:
    values = {k: v for k, v in asdict(style).items() if k in LOOK_FIELDS}
    data = _read()
    looks = [d for d in data.get("looks", []) if d.get("name") != name]
    looks.append({"name": name, "values": values})
    data["looks"] = looks
    _write(data)
    return Look(name, "Mine", values, builtin=False)


def delete_user_look(name: str) -> None:
    data = _read()
    data["looks"] = [d for d in data.get("looks", []) if d.get("name") != name]
    _write(data)


def favourites() -> set[str]:
    return set(_read().get("favourites", []))


def set_favourite(name: str, on: bool) -> None:
    data = _read()
    favs = set(data.get("favourites", []))
    favs.add(name) if on else favs.discard(name)
    data["favourites"] = sorted(favs)
    _write(data)


def all_looks() -> list[Look]:
    return BUILTIN + user_looks()
