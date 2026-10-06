import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from events import emit


# Limites para evitar [WinError 206] e MAX_PATH (260) no Windows.
MAX_OUTPUT_STEM_CHARS = 60
WINDOWS_PATH_WARN_CHARS = 240


def safe_short_stem(stem: str, limit: int = MAX_OUTPUT_STEM_CHARS) -> str:
    cleaned = re.sub(r"\s+", "_", stem.strip())
    cleaned = re.sub(r"[^A-Za-z0-9_.\-]", "", cleaned)
    return cleaned[:limit] or "video"


def resolve_short_temp_dir(input_file: Path) -> Path:
    env_dir = os.environ.get("CLIPFORGE_TEMP")
    candidates: list[Path] = []
    if env_dir:
        candidates.append(Path(env_dir))
    if sys.platform == "win32":
        drive = input_file.drive or "C:"
        candidates.append(Path(f"{drive}\\cs_tmp"))
        candidates.append(Path("C:\\cs_tmp"))
    else:
        candidates.append(Path("/tmp/cs_tmp"))
    candidates.append(input_file.parent)

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".cs_write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError:
            continue
    return input_file.parent


def assert_safe_path_lengths(**paths: Path) -> None:
    offenders = {label: str(path) for label, path in paths.items() if len(str(path)) > WINDOWS_PATH_WARN_CHARS}
    if not offenders:
        return
    details = "\n".join(f"  - {label}: {len(value)} chars -> {value}" for label, value in offenders.items())
    raise RuntimeError(
        "Caminho(s) muito longo(s) para Windows (limite seguro ~240 chars). "
        "Use pasta curta como D:\\cs\\ no input/output ou defina CLIPFORGE_TEMP para uma pasta curta.\n"
        f"{details}"
    )


# Resolve onde esta o projeto externo que contem FFmpeg, Whisper e a engine base.
def resolve_clip_splitter_root(explicit_root: str | None) -> Path:
    candidates = [
        explicit_root,
        str(Path.cwd() / "../Clip-Splitter"),
        "D:\\Projetos\\Clip-Splitter",
        "D:\\Projetos\\clip-splitter",
    ]

    for candidate in candidates:
        if not candidate:
            continue
        root = Path(candidate).resolve()
        if (root / "clip_splitter.py").exists():
            return root

    raise FileNotFoundError("Projeto Clip-Splitter nao encontrado.")


# Carrega dinamicamente o modulo principal do projeto Clip-Splitter.
def load_clip_splitter_module(root: Path):
    module_path = root / "clip_splitter.py"
    spec = importlib.util.spec_from_file_location("clipforge_clip_splitter_ext", module_path)
    if not spec or not spec.loader:
        raise RuntimeError("Nao foi possivel carregar clip_splitter.py")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EPSILON = 0.05
SILENCE_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
SILENCE_END_RE = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")
MID_IDEA_TRAILING_WORDS = {
    "que",
    "porque",
    "entao",
    "então",
    "tipo",
    "ai",
    "aí",
    "mas",
    "e",
    "pra",
    "para",
    "quando",
    "se",
    "de",
    "com",
}
PREEDIT_MODE_SETTINGS = {
    "conservative": {
        "dead_silence_keep": 0.30,
        "natural_pause_keep": 0.50,
        "dramatic_pause_keep": 0.90,
        "mid_idea_keep": 0.60,
        "between_ideas_keep": 0.50,
    },
    "balanced": {
        "dead_silence_keep": 0.25,
        "natural_pause_keep": 0.40,
        "dramatic_pause_keep": 0.75,
        "mid_idea_keep": 0.50,
        "between_ideas_keep": 0.35,
    },
    "aggressive": {
        "dead_silence_keep": 0.15,
        "natural_pause_keep": 0.30,
        "dramatic_pause_keep": 0.60,
        "mid_idea_keep": 0.40,
        "between_ideas_keep": 0.25,
    },
}
DEFAULT_PREEDIT_MODE = "balanced"
DEFAULT_ANALYSIS_AUDIO_TRACK = "1"
HARD_SILENCE_DURATION = 1.20
KEEP_PADDING_BEFORE = 0.08
KEEP_PADDING_AFTER = 0.12


