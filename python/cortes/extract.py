"""Leitura unica do bruto: as duas faixas de audio em WAV e os cortes de plano da metade do filme.

O HD do bruto e lento (USB); ler o arquivo uma vez so economiza minutos num react de 2h.
"""

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import ffmpeg_utils

SCENE_THRESHOLD = 0.30  # score de mudanca de cena do ffmpeg; calibrado no gabarito
SILENCE_DB = -35
SILENCE_MIN_SEC = 0.4
PTS_TIME_RE = re.compile(r"pts_time:(-?\d+(?:\.\d+)?)")
SILENCE_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
SILENCE_END_RE = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class ExtractPaths:
    film_wav: Path
    mic_wav: Path
    scenes: Path  # gravado com caminho relativo: o ffmpeg roda com cwd na pasta dele


def build_extract_command(
    ffmpeg: str,
    source: str,
    paths: ExtractPaths,
    film_track: int,
    mic_track: int,
    start: float,
    end: float | None,
    scene_threshold: float = SCENE_THRESHOLD,
    hwaccel: bool = True,
) -> list[str]:
    command = [ffmpeg, "-hide_banner", "-y"]
    if hwaccel:
        command += ["-hwaccel", "cuda"]
    if start > 0:
        command += ["-ss", f"{start:.3f}"]
    if end is not None:
        command += ["-to", f"{end:.3f}"]
    command += ["-i", source]
    # Metade esquerda = filme. Reduzido pra 320px: so precisa perceber a troca de plano.
    video_filter = (
        f"crop=iw/2:ih:0:0,scale=320:-2,select='gt(scene,{scene_threshold})',metadata=print:file={paths.scenes.name}"
    )
    command += ["-map", "0:v:0", "-vf", video_filter, "-f", "null", "-"]
    for track, wav in ((film_track, paths.film_wav), (mic_track, paths.mic_wav)):
        command += ["-map", f"0:a:{track}", "-ac", "1", "-ar", "16000", str(wav)]
    return command


def parse_scene_times(text: str, offset: float) -> list[float]:
    return [round(float(match.group(1)) + offset, 3) for match in PTS_TIME_RE.finditer(text)]


def parse_silences(text: str, offset: float, end: float) -> list[tuple[float, float]]:
    ranges = []
    opened = None
    for line in text.splitlines():
        if match := SILENCE_START_RE.search(line):
            opened = max(0.0, float(match.group(1))) + offset
        elif (match := SILENCE_END_RE.search(line)) and opened is not None:
            ranges.append((round(opened, 3), round(float(match.group(1)) + offset, 3)))
            opened = None
    if opened is not None:
        ranges.append((round(opened, 3), end))
    return ranges


def run_extract(
    source: str,
    paths: ExtractPaths,
    film_track: int,
    mic_track: int,
    start: float,
    end: float,
    on_progress: Callable[[int], None],
) -> list[str]:
    """Roda a leitura unica. Devolve avisos (ex.: caiu pra CPU)."""
    ffmpeg = ffmpeg_utils.resolve_ffmpeg_path()
    folder = str(paths.scenes.parent)
    try:
        ffmpeg_utils.run_ffmpeg_with_progress(
            build_extract_command(ffmpeg, source, paths, film_track, mic_track, start, end), end - start, on_progress, cwd=folder
        )
        return []
    except RuntimeError:
        ffmpeg_utils.run_ffmpeg_with_progress(
            build_extract_command(ffmpeg, source, paths, film_track, mic_track, start, end, hwaccel=False),
            end - start,
            on_progress,
            cwd=folder,
        )
        return ["A decodificacao na GPU (CUDA) falhou; li o bruto pela CPU, mais devagar."]


def read_scene_times(path: Path, offset: float) -> list[float]:
    if not path.exists():
        return []
    return parse_scene_times(path.read_text(encoding="utf-8", errors="replace"), offset)


def detect_silences(wav: Path, offset: float, end: float) -> list[tuple[float, float]]:
    result = subprocess.run(
        [
            ffmpeg_utils.resolve_ffmpeg_path(),
            "-hide_banner",
            "-nostats",
            "-i",
            str(wav),
            "-af",
            f"silencedetect=n={SILENCE_DB}dB:d={SILENCE_MIN_SEC}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg silencedetect falhou: {result.stderr.strip()[-500:]}")
    return parse_silences(result.stderr, offset, end)
