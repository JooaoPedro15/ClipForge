import argparse
import contextlib
import hashlib
import importlib.util
import io
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
FEEDBACK_LABEL_PRIORITY = {"viral": 3, "good": 2, "weak": 1}
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


# Limpa e ordena partes vindas de analises externas antes de exportar.
def sanitize_parts(parts: list[dict], total_duration: float) -> list[dict]:
    sanitized: list[dict] = []

    for part in parts:
        try:
            start = max(0.0, float(part.get("inicio", 0.0)))
            end = min(total_duration, float(part.get("fim", total_duration)))
        except (TypeError, ValueError):
            continue

        if end - start < 0.2:
            continue

        sanitized.append(
            {
                "inicio": round(start, 3),
                "fim": round(end, 3),
                "motivo": str(part.get("motivo", "")).strip() or "Parte exportada.",
            }
        )

    sanitized.sort(key=lambda item: item["inicio"])
    return sanitized


# Remove pontos muito proximos, fora dos limites ou redundantes.
def dedupe_cut_points(points: list[float], total_duration: float) -> list[float]:
    normalized: list[float] = []

    for point in sorted(points):
        point = round(max(0.0, min(total_duration, float(point))), 3)
        if point <= EPSILON or point >= total_duration - EPSILON:
            continue
        if normalized and abs(normalized[-1] - point) < 0.25:
            continue
        normalized.append(point)

    return normalized


def extract_preferred_cut_points(parts: list[dict], total_duration: float) -> list[float]:
    return dedupe_cut_points([float(part["fim"]) for part in parts], total_duration)


def collect_segment_cut_points(
    segments: list[dict],
    total_duration: float,
    silence_min_duration_sec: float,
) -> list[float]:
    # Extrai pausas entre segmentos de fala como candidatos naturais de corte.
    points: list[float] = []

    for index, segment in enumerate(segments):
        try:
            segment_end = float(segment["end"])
        except (KeyError, TypeError, ValueError):
            continue

        try:
            next_start = (
                float(segments[index + 1]["start"])
                if index + 1 < len(segments)
                else total_duration
            )
        except (KeyError, TypeError, ValueError):
            next_start = total_duration

        pause_duration = max(0.0, next_start - segment_end)
        if pause_duration >= silence_min_duration_sec:
            points.append(segment_end + pause_duration / 2)

    return dedupe_cut_points(points, total_duration)


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


# Mantem a API antiga de pontos de corte para os fluxos legados que ainda usam partes.
def detect_audio_silence_cut_points(
    module: Any,
    audio_path: str,
    total_duration: float,
    silence_threshold_db: float,
    silence_min_duration_sec: float,
) -> list[float]:
    ranges = detect_audio_silence_ranges(
        module,
        audio_path,
        total_duration,
        silence_threshold_db,
        silence_min_duration_sec,
    )
    return dedupe_cut_points([(item["start"] + item["end"]) / 2 for item in ranges], total_duration)


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


# Escolhe o melhor corte dentro da janela atual priorizando IA, pausas naturais e limites.
def choose_cut_point(
    current_start: float,
    total_duration: float,
    target_duration_sec: float,
    min_duration_sec: float,
    max_duration_sec: float,
    candidate_cut_points: list[float],
    preferred_cut_points: list[float],
) -> tuple[float, str]:
    remaining = total_duration - current_start
    if remaining <= max_duration_sec:
        return total_duration, "Ultima parte."

    min_end = current_start + min_duration_sec
    max_end = current_start + max_duration_sec
    split_friendly_max_end = min(max_end, total_duration - min_duration_sec)

    if split_friendly_max_end < min_end:
        return total_duration, "Ultima parte ajustada para nao sobrar um trecho curto."

    target_end = min(max(current_start + target_duration_sec, min_end), split_friendly_max_end)

    preferred_candidates = [
        point for point in preferred_cut_points if min_end <= point <= split_friendly_max_end
    ]
    if preferred_candidates:
        chosen = min(preferred_candidates, key=lambda point: abs(point - target_end))
        return chosen, "Corte guiado pela IA com validacao local."

    natural_candidates = [
        point for point in candidate_cut_points if min_end <= point <= split_friendly_max_end
    ]
    if natural_candidates:
        chosen = min(natural_candidates, key=lambda point: abs(point - target_end))
        return chosen, "Corte em pausa natural da fala."

    return target_end, "Janela ajustada automaticamente para respeitar minimo e maximo."


