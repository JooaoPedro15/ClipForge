"""Dados do bruto lidos com ffprobe."""

import json
import subprocess
from dataclasses import dataclass

import ffmpeg_utils


@dataclass(frozen=True)
class SourceMedia:
    path: str
    duration_sec: float
    fps: float
    width: int
    height: int
    audio_streams: int


def _fraction(text: str) -> float:
    numerator, _, denominator = text.partition("/")
    return float(numerator) / float(denominator or 1)


def parse_probe(path: str, data: dict) -> SourceMedia:
    streams = data.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError(f"{path} nao tem trilha de video.")
    return SourceMedia(
        path=path,
        duration_sec=round(float(data["format"]["duration"]), 3),
        fps=round(_fraction(video.get("r_frame_rate", "0/1")), 3),
        width=int(video["width"]),
        height=int(video["height"]),
        audio_streams=sum(1 for stream in streams if stream.get("codec_type") == "audio"),
    )


def probe_source(path: str) -> SourceMedia:
    result = subprocess.run(
        [
            ffmpeg_utils.resolve_ffprobe_path(),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,width,height,r_frame_rate:format=duration",
            "-of",
            "json",
            path,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe falhou para {path}: {result.stderr.strip()}")
    return parse_probe(path, json.loads(result.stdout))
