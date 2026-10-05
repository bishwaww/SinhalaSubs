"""App settings, saved in %APPDATA%\\SinhalaSubs\\settings.json.

The Gemini API key is encrypted with Windows DPAPI before it is saved, so the
file is useless on another computer or another Windows account.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def app_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path.home() / ".config"
    folder = base / "SinhalaSubs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# --- encryption of the API key ------------------------------------------------

def _dpapi(data: bytes, encrypt: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in, blob_out = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), BLOB()
    crypt32 = ctypes.windll.crypt32
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError("Windows could not encrypt/decrypt the API key.")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def protect(secret: str) -> str:
    if not secret:
        return ""
    raw = secret.encode("utf-8")
    if sys.platform == "win32":
        return "dpapi:" + base64.b64encode(_dpapi(raw, True)).decode()
    return "plain:" + base64.b64encode(raw).decode()


def unprotect(stored: str) -> str:
    kind, _, data = stored.partition(":")
    try:
        raw = base64.b64decode(data)
        if kind == "dpapi":
            return _dpapi(raw, False).decode("utf-8")
        if kind == "plain":
            return raw.decode("utf-8")
    except (OSError, ValueError):
        pass
    return ""


# --- settings -------------------------------------------------------------------

@dataclass
class Settings:
    api_key_protected: str = ""
    model: str = ""                    # "" = automatic
    english_mode: str = "english"
    max_chars: int = 42
    chunk_len: float = 60.0
    workers: int = 2
    polish: bool = True
    glossary: list[str] = field(default_factory=list)
    drafts_root: str = ""              # "" = find CapCut's drafts folder automatically
    style: dict = field(default_factory=dict)   # last SubtitleStyle used
    engine: str = "gemini"             # gemini | whisper
    language: str = "si"               # spoken language (languages.py)
    window: str = ""                   # the window's last size/place (Qt geometry, base64)
    as_captions: bool = True           # write as CapCut Auto captions (else plain text clips)
    whisper_model: str = "small"

    @property
    def api_key(self) -> str:
        return unprotect(self.api_key_protected) if self.api_key_protected else ""

    @api_key.setter
    def api_key(self, value: str) -> None:
        self.api_key_protected = protect(value.strip())

    @classmethod
    def path(cls) -> Path:
        return app_data_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self) -> None:
        tmp = self.path().with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path())

    def transcribe_options(self):
        from .transcribe import TranscribeOptions
        return TranscribeOptions(
            api_key=self.api_key or None, model=self.model, english_mode=self.english_mode,
            max_chars=self.max_chars, chunk_len=self.chunk_len, workers=self.workers,
            polish=self.polish, glossary=list(self.glossary),
            engine=self.engine, whisper_model=self.whisper_model, language=self.language,
        )


# --- per-project work, so edits survive closing the app ------------------------------------

def _session_path(key: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in " -_." else "_" for ch in key)[:80]
    folder = app_data_dir() / "sessions"
    folder.mkdir(exist_ok=True)
    return folder / f"{safe}.srt"


def save_session(key: str, cues) -> None:
    from .models import to_srt
    _session_path(key).write_text(to_srt(cues), encoding="utf-8")


def load_session(key: str):
    from .models import from_srt
    p = _session_path(key)
    return from_srt(p.read_text(encoding="utf-8")) if p.is_file() else []