# Monta uma sequencia continua de partes cobrindo o video inteiro sem deixar buracos.
def build_contiguous_parts(
    total_duration: float,
    target_duration_sec: float,
    min_duration_sec: float,
    max_duration_sec: float,
    candidate_cut_points: list[float] | None = None,
    preferred_cut_points: list[float] | None = None,
) -> list[dict]:
    if total_duration <= 0.2:
        return []

    candidate_cut_points = candidate_cut_points or []
    preferred_cut_points = preferred_cut_points or []
    parts: list[dict] = []
    cursor = 0.0
    part_number = 1

    while cursor < total_duration - EPSILON:
        end, reason = choose_cut_point(
            cursor,
            total_duration,
            target_duration_sec,
            min_duration_sec,
            max_duration_sec,
            candidate_cut_points,
            preferred_cut_points,
        )

        if end <= cursor + EPSILON:
            end = min(total_duration, cursor + max(min_duration_sec, target_duration_sec))
            reason = "Janela ajustada automaticamente para evitar corte vazio."

        parts.append(
            {
                "parte": part_number,
                "inicio": round(cursor, 3),
                "fim": round(end, 3),
                "motivo": reason,
            }
        )
        cursor = end
        part_number += 1

    return parts


# Modo fixo reaproveita o motor continuo sem candidatos especiais de silencio.
def build_fixed_parts(
    total_duration: float,
    target_duration_sec: float,
    min_duration_sec: float,
    max_duration_sec: float,
) -> list[dict]:
    return build_contiguous_parts(
        total_duration,
        target_duration_sec,
        min_duration_sec,
        max_duration_sec,
    )


# Modo por silencio tenta alinhar cortes nas pausas naturais da fala.
def build_silence_parts(
    segments: list[dict],
    total_duration: float,
    target_duration_sec: float,
    min_duration_sec: float,
    max_duration_sec: float,
    silence_min_duration_sec: float,
    silence_cut_points: list[float],
) -> list[dict]:
    return build_contiguous_parts(
        total_duration,
        target_duration_sec,
        min_duration_sec,
        max_duration_sec,
        candidate_cut_points=silence_cut_points
        or collect_segment_cut_points(segments, total_duration, silence_min_duration_sec),
    )


# Helpers para resumir texto e gerar ids estaveis dos clipes.
def truncate_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def make_clip_id(source_path: str, start_sec: float, end_sec: float) -> str:
    stable_key = f"{Path(source_path).resolve()}|{round(start_sec, 3)}|{round(end_sec, 3)}"
    return hashlib.sha1(stable_key.encode("utf-8")).hexdigest()[:16]


def build_transcript_snippet(segments: list[dict], start_sec: float, end_sec: float, limit: int = 320) -> str:
    collected: list[str] = []

    for segment in segments:
        try:
            segment_start = float(segment.get("start", 0.0))
            segment_end = float(segment.get("end", 0.0))
        except (TypeError, ValueError):
            continue

        if segment_end <= start_sec or segment_start >= end_sec:
            continue

        text = str(segment.get("text", "")).strip()
        if not text:
            continue

        collected.append(text)
        if len(" ".join(collected)) >= limit:
            break

    snippet = truncate_text(" ".join(collected), limit)
    return snippet or "Sem trecho de fala identificado."


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