# Mantem as duracoes em um intervalo seguro antes de planejar os cortes.
def normalize_duration_settings(
    target_duration_sec: float,
    min_duration_sec: float,
    max_duration_sec: float,
) -> tuple[float, float, float]:
    min_duration = max(5.0, float(min_duration_sec))
    max_duration = max(min_duration + 1.0, float(max_duration_sec))
    target_duration = min(max(float(target_duration_sec), min_duration), max_duration)
    return target_duration, min_duration, max_duration


# Extrai intervalos de pausa entre segmentos transcritos para complementar o silencedetect.
def collect_segment_pause_ranges(
    segments: list[dict],
    total_duration: float,
    silence_min_duration_sec: float,
) -> list[dict]:
    ranges: list[dict] = []

    for index, segment in enumerate(segments):
        try:
            pause_start = float(segment["end"])
            pause_end = float(segments[index + 1]["start"]) if index + 1 < len(segments) else total_duration
        except (KeyError, TypeError, ValueError):
            continue

        pause_start = max(0.0, min(total_duration, pause_start))
        pause_end = max(0.0, min(total_duration, pause_end))
        pause_duration = max(0.0, pause_end - pause_start)
        if pause_duration >= silence_min_duration_sec:
            ranges.append(
                {
                    "start": round(pause_start, 3),
                    "end": round(pause_end, 3),
                    "duration": round(pause_duration, 3),
                    "source": "transcript",
                }
            )

    return ranges


# Usa FFmpeg + silencedetect para encontrar pausas reais no audio original.
def detect_audio_silence_ranges(
    module: Any,
    audio_path: str,
    total_duration: float,
    silence_threshold_db: float,
    silence_min_duration_sec: float,
) -> list[dict]:
    command = [
        module.FFMPEG,
        "-hide_banner",
        "-nostats",
        "-i",
        audio_path,
        "-af",
        f"silencedetect=n={silence_threshold_db}dB:d={silence_min_duration_sec}",
        "-f",
        "null",
        "-",
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception:
        return []

    combined_output = "\n".join(filter(None, [result.stdout, result.stderr]))
    if not combined_output:
        return []

    ranges: list[dict] = []
    current_silence_start: float | None = None

    for line in combined_output.splitlines():
        start_match = SILENCE_START_RE.search(line)
        if start_match:
            current_silence_start = float(start_match.group(1))
            continue

        end_match = SILENCE_END_RE.search(line)
        if not end_match:
            continue

        silence_end = float(end_match.group(1))
        if current_silence_start is not None and silence_end >= current_silence_start:
            pause_start = max(0.0, min(total_duration, current_silence_start))
            pause_end = max(0.0, min(total_duration, silence_end))
            pause_duration = max(0.0, pause_end - pause_start)
            if pause_duration >= silence_min_duration_sec:
                ranges.append(
                    {
                        "start": round(pause_start, 3),
                        "end": round(pause_end, 3),
                        "duration": round(pause_duration, 3),
                        "source": "audio",
                    }
                )
        current_silence_start = None

    if current_silence_start is not None and total_duration > current_silence_start:
        pause_start = max(0.0, min(total_duration, current_silence_start))
        pause_end = total_duration
        pause_duration = max(0.0, pause_end - pause_start)
        if pause_duration >= silence_min_duration_sec:
            ranges.append(
                {
                    "start": round(pause_start, 3),
                    "end": round(pause_end, 3),
                    "duration": round(pause_duration, 3),
                    "source": "audio",
                }
            )

    return merge_pause_ranges(ranges, total_duration)


# Junta pausas sobrepostas vindas de audio e transcricao para evitar decisoes duplicadas.
def merge_pause_ranges(ranges: list[dict], total_duration: float, merge_gap_sec: float = 0.12) -> list[dict]:
    normalized: list[dict] = []

    for raw_range in ranges:
        try:
            start = max(0.0, min(total_duration, float(raw_range.get("start", 0.0))))
            end = max(0.0, min(total_duration, float(raw_range.get("end", total_duration))))
        except (TypeError, ValueError):
            continue

        if end - start < 0.1:
            continue

        normalized.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(end - start, 3),
                "source": str(raw_range.get("source", "unknown")),
            }
        )

    merged: list[dict] = []
    for item in sorted(normalized, key=lambda value: value["start"]):
        if not merged or item["start"] > merged[-1]["end"] + merge_gap_sec:
            merged.append(item)
            continue

        merged[-1]["end"] = round(max(merged[-1]["end"], item["end"]), 3)
        merged[-1]["duration"] = round(merged[-1]["end"] - merged[-1]["start"], 3)
        sources = set(str(merged[-1].get("source", "")).split("+"))
        sources.add(str(item.get("source", "unknown")))
        merged[-1]["source"] = "+".join(sorted(source for source in sources if source))

    return merged


