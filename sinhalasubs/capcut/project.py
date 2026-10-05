"""Read CapCut desktop projects ("drafts"): find them, their timelines and their audio.

A CapCut project is a folder. Its timeline lives in a JSON file (draft_content.json,
or draft_info.json on some versions). Every clip, text and effect is in there.
CapCut counts time in microseconds: 1 second = 1_000_000.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

US = 1_000_000
DRAFT_NAMES = ("draft_content.json", "draft_info.json")


def draft_file(folder: Path) -> Path | None:
    return next((folder / n for n in DRAFT_NAMES if (folder / n).is_file()), None)


def read_draft_json(path: Path) -> dict:
    raw = path.read_bytes().lstrip()
    if not raw.startswith(b"{"):
        raise RuntimeError(f"{path.parent.name}: this project is encrypted by CapCut, so it can't be read.")
    return json.loads(raw.decode("utf-8"))


# --- where CapCut keeps projects --------------------------------------------------

def _capcut_user_data() -> list[Path]:
    home = Path.home()
    if sys.platform == "darwin":
        return [home / "Movies/CapCut/User Data",
                home / "Library/Containers/com.lemon.lvoverseas/Data/Movies/CapCut/User Data"]
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
    return [local / "CapCut/User Data"]


def _custom_drafts_path(user_data: Path) -> Path | None:
    """The folder chosen in CapCut > Settings > Drafts location, if changed."""
    ini = user_data / "Config/globalSetting"
    try:
        for line in ini.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "currentCustomDraftPath" and value.strip():
                return Path(value.strip().replace("\\\\", "\\"))
    except OSError:
        pass
    return None


def default_drafts_roots() -> list[Path]:
    roots = []
    for ud in _capcut_user_data():
        for p in (_custom_drafts_path(ud), ud / "Projects/com.lveditor.draft"):
            if p and p.is_dir() and p not in roots:
                roots.append(p)
    return roots


def is_capcut_running() -> bool:
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe", "/NH"],
                                 capture_output=True, text=True, errors="replace",
                                 creationflags=subprocess.CREATE_NO_WINDOW).stdout
            return "capcut.exe" in out.lower()
        return subprocess.run(["pgrep", "-x", "CapCut"], capture_output=True).returncode == 0
    except OSError:
        return False


# --- projects and timelines ---------------------------------------------------------

@dataclass
class ProjectInfo:
    name: str
    folder: Path
    modified: float
    duration: float          # seconds
    cover: Path | None


def list_projects(root: Path | None = None) -> list[ProjectInfo]:
    roots = [root] if root else default_drafts_roots()
    projects = []
    for r in roots:
        try:
            folders = [f for f in r.iterdir() if f.is_dir() and not f.name.startswith(".")]
        except OSError:
            continue
        for folder in folders:
            main = draft_file(folder)
            if not main:
                continue
            name, duration = folder.name, 0.0
            try:
                meta = json.loads((folder / "draft_meta_info.json").read_text(encoding="utf-8"))
                name = meta.get("draft_name") or name
                duration = int(meta.get("tm_duration", 0)) / US
            except (OSError, ValueError):
                pass
            cover = folder / "draft_cover.jpg"
            projects.append(ProjectInfo(name, folder, main.stat().st_mtime, duration,
                                        cover if cover.is_file() else None))
    return sorted(projects, key=lambda p: p.modified, reverse=True)


@dataclass
class Timeline:
    id: str
    name: str
    files: list[Path]        # every draft file that holds this timeline
    is_main: bool
    duration: float = 0.0    # seconds


def _duration_of(path: Path) -> float:
    try:
        return int(read_draft_json(path).get("duration", 0)) / US
    except (RuntimeError, OSError, ValueError):
        return 0.0


def list_timelines(folder: Path) -> list[Timeline]:
    """Newer CapCut keeps each timeline in Timelines/<id>/; the main one is also copied to the root."""
    root_file = draft_file(folder)
    try:
        info = json.loads((folder / "Timelines/project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [Timeline("", "Timeline", [root_file], True, _duration_of(root_file))] if root_file else []

    main_id = info.get("main_timeline_id", "")
    timelines = []
    for t in info.get("timelines", []):
        if t.get("is_marked_delete"):
            continue
        files = [f for f in [draft_file(folder / "Timelines" / t["id"])] if f]
        if t["id"] == main_id and root_file:
            files.append(root_file)
        if files:
            timelines.append(Timeline(t["id"], t.get("name", "Timeline"), files, t["id"] == main_id,
                                      _duration_of(files[0])))
    return sorted(timelines, key=lambda t: not t.is_main)


# --- clips and tracks ---------------------------------------------------------------------

@dataclass
class AudioClip:
    path: str
    source_start: float      # seconds into the media file
    source_duration: float
    target_start: float      # seconds on the timeline
    target_duration: float
    speed: float
    volume: float


@dataclass
class TrackInfo:
    index: int
    type: str                # "audio" or "video"
    label: str
    clips: list[AudioClip] = field(default_factory=list)


class Draft:
    """One loaded timeline of a project."""

    def __init__(self, folder: Path, timeline: Timeline):
        self.folder = folder
        self.timeline = timeline
        self.path = timeline.files[0]
        self.data = read_draft_json(self.path)

    @property
    def duration(self) -> float:
        return int(self.data.get("duration", 0)) / US

    @property
    def canvas(self) -> tuple[int, int]:
        c = self.data.get("canvas_config", {})
        return int(c.get("width", 1920)), int(c.get("height", 1080))

    def _material(self, mid: str) -> dict | None:
        mats = self.data.get("materials", {})
        return next((m for kind in ("audios", "videos") for m in mats.get(kind, []) if m.get("id") == mid), None)

    def audio_tracks(self) -> list[TrackInfo]:
        """Tracks that can hold speech: audio tracks first, then video tracks."""
        tracks = []
        for i, t in enumerate(self.data.get("tracks", [])):
            if t.get("type") not in ("audio", "video"):
                continue
            clips = []
            for s in t.get("segments", []):
                m = self._material(s.get("material_id", ""))
                if not m or m.get("type") == "photo" or not m.get("path"):
                    continue
                src, tgt = s.get("source_timerange") or {}, s.get("target_timerange") or {}
                clips.append(AudioClip(
                    path=m["path"],
                    source_start=int(src.get("start", 0)) / US,
                    source_duration=int(src.get("duration", tgt.get("duration", 0))) / US,
                    target_start=int(tgt.get("start", 0)) / US,
                    target_duration=int(tgt.get("duration", 0)) / US,
                    speed=float(s.get("speed", 1.0)) or 1.0,
                    volume=float(s.get("volume", 1.0)),
                ))
            if clips:
                n = sum(1 for x in tracks if x.type == t["type"]) + 1
                label = f"{t['type'].capitalize()} track {n} ({len(clips)} clip{'s' if len(clips) > 1 else ''})"
                tracks.append(TrackInfo(i, t["type"], label, clips))
        return sorted(tracks, key=lambda t: t.type != "audio")


def current_timeline(timelines: list[Timeline], project_duration: float) -> int:
    """Index of the timeline CapCut worked on last.

    CapCut's project list shows the length of the timeline you edited last (tm_duration),
    which is often not the "main" one, so pick the timeline with that length.
    """
    if not timelines:
        return -1
    best = min(range(len(timelines)), key=lambda i: abs(timelines[i].duration - project_duration))
    return best if abs(timelines[best].duration - project_duration) < 0.5 else 0


def effect_cache_dir(resource_id: str) -> str:
    """Where CapCut keeps a downloaded effect (animation, font …), as CapCut writes the path.

    If it isn't downloaded yet we still give the folder it will use; CapCut fetches it by id.
    """
    for ud in _capcut_user_data():
        folder = ud / "Cache" / "effect" / resource_id
        if folder.is_dir():
            inner = next((d for d in folder.iterdir() if d.is_dir()), None)
            return (inner or folder).as_posix()
    return (_capcut_user_data()[0] / "Cache" / "effect" / resource_id).as_posix()