# Carrega o historico de feedback salvo pelo usuario e indexa por clipId.
def load_feedback_examples(feedback_file: str | None) -> tuple[list[dict], dict[str, dict]]:
    if not feedback_file:
        return [], {}

    feedback_path = Path(feedback_file)
    if not feedback_path.exists():
        return [], {}

    try:
        payload = json.loads(feedback_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], {}

    entries = payload.get("clips", []) if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        return [], {}

    normalized: list[dict] = []
    by_id: dict[str, dict] = {}

    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue

        label = str(raw_entry.get("label", "")).strip().lower()
        clip_id = str(raw_entry.get("clipId", "")).strip()
        if label not in FEEDBACK_LABEL_PRIORITY or not clip_id:
            continue

        try:
            start_sec = float(raw_entry.get("startSec", 0.0))
            end_sec = float(raw_entry.get("endSec", 0.0))
            duration_sec = float(raw_entry.get("durationSec", max(0.0, end_sec - start_sec)))
        except (TypeError, ValueError):
            continue

        entry = {
            "clipId": clip_id,
            "label": label,
            "sourcePath": str(raw_entry.get("sourcePath", "")).strip(),
            "sourceName": str(raw_entry.get("sourceName", "")).strip(),
            "filePath": str(raw_entry.get("filePath", "")).strip(),
            "fileName": str(raw_entry.get("fileName", "")).strip(),
            "startSec": round(start_sec, 3),
            "endSec": round(end_sec, 3),
            "durationSec": round(duration_sec, 3),
            "reason": str(raw_entry.get("reason", "")).strip(),
            "transcriptSnippet": truncate_text(str(raw_entry.get("transcriptSnippet", "")).strip(), 320),
            "updatedAt": int(raw_entry.get("updatedAt", 0) or 0),
        }

        normalized.append(entry)
        by_id[clip_id] = entry

    normalized.sort(
        key=lambda item: (
            FEEDBACK_LABEL_PRIORITY.get(str(item["label"]), 0),
            int(item.get("updatedAt", 0)),
        ),
        reverse=True,
    )
    return normalized, by_id


# Seleciona os exemplos mais relevantes para ajudar a IA a escolher novos cortes.
def select_feedback_examples(feedback_entries: list[dict], target_duration_sec: float) -> list[dict]:
    def sort_key(item: dict) -> tuple[int, float, int]:
        return (
            FEEDBACK_LABEL_PRIORITY.get(str(item["label"]), 0),
            -abs(float(item.get("durationSec", target_duration_sec)) - target_duration_sec),
            int(item.get("updatedAt", 0)),
        )

    positives = sorted(
        [item for item in feedback_entries if item.get("label") in {"viral", "good"}],
        key=sort_key,
        reverse=True,
    )[:4]
    negatives = sorted(
        [item for item in feedback_entries if item.get("label") == "weak"],
        key=sort_key,
        reverse=True,
    )[:2]
    return positives + negatives


def format_feedback_examples(feedback_examples: list[dict]) -> str:
    if not feedback_examples:
        return "Nenhum exemplo salvo."

    lines: list[str] = []
    for example in feedback_examples:
        label = str(example.get("label", "")).upper()
        duration_sec = float(example.get("durationSec", 0.0))
        reason = truncate_text(str(example.get("reason", "")).strip(), 140) or "Sem motivo salvo."
        snippet = truncate_text(str(example.get("transcriptSnippet", "")).strip(), 220) or "Sem trecho salvo."
        lines.append(
            f"- [{label}] {duration_sec:.0f}s | motivo: {reason} | trecho: {snippet}"
        )

    return "\n".join(lines)


def summarize_cut_candidates(points: list[float], limit: int = 28) -> str:
    if not points:
        return "Nenhum candidato natural detectado."

    if len(points) <= limit:
        selected = points
    else:
        step = max(1, math.floor(len(points) / limit))
        selected = [points[index] for index in range(0, len(points), step)][:limit]

    return "\n".join(f"- {point:.1f}s" for point in selected)