# Normaliza uma palavra de contexto para comparar conectores fracos sem alterar a transcricao.
def normalize_context_word(word: str) -> str:
    return re.sub(r"[^\w\s]", "", word).strip().lower()


def last_context_word(text: str) -> str:
    words = [normalize_context_word(word) for word in text.split()]
    words = [word for word in words if word]
    return words[-1] if words else ""


# Encontra a fala imediatamente antes/depois de uma pausa para decidir se ela carrega sentido.
def find_pause_context(segments: list[dict], pause_start: float, pause_end: float) -> dict:
    before: dict | None = None
    after: dict | None = None

    for segment in segments:
        try:
            segment_start = float(segment.get("start", 0.0))
            segment_end = float(segment.get("end", 0.0))
        except (TypeError, ValueError):
            continue

        if segment_end <= pause_start + 0.2 and (before is None or segment_end > float(before.get("end", 0.0))):
            before = segment

        if segment_start >= pause_end - 0.2 and (after is None or segment_start < float(after.get("start", 10**9))):
            after = segment

    before_text = str(before.get("text", "")).strip() if before else ""
    after_text = str(after.get("text", "")).strip() if after else ""

    return {
        "before_text": before_text,
        "after_text": after_text,
        "before_word": last_context_word(before_text),
        "after_word": normalize_context_word(after_text.split()[0]) if after_text.split() else "",
    }


# Classifica a pausa em tipos editoriais para evitar transformar todo silencio em corte seco.
def classify_pause(pause: dict, segments: list[dict]) -> tuple[str, str]:
    start = float(pause["start"])
    end = float(pause["end"])
    duration = float(pause.get("duration", end - start))
    context = find_pause_context(segments, start, end)
    before_word = context["before_word"]
    before_text = context["before_text"]
    after_text = context["after_text"]

    if before_word in MID_IDEA_TRAILING_WORDS:
        return "mid_idea_pause", f"pause follows connector '{before_word}' and likely completes the same idea"

    if duration < HARD_SILENCE_DURATION:
        return "breathing_pause", "short natural pause between words or phrases"

    if duration <= 2.2 and before_text and after_text:
        return "dramatic_pause", "moderate pause with speech on both sides, useful for timing or reaction"

    if before_text and after_text and duration <= 2.8:
        return "between_ideas", "pause between nearby spoken ideas"

    return "dead_silence", "long silence with no useful context"


# Decide se cada pausa deve ser mantida, comprimida ou quase removida conforme a intensidade escolhida.
def build_pause_edit_decisions(pauses: list[dict], segments: list[dict], mode: str = DEFAULT_PREEDIT_MODE) -> list[dict]:
    settings = PREEDIT_MODE_SETTINGS.get(mode, PREEDIT_MODE_SETTINGS[DEFAULT_PREEDIT_MODE])
    keep_by_type = {
        "dead_silence": settings["dead_silence_keep"],
        "breathing_pause": settings["natural_pause_keep"],
        "dramatic_pause": settings["dramatic_pause_keep"],
        "mid_idea_pause": settings["mid_idea_keep"],
        "between_ideas": settings["between_ideas_keep"],
    }
    decisions: list[dict] = []

    for pause in sorted(pauses, key=lambda item: float(item.get("start", 0.0))):
        try:
            start = round(float(pause["start"]), 3)
            end = round(float(pause["end"]), 3)
        except (KeyError, TypeError, ValueError):
            continue

        duration = round(max(0.0, end - start), 3)
        if duration < 0.1:
            continue

        pause_type, reason = classify_pause({"start": start, "end": end, "duration": duration}, segments)
        keep_duration = min(duration, float(keep_by_type[pause_type]))
        if mode == "aggressive" and pause_type == "dead_silence" and duration >= 4.0:
            action = "remove"
            keep_duration = 0.0
        else:
            action = "keep" if duration <= keep_duration + EPSILON else "compress"

        decisions.append(
            {
                "start": start,
                "end": end,
                "duration": duration,
                "type": pause_type,
                "action": action,
                "keep_duration": round(keep_duration, 3),
                "reason": reason,
            }
        )

    return decisions


