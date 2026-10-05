"""Command line.  Examples:

    python -m sinhalasubs transcribe myvideo.mp4 --fm
    python -m sinhalasubs projects
    python -m sinhalasubs tracks "My Project"
    python -m sinhalasubs capcut "My Project"                  (transcribe + write)
    python -m sinhalasubs capcut "My Project" --srt subs.srt   (write an existing .srt)
    python -m sinhalasubs restore "My Project"
    python -m sinhalasubs settings --set-key
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .fm_converter import has_sinhala, unicode_to_fm
from .models import Cue, from_srt, to_srt


def _options(args):
    from .config import Settings

    opts = Settings.load().transcribe_options()
    for name in ("model", "english_mode", "max_chars", "chunk_len", "workers"):
        value = getattr(args, name, None)
        if value not in (None, ""):
            setattr(opts, name, value)
    if getattr(args, "no_polish", False):
        opts.polish = False
    if getattr(args, "glossary", ""):
        opts.glossary = [w.strip() for w in args.glossary.split(",") if w.strip()]
    return opts


def cmd_transcribe(args) -> None:
    from .pipeline import video_to_cues

    video = Path(args.video)
    cues = video_to_cues(video, _options(args))
    out = Path(args.output) if args.output else video.with_suffix(".srt")
    out.write_text(to_srt(cues), encoding="utf-8")
    print(f"Saved {out}")
    if args.fm:
        fm_out = out.with_suffix(".fm.srt")
        fm_out.write_text(to_srt([Cue(c.start, c.end, unicode_to_fm(c.text)) for c in cues]), encoding="utf-8")
        print(f"Saved {fm_out}  (use an FM font like FM-Abhaya in CapCut)")


def _find_project(query: str):
    from .capcut.project import list_projects

    p = Path(query)
    if p.is_dir():
        return p
    projects = list_projects()
    exact = [x for x in projects if query.lower() in (x.name.lower(), x.folder.name.lower())]
    loose = [x for x in projects if query.lower() in x.name.lower()]
    found = exact or loose
    if not found:
        raise RuntimeError(f"No CapCut project called '{query}'. See: python -m sinhalasubs projects")
    if len(found) > 1 and not exact:
        raise RuntimeError("Several projects match: " + ", ".join(x.name for x in found))
    return found[0].folder


def cmd_projects(args) -> None:
    from .capcut.project import default_drafts_roots, list_projects

    print("CapCut drafts folder:", ", ".join(str(r) for r in default_drafts_roots()) or "not found")
    for p in list_projects():
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(p.modified))
        print(f"  {p.name:<32} {p.duration:7.1f}s   {when}")


def _pick(folder: Path, timeline_no: int):
    """Timeline number timeline_no (1, 2 …), or 0 for the one CapCut worked on last."""
    from .capcut.project import Draft, current_timeline, list_projects, list_timelines

    timelines = list_timelines(folder)
    if not timelines:
        raise RuntimeError("This project has no timeline file.")
    if timeline_no == 0:
        info = next((p for p in list_projects(folder.parent) if p.folder == folder), None)
        timeline_no = current_timeline(timelines, info.duration if info else 0) + 1
    if not 1 <= timeline_no <= len(timelines):
        raise RuntimeError(f"Timeline must be 1–{len(timelines)}.")
    return Draft(folder, timelines[timeline_no - 1])


def cmd_tracks(args) -> None:
    from .capcut.project import list_timelines

    folder = _find_project(args.project)
    for n, t in enumerate(list_timelines(folder), start=1):
        print(f"Timeline {n}: {t.name} ({t.duration:.1f}s){'  (main)' if t.is_main else ''}")
        draft = _pick(folder, n)
        for k, tr in enumerate(draft.audio_tracks(), start=1):
            print(f"   track {k}: {tr.label}")


def cmd_capcut(args) -> None:
    from .capcut.project import is_capcut_running
    from .capcut.writer import write_to_draft
    from .pipeline import clips_to_cues
    from .style import SubtitleStyle

    folder = _find_project(args.project)
    draft = _pick(folder, args.timeline)
    if args.srt:
        cues = from_srt(Path(args.srt).read_text(encoding="utf-8"))
        print(f"Loaded {len(cues)} subtitles from {args.srt}")
    else:
        tracks = draft.audio_tracks()
        if not tracks:
            raise RuntimeError("This timeline has no audio or video clips.")
        if not 1 <= args.track <= len(tracks):
            raise RuntimeError(f"Track must be 1–{len(tracks)}. See: tracks \"{args.project}\"")
        track = tracks[args.track - 1]
        print(f"Using {track.label}")
        cues = clips_to_cues(track.clips, _options(args))
        from .config import app_data_dir
        srt = Path(args.save_srt) if args.save_srt else app_data_dir() / "srt" / f"{folder.name}.srt"
        srt.parent.mkdir(parents=True, exist_ok=True)
        srt.write_text(to_srt(cues), encoding="utf-8")
        print(f"Also saved the subtitles as {srt}")

    style = SubtitleStyle(size=args.size, pos_y=args.pos_y, convert_to_fm=not args.unicode)
    if args.font:
        style.font_path = Path(args.font).as_posix()
    if is_capcut_running():
        print("⚠ CapCut is open. Make sure this project is closed (CapCut home screen) before you open it again.")
    result = write_to_draft(folder, draft.timeline, cues, style)
    print(f"Wrote {result['added']} subtitles into {result['files']} file(s)"
          f"{f', replaced {result['removed']} old ones' if result['removed'] else ''}.")
    print(f"Backup: {result['backup']}")


def cmd_restore(args) -> None:
    from .capcut.writer import list_backups, restore_backup

    folder = _find_project(args.project)
    backups = list_backups(folder)
    if not backups:
        raise RuntimeError("No backups for this project.")
    n = restore_backup(folder, backups[0])
    print(f"Restored {n} file(s) from {backups[0].name}")


def cmd_settings(args) -> None:
    import getpass

    from .config import Settings

    s = Settings.load()
    if args.set_key:
        s.api_key = getpass.getpass("Paste your Gemini API key (hidden): ")
        s.save()
        print("Saved (encrypted).")
    key = s.api_key
    print(f"Settings file: {Settings.path()}")
    print(f"API key: {'…' + key[-4:] if key else 'not set'}")
    print(f"Model: {s.model or 'automatic'} | English words: {s.english_mode} | Glossary: {', '.join(s.glossary) or '-'}")


def cmd_models(args) -> None:
    from .transcribe import list_models, make_client, pick_model

    names = list_models(make_client(_options(args)))
    best = pick_model(names)
    for n in names:
        print(("* " if n == best else "  ") + n)
    print("\n* = used by default")


def cmd_fm(args) -> None:
    print(unicode_to_fm(args.text) if has_sinhala(args.text) else args.text)


def _add_ai_args(p) -> None:
    p.add_argument("--model", default="", help="Gemini model (see: models)")
    p.add_argument("--english", dest="english_mode", choices=["english", "sinhala"],
                   help="how to write English words")
    p.add_argument("--max-chars", dest="max_chars", type=int)
    p.add_argument("--chunk", dest="chunk_len", type=float, help="seconds per Gemini request")
    p.add_argument("--workers", type=int, help="requests at the same time")
    p.add_argument("--glossary", default="", help="names to spell exactly, comma separated")
    p.add_argument("--no-polish", action="store_true", help="skip the second Gemini pass")


def main() -> None:
    # Windows terminals default to an old code page that can't print Sinhala.
    # (With pythonw there is no terminal at all, so stdout is None.)
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) == 1:   # no command: open the app window
        from .ui.app import run
        sys.exit(run())

    p = argparse.ArgumentParser(prog="sinhalasubs", description="Sinhala subtitles with Gemini")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("transcribe", help="make an .srt from a video or audio file")
    t.add_argument("video")
    t.add_argument("-o", "--output", help="where to save the .srt (default: next to the video)")
    t.add_argument("--fm", action="store_true", help="also save an FM-font version")
    _add_ai_args(t)
    t.set_defaults(func=cmd_transcribe)

    sub.add_parser("projects", help="list CapCut projects").set_defaults(func=cmd_projects)

    tr = sub.add_parser("tracks", help="list the timelines and tracks of a CapCut project")
    tr.add_argument("project")
    tr.set_defaults(func=cmd_tracks)

    c = sub.add_parser("capcut", help="put Sinhala subtitles into a CapCut project")
    c.add_argument("project", help="project name (see: projects) or folder")
    c.add_argument("--timeline", type=int, default=0, help="1, 2 … (default: the one you edited last)")
    c.add_argument("--track", type=int, default=1, help="track to listen to (see: tracks)")
    c.add_argument("--srt", help="write this .srt instead of transcribing")
    c.add_argument("--save-srt", help="where to also save the new subtitles")
    c.add_argument("--font", help="font file (default: FM-Abhaya)")
    c.add_argument("--size", type=float, default=12.0)
    c.add_argument("--pos-y", dest="pos_y", type=float, default=-0.75, help="-1 bottom … 1 top")
    c.add_argument("--unicode", action="store_true", help="keep Unicode text (no FM conversion)")
    _add_ai_args(c)
    c.set_defaults(func=cmd_capcut)

    r = sub.add_parser("restore", help="undo: restore the last backup of a project")
    r.add_argument("project")
    r.set_defaults(func=cmd_restore)

    s = sub.add_parser("settings", help="show settings, or save your Gemini API key")
    s.add_argument("--set-key", action="store_true")
    s.set_defaults(func=cmd_settings)

    sub.add_parser("models", help="list Gemini models your key can use").set_defaults(func=cmd_models)

    f = sub.add_parser("fm", help="convert Sinhala text to FM font text")
    f.add_argument("text")
    f.set_defaults(func=cmd_fm)

    args = p.parse_args()
    try:
        args.func(args)
    except (RuntimeError, FileNotFoundError) as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
