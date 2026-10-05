"""Sinhala speech -> timed subtitle cues, using Google Gemini.

We send Gemini a short audio clip plus instructions (the "prompt"), and ask it
to reply in JSON: a list of {start, end, text}. Gemini's reply is checked by a
pydantic schema, so we always get clean data back.
"""

from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from .models import Cue
from .sinhala_script import foreign_chars, has_foreign, purity, transliterate

Log = Callable[[str], None]


@dataclass
class TranscribeOptions:
    api_key: str | None = None      # None: read GEMINI_API_KEY from the environment
    model: str = ""                  # "": pick the best Flash model automatically
    english_mode: str = "english"    # "english": 'layer' | "sinhala": 'ලේයර්'
    max_chars: int = 42              # longest subtitle line
    max_duration: float = 6.0        # longest time one subtitle stays on screen
    chunk_len: float = 60.0          # seconds of audio per Gemini request
    workers: int = 2                 # chunks sent to Gemini at the same time
    polish: bool = True              # second Gemini pass to fix wrong letters
    glossary: list[str] = field(default_factory=list)  # names/words to spell exactly
    engine: str = "gemini"           # "gemini" (online, best Sinhala) | "whisper" (offline)
    language: str = "si"             # spoken language, see languages.py
    whisper_model: str = "small"


class _Sub(BaseModel):
    start: float
    end: float
    text: str


ENGLISH_RULES = {
    "english": "When the speaker uses an English word, write it in English letters with normal "
               "English spelling{example_en}. Never spell English words in {lang} letters.",
    "sinhala": "When the speaker uses an English word, write it in {lang} letters the way it is "
               "pronounced{example_native}.",
}
_EXAMPLES = {   # Sinhala examples help Gemini a lot; other languages get the plain rule
    "si": {"example_en": " (e.g. 'අලුත් layer එකක් හදන්න')", "example_native": " (e.g. 'ලේයර්', 'වීඩියෝ')"},
}

SCRIPT_RULES = {
    "si": """
- Write Sinhala only with Sinhala Unicode letters (U+0D80-U+0DFF). Never use Malayalam, Tamil,
  Devanagari, Telugu or any other script, even when a letter looks or sounds the same.
- Use correct Sinhala spelling with the right vowel signs, hal kirima (්) and joined letters
  (e.g. ශ්‍රී, ක්‍ර, ද්‍ය).""",
}


def language_rules(opts: "TranscribeOptions") -> tuple[str, str, str]:
    """(language description, script rules, English-words rule) for the prompts."""
    from .languages import get
    lang = get(opts.language)
    who = ("Sri Lankan Sinhala (සිංහල)" if lang.code == "si" else
           lang.name if lang.native == lang.name else f"{lang.name} ({lang.native})")
    script = SCRIPT_RULES.get(lang.code) or (
        f"\n- Write {lang.name} in its own script with correct spelling." if lang.script else
        f"\n- Use correct {lang.name} spelling, capital letters and punctuation.")
    english = ""
    if lang.mixes_english:
        ex = _EXAMPLES.get(lang.code, {"example_en": "", "example_native": ""})
        english = "\n- " + ENGLISH_RULES[opts.english_mode].format(lang=lang.name, **ex)
    return who, script, english


TRANSCRIBE_PROMPT = """You are an expert subtitle writer for {who} videos.
Listen to this audio clip ({duration:.1f} seconds long) and write subtitles for everything that is said.

Rules:{script_rules}
- Write exactly what is said, in the language spoken. Do not translate, summarise or fix grammar.{english_rule}
- Each subtitle has at most {max_chars} characters and lasts at most {max_dur:.0f} seconds.
  Break lines at natural pauses.
- start and end are seconds from the beginning of THIS clip (numbers like 12.35),
  between 0 and {duration:.1f}. Subtitles are in time order and never overlap.
- Skip music, noise and silence. If nobody speaks, return an empty list.{glossary}"""

POLISH_PROMPT = """These {n} Sinhala subtitle lines come from speech recognition of a Sri Lankan
speaker who mixes English words into Sinhala. Fix each line:
- Letters from a wrong script (Malayalam, Tamil, Devanagari, Telugu ...) or stray digits inside
  words must become correct Sinhala Unicode (U+0D80-U+0DFF) with correct Sinhala spelling.
- {english_rule}
- Keep every word and the meaning. Do not translate, add or remove content.{glossary}
Return a JSON list with exactly {n} strings, in the same order.

Lines:
{lines}"""