# Transforma decisoes de pausa em trechos preservados, mantendo a ordem original do video inteiro.
def build_preedit_keep_ranges(
    total_duration: float,
    decisions: list[dict],
    keep_padding_before: float = KEEP_PADDING_BEFORE,
    keep_padding_after: float = KEEP_PADDING_AFTER,
) -> list[dict]:
    ranges: list[dict] = []
    cursor = 0.0

    for decision in sorted(decisions, key=lambda item: float(item.get("start", 0.0))):
        if decision.get("action") == "keep":
            continue

        try:
            pause_start = max(0.0, min(total_duration, float(decision["start"])))
            pause_end = max(0.0, min(total_duration, float(decision["end"])))
            keep_duration = max(0.0, float(decision.get("keep_duration", 0.0)))
        except (KeyError, TypeError, ValueError):
            continue

        pause_duration = pause_end - pause_start
        if pause_duration <= 0.1:
            continue

        total_keep = min(pause_duration, max(keep_duration, min(pause_duration, keep_padding_before + keep_padding_after)))
        keep_before = min(total_keep, max(keep_padding_before, total_keep * 0.45))
        keep_after = min(pause_duration - keep_before, max(keep_padding_after, total_keep - keep_before))
        removed_start = round(pause_start + keep_before, 3)
        removed_end = round(pause_end - keep_after, 3)

        if removed_end <= removed_start + EPSILON:
            continue

        if removed_start > cursor + EPSILON:
            ranges.append({"start": round(cursor, 3), "end": removed_start})

        cursor = max(cursor, removed_end)

    if cursor < total_duration - EPSILON:
        ranges.append({"start": round(cursor, 3), "end": round(total_duration, 3)})

    return [item for item in ranges if item["end"] - item["start"] > 0.05]


# Monta o item unico que representa o video limpo entregue pela pre-edicao.
def build_preedit_export_payload(
    source_path: str,
    output_file: str,
    source_duration_sec: float,
    edited_duration_sec: float,
    decisions_count: int,
) -> dict:
    output_path = Path(output_file)
    clip_id = hashlib.sha1(f"{Path(source_path).resolve()}|preedit|{output_path}".encode("utf-8")).hexdigest()[:16]
    removed_sec = max(0.0, float(source_duration_sec) - float(edited_duration_sec))

    return {
        "clipId": clip_id,
        "index": 1,
        "filePath": str(output_path),
        "fileName": output_path.name,
        "startSec": 0.0,
        "endSec": round(float(edited_duration_sec), 3),
        "durationSec": round(float(edited_duration_sec), 3),
        "reason": f"Pre-edicao unica com {decisions_count} pausa(s) analisada(s); {removed_sec:.1f}s removidos.",
        "transcriptSnippet": "Video limpo em ordem original para revisao manual.",
        "feedbackLabel": None,
        "feedbackUpdatedAt": None,
    }


