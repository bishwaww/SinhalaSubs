"""Audio work with FFmpeg: pull audio out of a video, find silences, cut chunks.

FFmpeg is a free command-line program that can read almost any video or audio
file. imageio-ffmpeg ships a copy of it, so the user doesn't have to install it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

SAMPLE_RATE = 16000  # 16 kHz mono is plenty for speech and keeps files small


def ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess:
    """Run ffmpeg with `args`. On Windows, don't flash a black console window."""
    extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    return subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-nostdin", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", **extra,
    )


def media_duration(path: Path) -> float:
    """Length in seconds, read from ffmpeg's 'Duration: 00:01:23.45' line."""
    out = run_ffmpeg(["-i", str(path)]).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    if not m:
        raise RuntimeError(f"FFmpeg could not read {path.name}.")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def has_audio(path: Path) -> bool:
    return bool(re.search(r"Stream #.*Audio:", run_ffmpeg(["-i", str(path)]).stderr))


def extract_audio(video: Path, wav: Path) -> float:
    """Save the sound of `video` as a mono 16 kHz WAV. Returns its length in seconds."""
    if not video.is_file():
        raise FileNotFoundError(f"File not found: {video}")
    if not has_audio(video):
        raise RuntimeError(f"{video.name} has no sound track.")
    r = run_ffmpeg(["-i", str(video), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-y", str(wav)])
    if r.returncode != 0:
        raise RuntimeError("FFmpeg failed:\n" + r.stderr[-800:])
    return media_duration(wav)


def detect_silences(wav: Path, noise_db: int = -35, min_len: float = 0.4) -> list[tuple[float, float]]:
    """Quiet parts of the audio as (start, end) pairs."""
    err = run_ffmpeg(["-i", str(wav), "-af", f"silencedetect=noise={noise_db}dB:d={min_len}",
                      "-f", "null", "-"]).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    if len(ends) < len(starts):  # the file ended while still silent
        ends.append(media_duration(wav))
    return [(max(0.0, s), e) for s, e in zip(starts, ends)]


def plan_chunks(total: float, silences: list[tuple[float, float]],
                chunk_len: float = 60.0) -> list[tuple[float, float]]:
    """Split [0, total] into pieces of about `chunk_len` seconds.

    We cut in the middle of a silence close to each target point, so no word
    is cut in half. Short pieces make Gemini's timestamps more accurate.
    """
    cut_points = [(s + e) / 2 for s, e in silences]
    chunks, start = [], 0.0
    while total - start > chunk_len * 1.3:
        target = start + chunk_len
        near = [c for c in cut_points if start + chunk_len * 0.5 < c < start + chunk_len * 1.3]
        cut = min(near, key=lambda c: abs(c - target)) if near else target
        chunks.append((start, cut))
        start = cut
    chunks.append((start, total))
    return chunks


def export_chunk(wav: Path, start: float, end: float, out: Path) -> Path:
    """Cut [start, end] out of `wav` as a small MP3 to send to Gemini."""
    r = run_ffmpeg(["-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(wav),
                    "-ac", "1", "-b:a", "48k", "-y", str(out)])
    if r.returncode != 0:
        raise RuntimeError("FFmpeg failed:\n" + r.stderr[-800:])
    return out


def _atempo(speed: float) -> list[str]:
    """ffmpeg's atempo filter only takes 0.5–2.0, so bigger changes are chained."""
    parts = []
    while speed > 2.0:
        parts.append("atempo=2.0")
        speed /= 2.0
    while speed < 0.5:
        parts.append("atempo=0.5")
        speed /= 0.5
    if abs(speed - 1.0) > 1e-3:
        parts.append(f"atempo={speed:.5f}")
    return parts


def render_track(clips, out: Path, log=print) -> float:
    """Mix CapCut clips into one mono WAV, each at its place on the timeline.

    `clips` are capcut.project.AudioClip objects. Returns the length in seconds.
    """
    usable, problems = [], []
    for c in clips:
        p = Path(c.path)
        if not p.is_file():
            problems.append(f"• File not found: {p}")
        elif c.volume <= 0:
            problems.append(f"• Clip is muted in CapCut: {p.name}")
        elif not has_audio(p):
            problems.append(f"• No sound in: {p.name}")
        else:
            usable.append(c)
    problems = list(dict.fromkeys(problems))  # same file used many times: report it once
    if not usable:
        raise RuntimeError("This track has no playable audio clips.\n" + "\n".join(problems))
    for msg in problems:
        log(msg)

    total = max(c.target_start + c.target_duration for c in usable)
    inputs, chains = [], []
    for i, c in enumerate(usable):
        inputs += ["-i", c.path]
        steps = [f"atrim=start={c.source_start:.6f}:duration={c.source_duration:.6f}",
                 "asetpts=PTS-STARTPTS", *_atempo(c.speed), f"volume={c.volume:.3f}",
                 f"adelay={int(c.target_start * 1000)}:all=1"]
        chains.append(f"[{i}:a]{','.join(steps)}[a{i}]")
    labels = "".join(f"[a{i}]" for i in range(len(usable)))
    graph = ";".join(chains) + f";{labels}amix=inputs={len(usable)}:normalize=0:duration=longest[out]"

    r = run_ffmpeg([*inputs, "-filter_complex", graph, "-map", "[out]", "-t", f"{total:.3f}",
                    "-ac", "1", "-ar", str(SAMPLE_RATE), "-y", str(out)])
    if r.returncode != 0:
        raise RuntimeError("FFmpeg could not mix the track:\n" + r.stderr[-800:])
    log(f"Rendered {len(usable)} clip(s), {total:.1f}s of audio")
    return total