def build_timeline_digest(segments: list[dict], total_duration: float, max_windows: int = 12) -> str:
    if not segments:
        return "Sem segmentos de fala disponiveis."

    window_count = max(1, min(max_windows, math.ceil(total_duration / 300)))
    window_size = max(30.0, total_duration / window_count)
    lines: list[str] = []

    for window_index in range(window_count):
        start_sec = window_index * window_size
        end_sec = min(total_duration, start_sec + window_size)
        collected: list[str] = []

        for segment in segments:
            try:
                segment_start = float(segment.get("start", 0.0))
                segment_end = float(segment.get("end", 0.0))
            except (TypeError, ValueError):
                continue

            if segment_end <= start_sec or segment_start >= end_sec:
                continue

            text = str(segment.get("text", "")).strip()
            if not text:
                continue

            collected.append(text)
            if len(" ".join(collected)) >= 220:
                break

        if not collected:
            continue

        lines.append(
            f"- {int(start_sec)}s-{int(end_sec)}s: {truncate_text(' '.join(collected), 220)}"
        )

    return "\n".join(lines) if lines else "Sem resumo temporal disponivel."


# Chama o Gemini e exige JSON puro para transformar a resposta em pontos de corte.
def request_gemini_json(module: Any, prompt: str) -> dict:
    api_key = str(getattr(module, "GEMINI_API_KEY", "") or "").strip()
    models = list(getattr(module, "GEMINI_MODELS", []) or [])
    if not api_key or not models:
        raise RuntimeError("Gemini indisponivel ou sem modelos configurados.")

    summarize_error = getattr(module, "_resumir_erro_gemini", None)
    requests_api = getattr(module, "requests", None)
    if requests_api is None:
        raise RuntimeError("Biblioteca requests indisponivel no Clip-Splitter.")

    last_error = "Gemini nao retornou resposta valida."

    for model_name in models:
        try:
            response = requests_api.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}",
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=(15, 90),
            )
        except Exception as error:
            last_error = f"erro de conexao: {error}"
            break

        if response.status_code != 200:
            if callable(summarize_error):
                last_error = str(summarize_error(response))
            else:
                last_error = f"HTTP {response.status_code}"
            continue

        try:
            response_payload = response.json()
            text = response_payload["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError, ValueError, TypeError):
            last_error = "resposta inesperada do Gemini"
            continue

        text = text.replace("```json", "").replace("```", "").strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            last_error = "Gemini retornou JSON invalido"

    raise RuntimeError(last_error)


# Usa memoria local + contexto temporal para pedir cortes preferenciais a IA.
def analyze_cut_points_with_feedback(
    module: Any,
    segments: list[dict],
    total_duration: float,
    target_duration_sec: float,
    min_duration_sec: float,
    max_duration_sec: float,
    silence_cut_points: list[float],
    feedback_examples: list[dict],
) -> list[float]:
    if not feedback_examples:
        return []

    selected_examples = select_feedback_examples(feedback_examples, target_duration_sec)
    if not selected_examples:
        return []

    desired_points = max(2, min(18, math.ceil(total_duration / max(target_duration_sec, 1.0))))
    timeline_digest = build_timeline_digest(segments, total_duration)
    feedback_digest = format_feedback_examples(selected_examples)
    candidate_points_digest = summarize_cut_candidates(silence_cut_points)

    print(
        f"3/4 Definindo cortes com Gemini + memoria local ({len(selected_examples)} exemplo(s) aproveitado(s))..."
    )

    prompt = f"""Voce e um editor especializado em pre-edicao de videos longos.

TAREFA:
Escolha pontos seguros para encurtar pausas de um video longo. O software local depois preserva a ordem original.

OBJETIVO DE PRE-EDICAO:
- reduzir espera morta
- preservar pausas naturais ou dramaticas
- nao transformar o bruto em shorts automaticamente
- manter a ordem do video inteiro

REGRAS FIXAS:
- prefira pausas naturais da fala
- nao escolha ponto no meio de uma frase importante
- use exemplos positivos como padrao de ritmo a preservar
- use exemplos fracos como padrao de corte seco a evitar

MEMORIA LOCAL DE PERFORMANCE:
{feedback_digest}

CANDIDATOS NATURAIS DE CORTE:
{candidate_points_digest}

MAPA TEMPORAL DO VIDEO:
{timeline_digest}

Retorne APENAS JSON valido, sem markdown, no formato:
{{
  "cut_points": [
    {{
      "time": 245.5,
      "motivo": "explica por que este ponto tem gancho e respeita o ritmo"
    }}
  ]
}}

Escolha no maximo {desired_points} pontos de corte.
"""

    response_payload = request_gemini_json(module, prompt)
    raw_cut_points = response_payload.get("cut_points", []) if isinstance(response_payload, dict) else []
    if not isinstance(raw_cut_points, list):
        raise RuntimeError("Gemini nao retornou cut_points validos.")

    cut_points: list[float] = []
    for cut_point in raw_cut_points:
        if not isinstance(cut_point, dict):
            continue
        try:
            cut_points.append(float(cut_point.get("time")))
        except (TypeError, ValueError):
            continue

    normalized = dedupe_cut_points(cut_points, total_duration)
    if not normalized:
        raise RuntimeError("Gemini nao retornou pontos de corte aproveitaveis.")

    print(f"   ✓ {len(normalized)} pontos de corte definidos com memoria local")
    return normalized


# Construi a lista final de clipes para a UI, incluindo feedback salvo anteriormente.
def build_clip_exports(
    source_path: str,
    output_dir: Path,
    base_name: str,
    parts: list[dict],
    segments: list[dict],
    feedback_by_id: dict[str, dict],
) -> list[dict]:
    clips: list[dict] = []

    for part in parts:
        number = str(part["parte"]).zfill(2)
        start_sec = float(part["inicio"])
        end_sec = float(part["fim"])
        file_name = f"{base_name}_parte{number}.mp4"
        file_path = str(output_dir / file_name)
        clip_id = make_clip_id(source_path, start_sec, end_sec)
        saved_feedback = feedback_by_id.get(clip_id, {})

        clips.append(
            {
                "clipId": clip_id,
                "index": int(part["parte"]),
                "filePath": file_path,
                "fileName": file_name,
                "startSec": round(start_sec, 3),
                "endSec": round(end_sec, 3),
                "durationSec": round(end_sec - start_sec, 3),
                "reason": str(part.get("motivo", "")).strip() or "Parte exportada.",
                "transcriptSnippet": build_transcript_snippet(segments, start_sec, end_sec),
                "feedbackLabel": saved_feedback.get("label"),
                "feedbackUpdatedAt": saved_feedback.get("updatedAt"),
            }
        )

    return clips


# Exporta cada parte usando copy de audio/video para acelerar a geracao dos arquivos.
def export_parts(module: Any, video_path: str, output_dir: Path, base_name: str, parts: list[dict]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    for part in parts:
        number = str(part["parte"]).zfill(2)
        start = float(part["inicio"])
        end = float(part["fim"])
        duration = max(0.05, end - start)
        output_file = output_dir / f"{base_name}_parte{number}.mp4"

        module.executar_ffmpeg_com_progresso(
            [
                module.FFMPEG,
                "-y",
                "-ss",
                str(start),
                "-i",
                video_path,
                "-t",
                str(duration),
                # Preserva o stream de video e todas as faixas de audio do original.
                "-map",
                "0:v?",
                "-map",
                "0:a?",
                "-c:v",
                "copy",
                "-c:a",
                "copy",
                str(output_file),
            ],
            f"Exportando parte {number}",
        )


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


# Captura stdout de funcoes do modulo externo sem perder os logs para analise.
def run_and_capture_stdout(fn: Any, *args: Any, **kwargs: Any) -> tuple[Any, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = fn(*args, **kwargs)
    output = buffer.getvalue()
    return result, output


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