# Lê os streams de audio do arquivo original para escolher análise e preservar faixas na exportação.
def probe_audio_streams(module: Any, video_path: str) -> list[dict]:
    command = [
        module.FFPROBE,
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index,codec_name:stream_tags=title,handler_name",
        "-of",
        "json",
        video_path,
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        payload = json.loads(result.stdout or "{}")
    except Exception:
        return []

    streams: list[dict] = []
    for audio_index, stream in enumerate(payload.get("streams", []) if isinstance(payload, dict) else []):
        if not isinstance(stream, dict):
            continue

        tags = stream.get("tags", {}) if isinstance(stream.get("tags"), dict) else {}
        streams.append(
            {
                "index": int(stream.get("index", audio_index)),
                "audio_index": audio_index,
                "codec_name": str(stream.get("codec_name", "")),
                "title": str(tags.get("title") or tags.get("handler_name") or ""),
            }
        )

    return streams


# Resolve a faixa de audio usada para detectar silencio; por padrao usa 0:a:1 como faixa de voz.
def resolve_analysis_audio_track(selection: str | int | None, audio_streams: list[dict]) -> dict:
    if not audio_streams:
        raise RuntimeError("Nenhuma faixa de audio encontrada para analise.")

    def with_reason(stream: dict, reason: str) -> dict:
        return {
            **stream,
            "stream_index": int(stream.get("index", stream.get("audio_index", 0))),
            "reason": reason,
        }

    raw_selection = str(selection if selection is not None else DEFAULT_ANALYSIS_AUDIO_TRACK).strip()
    normalized_selection = (raw_selection or DEFAULT_ANALYSIS_AUDIO_TRACK).lower()
    is_default_voice_track = normalized_selection == DEFAULT_ANALYSIS_AUDIO_TRACK

    if normalized_selection.isdigit():
        requested_index = int(normalized_selection)
        for stream in audio_streams:
            if int(stream.get("audio_index", -1)) == requested_index:
                if is_default_voice_track:
                    return with_reason(stream, f"using default voice audio track {requested_index} (FFmpeg 0:a:{requested_index})")
                return with_reason(stream, f"using configured audio track {requested_index}")

        fallback_reason = (
            f"fallback to first audio track because default voice track {requested_index} "
            f"(FFmpeg 0:a:{requested_index}) was not found"
            if is_default_voice_track
            else f"fallback to first audio track because configured track {requested_index} was not found"
        )
        return with_reason(
            audio_streams[0],
            fallback_reason,
        )

    name_tokens = ["mic", "microphone", "microfone", "voz", "voice"]
    if normalized_selection in {"mic", "microphone", "microfone", "voz", "voice"}:
        for stream in audio_streams:
            title = str(stream.get("title", "")).lower()
            if any(token in title for token in name_tokens):
                return with_reason(stream, f"using mic-like audio track '{stream.get('title', '')}'")

        return with_reason(audio_streams[0], "fallback to first audio track because mic track was not identified")

    for stream in audio_streams:
        title = str(stream.get("title", "")).lower()
        if normalized_selection and normalized_selection in title:
            return with_reason(stream, f"using audio track matching '{normalized_selection}'")

    return with_reason(
        audio_streams[0],
        f"fallback to first audio track because '{normalized_selection}' was not identified",
    )


# Extrai somente a faixa escolhida para análise, sem alterar as faixas que serão exportadas depois.
def extract_analysis_audio_track(module: Any, video_path: str, output_path: str, audio_track_index: int) -> str:
    audio_path = str(Path(output_path) / "audio_temp.wav")
    print(f"1/4 Extraindo audio de analise da faixa {audio_track_index}...", flush=True)
    module.executar_ffmpeg_com_progresso(
        [
            module.FFMPEG,
            "-y",
            "-i",
            video_path,
            "-map",
            f"0:a:{audio_track_index}",
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            audio_path,
        ],
        "Extracao de audio para analise",
    )
    print("   Audio de analise extraido", flush=True)
    return audio_path


# Cria o comando FFmpeg que concatena os trechos preservados em um unico video limpo.
# Quando filter_script_path e informado, o filtergraph vai para arquivo e usamos
# -filter_complex_script, evitando estourar o limite de linha de comando do Windows (~32K).
def build_preedit_ffmpeg_command(
    module: Any,
    video_path: str,
    output_file: Path,
    keep_ranges: list[dict],
    audio_stream_count: int = 1,
    filter_script_path: Path | None = None,
) -> list[str]:
    filters: list[str] = []
    video_labels: list[str] = []
    audio_output_labels: list[str] = []

    for index, keep_range in enumerate(keep_ranges):
        start = float(keep_range["start"])
        end = float(keep_range["end"])
        filters.append(f"[0:v:0]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{index}]")
        video_labels.append(f"[v{index}]")

        for audio_index in range(audio_stream_count):
            filters.append(
                f"[0:a:{audio_index}]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{audio_index}_{index}]"
            )

    filters.append(f"{''.join(video_labels)}concat=n={len(keep_ranges)}:v=1:a=0[outv]")

    for audio_index in range(audio_stream_count):
        labels = "".join(f"[a{audio_index}_{index}]" for index in range(len(keep_ranges)))
        output_label = f"[outa{audio_index}]"
        filters.append(f"{labels}concat=n={len(keep_ranges)}:v=0:a=1{output_label}")
        audio_output_labels.append(output_label)

    map_args = ["-map", "[outv]"]
    for output_label in audio_output_labels:
        map_args.extend(["-map", output_label])

    graph = ";".join(filters)
    if filter_script_path is not None:
        filter_script_path.parent.mkdir(parents=True, exist_ok=True)
        filter_script_path.write_text(graph, encoding="utf-8")
        filter_args = ["-filter_complex_script", str(filter_script_path)]
    else:
        filter_args = ["-filter_complex", graph]

    return [
        module.FFMPEG,
        "-y",
        "-i",
        video_path,
        *filter_args,
        *map_args,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_file),
    ]


