"""Text animations: the CapCut entry to write, and how our preview imitates it.

CapCut animations are downloadable "effects" with a resource id. We write the id
into the draft; CapCut downloads the effect the first time the project is opened
if it is not already in its cache.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CATALOG = Path(__file__).parent / "data" / "animations.json"
CATEGORY = {"in": ("ruchang", "In"), "out": ("chuchang", "Out"), "loop": ("xunhuan", "Loop")}


@dataclass(frozen=True)
class Anim:
    key: str
    kind: str          # "in" | "out" | "loop"
    name: str
    resource_id: str
    duration: float    # default length in seconds
    effect: str        # preview: fade | slide_up | slide_right | slide_left | pop | type | drop | flash


@lru_cache(maxsize=1)
def catalog() -> dict[str, list[Anim]]:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    return {kind: [Anim(kind=kind, **a) for a in data[kind]] for kind in ("in", "out", "loop")}


def get(key: str) -> Anim | None:
    return next((a for group in catalog().values() for a in group if a.key == key), None)


def capcut_entry(anim: Anim, duration: float) -> dict:
    """One item of a CapCut 'material_animations' list."""
    from .capcut.project import effect_cache_dir

    cat_id, cat_name = CATEGORY[anim.kind]
    cache = effect_cache_dir(anim.resource_id)
    return {
        "id": anim.resource_id, "type": anim.kind, "start": 0, "duration": int(round(duration * 1_000_000)),
        "path": cache, "platform": "all", "resource_id": anim.resource_id,
        "third_resource_id": anim.resource_id, "source_platform": 1, "name": anim.name,
        "category_id": cat_id, "category_name": cat_name, "panel": "", "material_type": "sticker",
        "anim_adjust_params": None, "request_id": "",
    }


# --- preview ----------------------------------------------------------------------------------

@dataclass
class Fx:
    """How to draw the text at one moment: see preview.paint_caption."""
    alpha: float = 1.0
    scale: float = 1.0
    dx: float = 0.0      # in "em" units
    dy: float = 0.0
    reveal: float = 1.0  # share of the text shown (typewriter)


def _ease_out(p: float) -> float:
    return 1 - (1 - p) ** 3


def _ease_back(p: float) -> float:
    c = 1.7
    return 1 + (c + 1) * (p - 1) ** 3 + c * (p - 1) ** 2


def _apply(fx: Fx, effect: str, p: float, entering: bool) -> None:
    """p goes 0 → 1 while the animation runs (for 'out' we pass it reversed)."""
    e = _ease_out(p)
    if effect == "fade":
        fx.alpha *= e
    elif effect == "slide_up":
        fx.alpha *= e
        fx.dy += (1 - e) * 1.2
    elif effect == "slide_right":
        fx.alpha *= e
        fx.dx -= (1 - e) * 2.5
    elif effect == "slide_left":
        fx.alpha *= e
        fx.dx += (1 - e) * 2.5
    elif effect == "pop":
        fx.scale *= max(0.0, _ease_back(p)) if entering else e
        fx.alpha *= min(1.0, p * 3)
    elif effect == "type":
        fx.reveal = p
    elif effect == "drop":
        fx.alpha *= e
        fx.dy += (1 - e) * 1.5


def effect_at(intro: str, intro_dur: float, outro: str, outro_dur: float, loop: str,
              t: float, length: float) -> Fx:
    """Animation state `t` seconds into a subtitle that lasts `length` seconds."""
    fx = Fx()
    a_in, a_out, a_loop = get(intro), get(outro), get(loop)
    if a_in and t < intro_dur:
        _apply(fx, a_in.effect, max(0.0, t / intro_dur), True)
    if a_out and t > length - outro_dur:
        _apply(fx, a_out.effect, max(0.0, (length - t) / outro_dur), False)
    if a_loop and a_loop.effect == "flash":
        fx.alpha *= 0.55 + 0.45 * math.cos(2 * math.pi * t / max(0.05, a_loop.duration * 2))
    return fx