POLISH_ENGLISH = {
    "english": "English words written in Sinhala letters go back to English letters "
               "(ලේයර් -> layer, වීඩියෝ -> video). Real Sinhala words stay Sinhala.",
    "sinhala": "English words written in English letters are written in Sinhala letters as "
               "pronounced (layer -> ලේයර්).",
}

# We never give Gemini tools to call; saying so also stops a noisy SDK warning.
_NO_AFC = {"disable": True}
_SKIP_MODELS = ("image", "tts", "embedding", "live", "robotics", "computer-use", "audio", "veo", "imagen")
_RETRY_ON = ("429", "500", "502", "503", "504", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "timed out", "overloaded")


def make_client(opts: TranscribeOptions):
    from google import genai

    from .config import Settings

    key = (opts.api_key or Settings.load().api_key
           or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    if not key:
        raise RuntimeError("No Gemini API key. Add it in Settings first.")
    from google.genai import types
    # The SDK would quietly retry busy errors for minutes on its own. We retry ourselves (and switch
    # models, which is much faster), so: one attempt per call, and never wait forever.
    return genai.Client(api_key=key, http_options=types.HttpOptions(
        timeout=180_000, retry_options=types.HttpRetryOptions(attempts=1)))


def list_models(client) -> list[str]:
    """Gemini models this API key can use for audio transcription."""
    names = []
    for m in client.models.list():
        name = m.name.removeprefix("models/")
        actions = getattr(m, "supported_actions", None) or []
        if name.startswith("gemini") and "generateContent" in actions \
                and not any(bad in name for bad in _SKIP_MODELS):
            names.append(name)
    return sorted(set(names))


def pick_model(names: list[str]) -> str:
    """Newest stable 'flash' model: fast, cheap and good at Sinhala."""
    def version(name: str) -> float:
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
        return float(m.group(1)) if m else 0.0

    def score(name: str) -> tuple:
        return ("flash" in name, "lite" not in name, "preview" not in name and "exp" not in name,
                version(name), "latest" in name)

    if not names:
        raise RuntimeError("This API key cannot use any Gemini model.")
    return max(names, key=score)


def with_retry(fn, log: Log, tries: int = 3):
    """Call fn(); when Gemini is busy (error 429/503 ...), wait a little and try again."""
    for attempt in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - the SDK raises many error types
            msg = str(e)
            if attempt == tries - 1 or not any(code in msg for code in _RETRY_ON):
                raise
            wait = 3 * 2 ** attempt + random.uniform(0, 2)   # 3, 6, 12 … s; random so threads don't collide
            log(f"  Gemini busy ({_short(msg)}) – retrying in {wait:.0f}s")
            time.sleep(wait)


# --- when a model is overloaded, move on to the next one ----------------------------------

_BUSY = ("503", "UNAVAILABLE", "overloaded", "high demand", "429", "RESOURCE_EXHAUSTED")


def is_busy(e: Exception) -> bool:
    return any(code in str(e) for code in _BUSY)


def is_gone(e: Exception) -> bool:
    """Google retired this model (or this key may not use it): 404 NOT_FOUND."""
    msg = str(e)
    return "404" in msg and ("NOT_FOUND" in msg or "no longer available" in msg or "not found" in msg)


def _short(msg: str) -> str:
    m = re.search(r"'message': '([^']+)'", msg)
    return (m.group(1) if m else msg)[:70]


def friendly_error(e: Exception) -> str:
    """Turn a Gemini error into words a user can act on."""
    msg = str(e)
    if "503" in msg or "UNAVAILABLE" in msg or "high demand" in msg or "overloaded" in msg:
        return ("Gemini is very busy right now (error 503). This is on Google's side – your key is fine.\n"
                "Wait a few minutes and try again, or pick another model in Settings.")
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        return ("You reached the free Gemini limit for now (error 429).\n"
                "Wait a minute and try again, or pick another model in Settings.")
    if is_gone(e):
        return ("Google has retired this Gemini model for your key (error 404).\n"
                "Choose another model in Settings (or 'Automatic').")
    if "API key not valid" in msg or "API_KEY_INVALID" in msg or "PERMISSION_DENIED" in msg:
        return "Google says this API key is not valid. Check it in Settings (Test key)."
    return msg


def fallback_models(names: list[str], first: str, limit: int = 5) -> list[str]:
    """`first`, then other stable models that can stand in for it when it is busy.

    Busy errors are per model, so a slightly older Flash is usually free when the newest is not.
    """
    skip = ("preview", "exp", "transcribe", "omni", "customtools")
    stable = [n for n in names if n != first and not any(s in n for s in skip)]

    def rank(n: str) -> tuple:
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        kind = 0 if "flash" in n and "lite" not in n else 1 if "lite" in n else 2   # flash, lite, pro
        return (kind, -(float(m.group(1)) if m else 0.0))

    return [first] + sorted(stable, key=rank)[:limit - 1]


BUSY_MEMORY = 15 * 60          # seconds a busy model stays at the back of the queue


def _busy_file() -> Path:
    from .config import app_data_dir
    return app_data_dir() / "busy_models.json"


def _load_busy() -> dict[str, float]:
    """{model: unix time until which we treat it as busy}, kept on disk between app runs."""
    try:
        data = json.loads(_busy_file().read_text(encoding="utf-8"))
        return {k: float(v) for k, v in data.items() if float(v) > time.time()}
    except (OSError, ValueError, AttributeError):
        return {}


def _mark_busy(model: str, seconds: float = BUSY_MEMORY) -> None:
    busy = _load_busy()
    busy[model] = time.time() + seconds
    try:
        _busy_file().write_text(json.dumps(busy), encoding="utf-8")
    except OSError:
        pass


class ModelChain:
    """Models to try in order. A model that was busy moves to the back for later requests."""

    def __init__(self, models: list[str]):
        # models that were busy a few minutes ago are probably still busy: try them last
        busy = _load_busy()
        self.models = sorted(models, key=lambda m: m in busy)
        self._lock = threading.Lock()

    @property
    def first(self) -> str:
        return self.models[0]

    def call(self, fn, log: Log):
        """fn(model) with the first model that is not busy."""
        with self._lock:
            order = list(self.models)
        last: Exception | None = None
        for i, model in enumerate(order):
            more = i + 1 < len(order)
            try:
                # with other models left, don't wait at all: switching is faster than waiting
                return with_retry(lambda: fn(model), log, tries=1 if more else 4)
            except Exception as e:  # noqa: BLE001
                gone = is_gone(e)
                if not (gone or is_busy(e)):
                    raise
                last = e
                _mark_busy(model, 7 * 24 * 3600 if gone else BUSY_MEMORY)   # a retired model stays retired
                with self._lock:
                    if self.models[0] == model and len(self.models) > 1:
                        self.models.append(self.models.pop(0))
                if i + 1 < len(order):
                    why = "is no longer available" if gone else "is busy"
                    log(f"  {model} {why} – switching to {order[i + 1]}")
        raise RuntimeError(friendly_error(last)) from last


def model_chain(client, opts) -> ModelChain:
    names = list_models(client)
    first = opts.model or pick_model(names)
    return ModelChain(fallback_models(names, first))


def _glossary_text(words: list[str]) -> str:
    if not words:
        return ""
    return "\n- These names and words appear in the video; spell them exactly like this: " + ", ".join(words)


def transcribe_chunk(client, model: str, audio: Path, opts: TranscribeOptions,
                     offset: float, duration: float, log: Log) -> list[Cue]:
    """Subtitles for one audio clip. Times are moved by `offset` to fit the whole video."""
    from google.genai import types

    who, script_rules, english_rule = language_rules(opts)
    prompt = TRANSCRIBE_PROMPT.format(
        who=who, duration=duration, max_chars=opts.max_chars, max_dur=opts.max_duration,
        script_rules=script_rules, english_rule=english_rule, glossary=_glossary_text(opts.glossary),
    )
    # No retry here: the caller wraps this in ModelChain.call, which retries and switches models.
    reply = client.models.generate_content(
        model=model,
        contents=[prompt, types.Part.from_bytes(data=audio.read_bytes(), mime_type="audio/mp3")],
        config=types.GenerateContentConfig(response_mime_type="application/json",
                                           response_schema=list[_Sub], automatic_function_calling=_NO_AFC),
    )

    subs = reply.parsed if reply.parsed is not None else [_Sub(**d) for d in json.loads(reply.text)]
    cues = []
    for s in subs:
        start = min(max(0.0, s.start), duration)
        end = min(max(start, s.end), duration)
        if s.text.strip() and end > start:
            cues.append(Cue(start + offset, end + offset, s.text.strip()))
    return cues


def split_long(cues: list[Cue], max_chars: int) -> list[Cue]:
    """Break subtitles longer than max_chars at spaces; time is shared by length."""
    out = []
    for c in cues:
        if len(c.text) <= max_chars:
            out.append(c)
            continue
        parts, line = [], ""
        for word in c.text.split():
            if line and len(line) + 1 + len(word) > max_chars:
                parts.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        parts.append(line)
        total = sum(len(p) for p in parts)
        t = c.start
        for p in parts:
            end = t + c.duration * len(p) / total
            out.append(Cue(t, end, p))
            t = end
    return out


def tidy(cues: list[Cue], min_dur: float = 0.6) -> list[Cue]:
    """Sort, drop empty lines, stop overlaps, give very short subtitles a bit more time."""
    cues = sorted((c for c in cues if c.text.strip()), key=lambda c: c.start)
    for i, c in enumerate(cues):
        nxt = cues[i + 1].start if i + 1 < len(cues) else None
        if c.duration < min_dur:
            c.end = c.start + min_dur
        if nxt is not None and c.end > nxt:
            c.end = max(c.start + 0.05, nxt)
    return cues


def polish_texts(client, model, texts: list[str], opts: TranscribeOptions, log: Log) -> list[str]:
    """Text-only Gemini pass: fix wrong-script letters and English-word spelling.

    `model` is a model name or a ModelChain (then busy models are skipped).
    """
    from google.genai import types

    chain = model if isinstance(model, ModelChain) else ModelChain([model])
    out = list(texts)
    batch = 40
    for i in range(0, len(texts), batch):
        part = texts[i:i + batch]
        prompt = POLISH_PROMPT.format(
            n=len(part), english_rule=POLISH_ENGLISH[opts.english_mode],
            glossary=_glossary_text(opts.glossary),
            lines=json.dumps(part, ensure_ascii=False, indent=0),
        )
        reply = chain.call(lambda m: client.models.generate_content(
            model=m, contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json",
                                               response_schema=list[str], automatic_function_calling=_NO_AFC),
        ), log)
        fixed = reply.parsed if reply.parsed is not None else json.loads(reply.text)
        if not isinstance(fixed, list) or len(fixed) != len(part):
            log("  ⚠ Polish returned a different number of lines – kept the originals for that batch.")
            continue
        for j, (old, new) in enumerate(zip(part, fixed)):
            new = str(new).strip()
            # Guard: never accept a "fix" that drops half the line.
            if new and len(new.split()) >= len(old.split()) * 0.6:
                out[i + j] = new
    return out


def fix_script(cues: list[Cue], client, model, opts: TranscribeOptions, log: Log) -> dict:
    """Gemini polish (if on), then letter mapping for anything still wrong. Returns stats.

    Only for Sinhala: speech models mix look-alike Indian letters into Sinhala words.
    """
    texts = [c.text for c in cues]
    if opts.language != "si":
        return {"purity_before": 1.0, "purity_after": 1.0, "foreign_left": 0, "skipped": True}
    before = purity(texts)
    bad = sum(has_foreign(t) for t in texts)
    if opts.polish and client is not None and texts:
        log(f"Polishing {len(texts)} subtitles ({bad} with wrong letters)…")
        try:
            texts = polish_texts(client, model, texts, opts, log)
        except Exception as e:  # noqa: BLE001
            log(f"  ⚠ Polish failed ({str(e)[:80]}); using letter mapping only.")
    texts = [transliterate(t) if has_foreign(t) else t for t in texts]
    for c, t in zip(cues, texts):
        c.text = t
    left = sum(len(foreign_chars(t)) for t in texts)
    return {"purity_before": before, "purity_after": purity(texts), "foreign_left": left}