# Exporta a pre-edicao como um arquivo unico, preservando a ordem original dos trechos mantidos.
def export_preedited_video(
    module: Any,
    video_path: str,
    output_file: Path,
    keep_ranges: list[dict],
    audio_stream_count: int,
    filter_script_path: Path | None = None,
) -> None:
    if not keep_ranges:
        raise RuntimeError("Nenhum trecho valido para exportar a pre-edicao.")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    module.executar_ffmpeg_com_progresso(
        build_preedit_ffmpeg_command(
            module,
            video_path,
            output_file,
            keep_ranges,
            audio_stream_count=audio_stream_count,
            filter_script_path=filter_script_path,
        ),
        "Exportando pre-edicao",
    )


# Salva um JSON opcional com as decisoes editoriais tomadas para cada pausa detectada.
def write_debug_decisions(output_file: Path, decisions: list[dict]) -> str:
    debug_path = output_file.with_suffix(".debug.json")
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(debug_path)


# Ajusta o runtime do Whisper para CPU ou GPU antes da transcricao.
def configure_whisper_runtime(module: Any, force_cpu: bool) -> tuple[str, str]:
    device = "cpu" if force_cpu else str(getattr(module, "WHISPER_DEVICE", "cuda"))
    compute_type = "int8" if force_cpu else str(getattr(module, "WHISPER_COMPUTE", "float16"))
    module.WHISPER_DEVICE = device
    module.WHISPER_COMPUTE = compute_type
    return device, compute_type


# Interface CLI usada pelo processo principal do Electron para iniciar o runner.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ClipForge Pre-Editor service")
    parser.add_argument("input", help="Caminho do video")
    parser.add_argument("-o", "--output", default=None)
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--mode", choices=["fixed", "silence"], default="silence")
    parser.add_argument("--preedit-mode", choices=["conservative", "balanced", "aggressive"], default=DEFAULT_PREEDIT_MODE)
    parser.add_argument("--target-duration", type=float, default=35.0)
    parser.add_argument("--min-duration", type=float, default=20.0)
    parser.add_argument("--max-duration", type=float, default=50.0)
    parser.add_argument("--silence-threshold-db", type=float, default=-35.0)
    parser.add_argument("--silence-min-duration", type=float, default=0.45)
    parser.add_argument("--analysis-audio-track", "--voice-track-index", default=DEFAULT_ANALYSIS_AUDIO_TRACK)
    parser.add_argument("--feedback-file", default=None)
    parser.add_argument("--write-debug-json", action="store_true")
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--no-ai", action="store_true")
    return parser.parse_args()


