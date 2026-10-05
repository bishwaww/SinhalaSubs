"""Write subtitles into a CapCut project as a new text track.

Each subtitle becomes one text clip. We copy the exact JSON shape CapCut itself
saves (data/capcut_text_template.json) and fill in our text, times and style.

Close the project in CapCut before writing (go back to CapCut's home screen),
otherwise CapCut saves its own copy on top of ours.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import time
import uuid
from functools import lru_cache
from pathlib import Path

from .. import animations, layout
from ..captions import frames, word_times
from ..config import app_data_dir
from ..fm_converter import fm_runs
from ..models import Cue
from ..style import SubtitleStyle
from .metrics import matched_size
from .project import US, Timeline, read_draft_json

TRACK_NAME = "SinhalaSubs"
TEMPLATE = Path(__file__).parent.parent / "data" / "capcut_text_template.json"


@lru_cache(maxsize=1)
def _template() -> dict:
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def _uid() -> str:
    return str(uuid.uuid4()).upper()


def _rgb(hex_color: str) -> list[float]:
    h = hex_color.lstrip("#")
    return [round(int(h[i:i + 2], 16) / 255, 4) for i in (0, 2, 4)]


def _utf16_len(s: str) -> int:
    """CapCut counts text positions in UTF-16 units, like JavaScript does."""
    return len(s.encode("utf-16-le")) // 2


def _solid(hex_color: str) -> dict:
    return {"render_type": "solid", "solid": {"color": _rgb(hex_color)}}


def _fill(color: str, style: SubtitleStyle, role: str) -> dict:
    """Solid colour, or a top-to-bottom gradient (the format CapCut's own text styles use)."""
    if style.gradient_enabled and role != "active":
        return {"render_type": "gradient", "gradient": {
            "angle": 90, "color": [_rgb(color), _rgb(style.gradient_color)],
            "alpha": [1, 1], "percent": [0, 1], "mode": "character"}}
    return _solid(color)


def _strokes(style: SubtitleStyle) -> list[dict]:
    # CapCut draws only one outline per run (a second stroke is ignored), so glow is an effect: see _glow.
    if style.stroke_enabled and style.stroke_width > 0:
        return [{"content": _solid(style.stroke_color), "width": style.stroke_width, "alpha": 1.0, "mode": 0}]
    return []


# CapCut's Text > Glow is a "bloom" effect attached to the clip. Found by switching it on in CapCut
# and reading the saved draft. "glowing neon" is the free preset.
GLOW_EFFECT_ID = "7194814295517958657"
GLOW_FLAG = 64                   # bit CapCut sets in the text's check_flag when glow is on


def _glow(style: SubtitleStyle) -> dict:
    from .project import effect_cache_dir
    return {
        "id": _uid(), "effect_id": GLOW_EFFECT_ID, "resource_id": GLOW_EFFECT_ID, "third_resource_id": "",
        "name": "glowing neon", "report_name": "", "type": "bloom", "sub_type": "none",
        "path": effect_cache_dir(GLOW_EFFECT_ID), "value": 0.0, "visible": True, "item_effect_type": 0,
        "category_id": "", "category_name": "", "category_key": "", "sub_category_id": "",
        "sub_category_name": "", "platform": "all", "apply_target_type": 0, "source_platform": 1,
        "version": "", "adjust_params": [], "time_range": None, "formula_id": "",
        "enable_skin_tone_correction": False, "algorithm_artifact_path": "", "intensity_key": "",
        "face_adjust_params": [], "exclusion_group": [], "panel_id": "text_glow",
        # CapCut's sliders: Intensity 0–100 → strength 0–1, Range 0–100 → range 0–1
        "bloom_params": {"color": style.glow_color, "strength": round(style.glow_alpha, 3),
                         "range": round(style.glow_width, 3), "dir_x": 0.5, "dir_y": 0.5},
        "request_id": "", "color_match_info": None, "multi_language_current": "", "lumi_hub_path": "",
        "covering_relation_change": 0, "beauty_face_auto_preset_id": "", "beauty_body_auto_preset_id": "",
        "beauty_face_auto_retouch_info": {"face_id": [], "beauty_face_auto_retouch_id": ""},
        "smart_color_mode": 0, "is_from_intelligent_quality": False,
    }


def content_json_words(words: list[tuple[str, str]], style: SubtitleStyle,
                       canvas: tuple[float, float] | None = None) -> str:
    """The 'content' string of a text clip: the text plus one style run per word piece.

    `words` are (text, role) pairs from captions.frames(); role is normal | active | spoken.
    With `canvas` (the video size) long lines are broken with "\n", because CapCut never
    wraps a text clip by itself.
    """
    font, en_font = style.resolved_font(), style.resolved_english_font()
    en_size = round(matched_size(style.size, font, en_font), 2)   # same letter height as Sinhala
    colors = {"normal": style.color, "active": style.hl_color, "spoken": style.spoken_color or style.color}
    strokes = _strokes(style)

    toks = layout.tokens(words)
    cuts = layout.breaks(words, style, canvas) if canvas else set()
    pieces: list[tuple[str, bool, str]] = []            # (text, english, role)
    for n, (word, role) in enumerate(toks):
        chunks = fm_runs(word) if style.convert_to_fm else [(word, False)]
        if n + 1 < len(toks):                             # the space (or line break) goes with this word
            last_text, last_en = chunks[-1]
            chunks = chunks[:-1] + [(last_text + ("\n" if n in cuts else " "), last_en)]
        pieces += [(t, en, role) for t, en in chunks if t]

    styles, pos = [], 0
    for text, english, role in pieces:
        n = _utf16_len(text)
        other = english and style.convert_to_fm
        size = (en_size if other else style.size) * (style.hl_scale if role == "active" else 1.0)
        run = {
            "fill": {"content": _fill(colors[role], style, role)},
            "font": {"path": en_font if other else font, "id": ""},
            "size": round(size, 2),
            "useLetterColor": True,
            "range": [pos, pos + n],
        }
        if style.bold:
            run["bold"] = True
        if strokes:
            run["strokes"] = strokes
        if style.shadow_enabled:
            run["shadows"] = [{
                "thickness_projection_angle": -45, "thickness_projection_enable": False, "diffuse": 0,
                "alpha": style.shadow_alpha, "distance": style.shadow_distance,
                "content": _solid(style.shadow_color), "angle": style.shadow_angle,
                "thickness_projection_distance": 0,
            }]
        styles.append(run)
        pos += n
    body = "".join(t for t, _, _ in pieces)
    return json.dumps({"text": body, "styles": styles}, ensure_ascii=False, separators=(",", ":"))


def content_json(text: str, style: SubtitleStyle) -> str:
    """Content for a plain one-line subtitle."""
    return content_json_words([(text, "normal")], style)


def _text_material(words: list[tuple[str, str]], style: SubtitleStyle,
                   canvas: tuple[float, float] | None = None) -> dict:
    m = copy.deepcopy(_template()["material"])
    m.update(
        id=_uid(), content=content_json_words(words, style, canvas), font_path=style.resolved_font(),
        font_size=style.size, text_color=style.color, line_max_width=style.line_max_width,
        border_color=style.stroke_color if style.stroke_enabled else "",
        border_width=style.stroke_width, has_shadow=style.shadow_enabled,
        shadow_color=style.shadow_color if style.shadow_enabled else "",
        shadow_alpha=style.shadow_alpha, shadow_distance=style.shadow_distance,
        shadow_angle=style.shadow_angle,
        background_color=style.background_color if style.background_enabled else "",
        background_alpha=style.background_alpha, background_style=1 if style.background_enabled else 0,
        name=" ".join(w for w, _ in words)[:40],
    )
    return m


def _animation_material(style: SubtitleStyle, dur: float, first: bool, last: bool) -> dict:
    """The clip's animations: intro on the first frame of a subtitle, outro on the last, loop on all."""
    a = copy.deepcopy(_template()["animation"])
    a["id"] = _uid()
    intro = animations.get(style.intro) if first else None
    outro = animations.get(style.outro) if last else None
    d_in = min(style.intro_duration, dur) if intro else 0.0
    d_out = min(style.outro_duration, dur) if outro else 0.0
    if d_in + d_out > dur:                     # both on a short clip: share its time
        k = dur / (d_in + d_out)
        d_in, d_out = d_in * k, d_out * k
    if intro:
        a["animations"].append(animations.capcut_entry(intro, d_in))
    if outro:
        a["animations"].append(animations.capcut_entry(outro, d_out))
    loop = animations.get(style.loop)
    if loop:
        a["animations"].append(animations.capcut_entry(loop, loop.duration))
    return a


def _segment(material_id: str, anim_id: str, start_s: float, end_s: float, style: SubtitleStyle,
             render_index: int, track_index: int) -> dict:
    s = copy.deepcopy(_template()["segment"])
    start = int(round(start_s * US))
    s.update(
        id=_uid(), material_id=material_id, extra_material_refs=[anim_id],
        target_timerange={"start": start, "duration": max(1, int(round(end_s * US)) - start)},
        render_index=render_index, track_render_index=track_index,
    )
    s["clip"]["transform"] = {"x": style.pos_x, "y": style.pos_y}
    s["clip"]["scale"] = {"x": style.scale, "y": style.scale}
    return s


TASK_PREFIX = "sinhalasubs_"     # our "recognition task" id, so we can find our captions again
CAPTION_LANG = "en-US"           # FM text is plain Latin letters to CapCut


def remove_existing(data: dict) -> int:
    """Take out a text track this tool added before. Returns how many clips were removed."""
    ours = [t for t in data.get("tracks", []) if t.get("type") == "text" and t.get("name") == TRACK_NAME]
    cfg = data.get("config") or {}
    if isinstance(cfg.get("subtitle_taskinfo"), list):
        cfg["subtitle_taskinfo"] = [t for t in cfg["subtitle_taskinfo"]
                                    if not str(t.get("id", "")).startswith(TASK_PREFIX)]
    if not ours:
        return 0
    seg_ids = [s for t in ours for s in t.get("segments", [])]
    mat_ids = {s.get("material_id") for s in seg_ids} | {r for s in seg_ids for r in s.get("extra_material_refs", [])}
    for kind in ("texts", "material_animations", "effects"):
        data["materials"][kind] = [m for m in data["materials"].get(kind, []) if m.get("id") not in mat_ids]
    data["tracks"] = [t for t in data["tracks"] if t not in ours]
    return len(seg_ids)


def caption_words(cue: Cue, body: str, start: float) -> dict:
    """CapCut's word timing for a caption: every word and every space, in ms from the clip start.

    `body` is the text as written in the clip (FM letters), so the pieces join back to it exactly.
    """
    parts = re.split(r"([ \n])", body)                         # words and the separators between them
    tokens, seps = parts[0::2], parts[1::2]
    times = word_times(cue)
    if len(times) != len([t for t in tokens if t]):             # FM changed the word count: share by length
        times = word_times(Cue(cue.start, cue.end, " ".join(t for t in tokens if t)))
    starts, ends, texts = [], [], []
    k = 0
    for i, tok in enumerate(tokens):
        if i:                                                   # the space: zero length, at the word end
            starts.append(ends[-1] if ends else 0)
            ends.append(starts[-1])
            texts.append(seps[i - 1])
        if not tok:
            continue
        w = times[min(k, len(times) - 1)]
        starts.append(max(0, round((w.start - start) * 1000)))
        ends.append(max(starts[-1], round((w.end - start) * 1000)))
        texts.append(tok)
        k += 1
    return {"start_time": starts, "end_time": ends, "text": texts}


def apply_subtitles(data: dict, cues: list[Cue], style: SubtitleStyle, replace: bool = True,
                    as_captions: bool = True, language: str = "si") -> dict:
    """Add one text track with every cue to a loaded draft (changes `data`).

    as_captions=True writes them the way CapCut's own Auto captions are stored: one linked group
    you can restyle with "Apply to all" and see in CapCut's Captions list. Word styles (karaoke …)
    need one clip per word, so those are always written as normal text clips.
    """
    removed = remove_existing(data) if replace else 0
    mats = data.setdefault("materials", {})
    texts, anims = mats.setdefault("texts", []), mats.setdefault("material_animations", [])
    tracks = data.setdefault("tracks", [])
    captions = as_captions and style.caption_mode == "classic"
    cfg_canvas = data.get("canvas_config") or {}
    canvas = (float(cfg_canvas.get("width") or 1920), float(cfg_canvas.get("height") or 1080))
    effects = mats.setdefault("effects", []) if style.glow_enabled else None

    used = [s.get("render_index", 0) for t in tracks if t.get("type") in ("text", "sticker")
            for s in t.get("segments", [])]
    render_index = max(used + [13999]) + 1
    track_index = len(tracks)
    task_id = TASK_PREFIX + uuid.uuid4().hex[:16]
    from ..languages import get as get_language
    # FM text is plain Latin letters to CapCut; other languages are real Unicode text
    lang_tag = CAPTION_LANG if style.convert_to_fm else get_language(language).bcp47
    group_id = f"{lang_tag}_{int(time.time() * 1000)}"

    segments = []
    for cue in sorted(cues, key=lambda c: c.start):
        if not cue.text.strip() or cue.end <= cue.start:
            continue
        parts = frames(cue, style.caption_mode, style.words_per_caption, style.text_case)
        for n, f in enumerate(parts):
            m = _text_material(f.words, style, canvas)
            if captions:
                body = json.loads(m["content"])["text"]
                m.update(type="subtitle", add_type=1, group_id=group_id, language=lang_tag,
                         recognize_task_id=task_id, recognize_text=body,
                         words=caption_words(cue, body, f.start), subtitle_keywords={"range": []})
            a = _animation_material(style, f.end - f.start, n == 0, n == len(parts) - 1)
            texts.append(m)
            anims.append(a)
            seg = _segment(m["id"], a["id"], f.start, f.end, style, render_index, track_index)
            if effects is not None:
                g = _glow(style)
                effects.append(g)
                seg["extra_material_refs"].append(g["id"])
                m["check_flag"] = int(m.get("check_flag", 0)) | GLOW_FLAG
            if captions:
                seg.update(enable_mask_shadow=False, enable_mask_stroke=False)
            segments.append(seg)

    tracks.append({"id": _uid(), "type": "text", "flag": 1 if captions else 0, "attribute": 0,
                   "name": TRACK_NAME, "is_default_name": False, "segments": segments})
    if captions:
        cfg = data.setdefault("config", {})
        if not isinstance(cfg.get("subtitle_taskinfo"), list):
            cfg["subtitle_taskinfo"] = []
        cfg["subtitle_taskinfo"].append({"id": task_id, "type": 10, "language": lang_tag, "content": "",
                                         "remove_invalid_task_id": "", "ai_accurate_recognize_enable": False})
    end = max((s["target_timerange"]["start"] + s["target_timerange"]["duration"] for s in segments), default=0)
    data["duration"] = max(int(data.get("duration", 0)), end)
    return {"removed": removed, "added": len(segments), "subtitles": len(cues), "as_captions": captions}


# --- files ---------------------------------------------------------------------------

def _atomic_write(path: Path, raw: bytes) -> None:
    """Write to a temp file, then swap it in: a crash can never leave a half-written draft."""
    tmp = path.with_name(path.name + ".sinhalasubs-tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)


def _twins(path: Path, draft_id: str) -> list[Path]:
    """CapCut's own copies of the draft (.bak, template-2.tmp …) that hold the same timeline."""
    twins = []
    for f in path.parent.iterdir():
        if f == path or not f.is_file():
            continue
        if f.name.startswith(path.name + ".") or (f.name.startswith("template") and f.suffix == ".tmp"):
            if f.name.endswith(".sinhalasubs-tmp"):
                continue
            try:
                if json.loads(f.read_bytes()).get("id") == draft_id:
                    twins.append(f)
            except (ValueError, OSError, AttributeError):
                pass  # not a copy of this draft: leave it alone
    return twins


def backups_dir(folder: Path) -> Path:
    return app_data_dir() / "backups" / folder.name


def backup(folder: Path, files: list[Path]) -> Path:
    dest = backups_dir(folder) / time.strftime("%Y%m%d-%H%M%S")
    for f in files:
        target = dest / f.relative_to(folder)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
    return dest


def list_backups(folder: Path) -> list[Path]:
    d = backups_dir(folder)
    return sorted((p for p in d.iterdir() if p.is_dir()), reverse=True) if d.is_dir() else []


def restore_backup(folder: Path, backup_dir: Path) -> int:
    count = 0
    for f in backup_dir.rglob("*"):
        if f.is_file():
            _atomic_write(folder / f.relative_to(backup_dir), f.read_bytes())
            count += 1
    return count


def write_to_draft(folder: Path, timeline: Timeline, cues: list[Cue], style: SubtitleStyle,
                   replace: bool = True, as_captions: bool = True, language: str = "si") -> dict:
    """Back up, then write the subtitles into every file that holds this timeline."""
    targets = []
    for f in timeline.files:
        data = read_draft_json(f)
        targets.append((f, data, _twins(f, data.get("id", ""))))

    meta = folder / "draft_meta_info.json"
    all_files = [f for f, _, tw in targets for f in [f, *tw]] + ([meta] if meta.is_file() else [])
    saved_to = backup(folder, all_files)

    stats = {}
    done: dict[str, bytes] = {}          # same draft content -> same new bytes (and the same new ids)
    for f, data, twins in targets:
        key = hashlib.sha1(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()
        if key not in done:
            stats = apply_subtitles(data, cues, style, replace, as_captions, language)
            done[key] = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if timeline.is_main:
                _update_meta_duration(meta, int(data["duration"]))
        for target in [f, *twins]:
            _atomic_write(target, done[key])
    return {**stats, "backup": saved_to, "files": sum(1 + len(t) for _, _, t in targets)}


def _update_meta_duration(meta: Path, duration: int) -> None:
    try:
        info = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if int(info.get("tm_duration", 0)) < duration:
        info["tm_duration"] = duration
        _atomic_write(meta, json.dumps(info, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