# Orquestra todo o pipeline: probe, audio, transcricao, planejamento e exportacao.
def main() -> int:
    args = parse_args()
    started_at = time.time()
    input_file = Path(args.input)

    if not input_file.exists():
        emit("error", "error", "input", "Arquivo nao encontrado.", error=f"Arquivo nao encontrado: {args.input}")
        return 1

    try:
        project_root = resolve_clip_splitter_root(args.project_root)
        emit("status", "preparing", "bootstrap", "Carregando engine do Clip-Splitter...", progress=5)
        module = load_clip_splitter_module(project_root)
        whisper_device, whisper_compute = configure_whisper_runtime(module, args.cpu)
    except Exception as error:
        emit("error", "error", "bootstrap", "Falha ao carregar engine do Clip-Splitter.", error=str(error))
        return 1

    safe_stem = safe_short_stem(input_file.stem)
    output_dir = Path(args.output) if args.output else input_file.parent / f"{safe_stem}_preedit"
    temp_dir = resolve_short_temp_dir(input_file)
    filter_script_path = temp_dir / "preedit_filters.txt"
    temp_audio_path = temp_dir / "audio_temp.wav"

    print(
        f"[debug] input_path ({len(str(input_file))} chars): {input_file}\n"
        f"[debug] output_dir ({len(str(output_dir))} chars): {output_dir}\n"
        f"[debug] temp_dir ({len(str(temp_dir))} chars): {temp_dir}\n"
        f"[debug] filter_script_path: {filter_script_path}\n"
        f"[debug] temp_audio_path: {temp_audio_path}",
        flush=True,
    )

    try:
        assert_safe_path_lengths(
            input_path=input_file,
            output_dir=output_dir,
            temp_dir=temp_dir,
            temp_audio_path=temp_audio_path,
            filter_script_path=filter_script_path,
        )
    except RuntimeError as path_error:
        emit("error", "error", "paths", str(path_error), error=str(path_error))
        return 1

    try:
        target_duration_sec, min_duration_sec, max_duration_sec = normalize_duration_settings(
            args.target_duration,
            args.min_duration,
            args.max_duration,
        )
        silence_min_duration_sec = max(0.1, float(args.silence_min_duration))
        silence_threshold_db = float(args.silence_threshold_db)

        module.MIN_PART_DURATION = max(5, int(math.floor(min_duration_sec)))
        module.MAX_PART_DURATION = max(module.MIN_PART_DURATION + 1, int(math.ceil(max_duration_sec)))
        ai_requested = False
        ai_used = False
        fallback_reason: str | None = "Pre-edicao usa heuristicas locais de pausa; nao escolhe shorts automaticamente."

        emit(
            "status",
            "preparing",
            "probing",
            "Lendo duracao do video...",
            progress=10,
            outputDir=str(output_dir),
            aiRequested=ai_requested,
            aiUsed=ai_used,
            fallbackReason=fallback_reason,
            transcriptionDevice=whisper_device,
            transcriptionComputeType=whisper_compute,
        )
        total_duration = float(module.get_duracao(str(input_file)))
        audio_streams = probe_audio_streams(module, str(input_file))
        if not audio_streams:
            raise RuntimeError("Nenhuma faixa de audio encontrada no video de entrada.")

        analysis_audio = resolve_analysis_audio_track(args.analysis_audio_track, audio_streams)
        analysis_audio_index = int(analysis_audio["audio_index"])
        audio_stream_count = len(audio_streams)
        print(
            f"Audio: {audio_stream_count} faixa(s) detectada(s); analisando faixa {analysis_audio_index} "
            f"(stream {analysis_audio['stream_index']}). {analysis_audio['reason']}",
            flush=True,
        )

        emit(
            "status",
            "preparing",
            "extracting-audio",
            f"Extraindo audio de analise da faixa {analysis_audio_index}/{audio_stream_count - 1}...",
            progress=18,
            outputDir=str(output_dir),
            sourceDurationSec=total_duration,
            aiRequested=ai_requested,
            aiUsed=ai_used,
            fallbackReason=fallback_reason,
            transcriptionDevice=whisper_device,
            transcriptionComputeType=whisper_compute,
        )
        audio_path = extract_analysis_audio_track(module, str(input_file), str(temp_dir), analysis_audio_index)

        emit(
            "status",
            "processing",
            "transcribing",
            "Transcrevendo audio com Whisper em CPU..." if whisper_device == "cpu" else "Transcrevendo audio com Whisper...",
            progress=34,
            outputDir=str(output_dir),
            sourceDurationSec=total_duration,
            aiRequested=ai_requested,
            aiUsed=ai_used,
            fallbackReason=fallback_reason,
            transcriptionDevice=whisper_device,
            transcriptionComputeType=whisper_compute,
        )
        segments = module.transcrever(audio_path)
        audio_pause_ranges = detect_audio_silence_ranges(
            module,
            audio_path,
            total_duration,
            silence_threshold_db,
            silence_min_duration_sec,
        )
        transcript_pause_ranges = collect_segment_pause_ranges(segments, total_duration, silence_min_duration_sec)
        pause_ranges = merge_pause_ranges(audio_pause_ranges + transcript_pause_ranges, total_duration)

        if args.mode == "fixed":
            # Modo fixo agora preserva o bruto em arquivo unico, sem gerar partes curtas.
            pause_decisions: list[dict] = []
            keep_ranges = [{"start": 0.0, "end": round(total_duration, 3)}]
        else:
            # Modo silencio virou pre-edicao: cada pausa vira uma decisao de manter, comprimir ou reduzir.
            pause_decisions = build_pause_edit_decisions(pause_ranges, segments, mode=args.preedit_mode)
            keep_ranges = build_preedit_keep_ranges(total_duration, pause_decisions)

        edited_duration_sec = round(sum(item["end"] - item["start"] for item in keep_ranges), 3)
        output_file = output_dir / f"{safe_stem}_preedit.mp4"
        debug_path = write_debug_decisions(output_file, pause_decisions) if args.write_debug_json else None
        clip_exports = [
            build_preedit_export_payload(
                str(input_file),
                str(output_file),
                total_duration,
                edited_duration_sec,
                len(pause_decisions),
            )
        ]

        emit(
            "status",
            "processing",
            "planning",
            f"{len(pause_decisions)} pausas analisadas para pre-edicao.",
            progress=56,
            outputDir=str(output_dir),
            debugPath=debug_path,
            sourceDurationSec=total_duration,
            aiRequested=ai_requested,
            aiUsed=ai_used,
            fallbackReason=fallback_reason,
        )

        if not keep_ranges:
            raise RuntimeError("Nenhum trecho valido foi gerado para a pre-edicao.")

        emit(
            "status",
            "processing",
            "planning-done",
            "Video unico planejado para pre-edicao.",
            progress=70,
            outputDir=str(output_dir),
            debugPath=debug_path,
            sourceDurationSec=total_duration,
            totalClips=1,
            clipsCreated=0,
            aiRequested=ai_requested,
            aiUsed=ai_used,
            fallbackReason=fallback_reason,
            transcriptionDevice=whisper_device,
            transcriptionComputeType=whisper_compute,
        )

        emit(
            "status",
            "processing",
            "exporting",
            "Exportando video limpo unico...",
            progress=82,
            outputDir=str(output_dir),
            debugPath=debug_path,
            sourceDurationSec=total_duration,
            totalClips=1,
            clipsCreated=0,
            aiRequested=ai_requested,
            aiUsed=ai_used,
            fallbackReason=fallback_reason,
            transcriptionDevice=whisper_device,
            transcriptionComputeType=whisper_compute,
        )

        print(
            f"[debug] keep_ranges={len(keep_ranges)} audio_streams={audio_stream_count} "
            f"using_filter_script=true script_path={filter_script_path}",
            flush=True,
        )
        export_preedited_video(
            module,
            str(input_file),
            output_file,
            keep_ranges,
            audio_stream_count,
            filter_script_path=filter_script_path,
        )
        preserved_audio_streams = probe_audio_streams(module, str(output_file))
        preserved_audio_count = len(preserved_audio_streams)
        if preserved_audio_count != audio_stream_count:
            raise RuntimeError(
                f"Possivel downmix acidental: entrada tinha {audio_stream_count} faixa(s) de audio, "
                f"saida preservou {preserved_audio_count}."
            )

        print(
            f"Audio: {audio_stream_count} faixa(s) na entrada; {preserved_audio_count} preservada(s) na saida.",
            flush=True,
        )

        for cleanup_path in (Path(audio_path), filter_script_path):
            try:
                cleanup_path.unlink(missing_ok=True)
            except Exception:
                pass

        emit(
            "done",
            "completed",
            "done",
            f"Pre-edicao exportada com sucesso; {preserved_audio_count} faixa(s) de audio preservada(s).",
            progress=100,
            outputDir=str(output_dir),
            debugPath=debug_path,
            sourceDurationSec=total_duration,
            totalClips=1,
            clipsCreated=1,
            durationSec=round(time.time() - started_at, 1),
            aiRequested=ai_requested,
            aiUsed=ai_used,
            fallbackReason=fallback_reason,
            clips=clip_exports,
            transcriptionDevice=whisper_device,
            transcriptionComputeType=whisper_compute,
        )
        return 0
    except Exception as error:
        emit(
            "error",
            "error",
            "processing",
            "Falha ao processar o Pre-Editor.",
            error=str(error),
            outputDir=str(output_dir),
            aiRequested=False,
            transcriptionDevice=whisper_device,
            transcriptionComputeType=whisper_compute,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
