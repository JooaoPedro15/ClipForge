"""Orquestra a analise do bruto: leitura -> transcricao -> candidatos -> fronteiras -> cortes.json."""

import gc
import itertools
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import ffmpeg_utils
import subtitle_service

from cortes import candidates, extract, segmenter, store, transcribe
from cortes.media import probe_source

ProgressFn = Callable[[str, str, int], None]  # (etapa, mensagem, progresso 0-100)
WarnFn = Callable[[str], None]


@dataclass(frozen=True)
class AnalyzeOptions:
    start: float = 0.0
    end: float | None = None
    film_track: int = 0  # indice do ffmpeg 0:a:N (faixa 1 na CLI = 0)
    mic_track: int = 1
    judge_model: str | None = None  # None = so regras
    durations: segmenter.Durations = field(default_factory=segmenter.Durations)
    whisper_model: str = subtitle_service.DEFAULT_MODEL
    device: str = "cuda"
    compute_type: str = "float16"


def clips_from(bounds: list[float]) -> list[store.Clip]:
    return [store.Clip(n=n, start=a, end=b) for n, (a, b) in enumerate(itertools.pairwise(bounds), 1)]


def analyze(source_path: str, options: AnalyzeOptions, progress: ProgressFn, warn: WarnFn) -> store.Analysis:
    media = probe_source(source_path)
    needed = max(options.film_track, options.mic_track) + 1
    if media.audio_streams < needed:
        raise ValueError(
            f"O bruto tem {media.audio_streams} faixa(s) de audio, mas a configuracao usa a faixa {needed}."
        )
    start = max(0.0, options.start)
    end = min(options.end, media.duration_sec) if options.end else media.duration_sec
    if end - start < 1:
        raise ValueError("Trecho vazio: o fim precisa vir depois do inicio (e antes do fim do video).")

    warnings: list[str] = []
    timings: dict[str, float] = {}

    def note(message: str) -> None:
        warnings.append(message)
        warn(message)

    def lap(stage: str, began: float) -> None:
        timings[stage] = round(time.perf_counter() - began, 1)

    span = end - start
    temp_dir = Path(tempfile.mkdtemp(prefix="cortes-", dir=ffmpeg_utils.resolve_short_temp_dir(Path(source_path))))
    try:
        paths = extract.ExtractPaths(temp_dir / "filme.wav", temp_dir / "mic.wav", temp_dir / "planos.txt")
        began = time.perf_counter()
        progress("extracting", "Lendo o bruto (audio e cortes de plano)...", 2)
        for message in extract.run_extract(
            source_path,
            paths,
            options.film_track,
            options.mic_track,
            start,
            end,
            lambda pct: progress("extracting", f"Lendo o bruto... {pct}%", 2 + pct * 23 // 100),
        ):
            note(message)
        shot_cuts = extract.read_scene_times(paths.scenes, offset=start)
        film_silences = extract.detect_silences(paths.film_wav, offset=start, end=end)
        lap("extract", began)

        began = time.perf_counter()
        progress("transcribing", f"Carregando o Whisper ({options.whisper_model})...", 26)
        model = subtitle_service.load_whisper_model(options.whisper_model, options.device, options.compute_type)
        film_words, film_segments = transcribe.transcribe_track(
            model,
            str(paths.film_wav),
            None,
            start,
            lambda t: progress("transcribing", "Transcrevendo o filme...", 30 + int(15 * min(1.0, t / span))),
        )
        mic_words, mic_segments = transcribe.transcribe_track(
            model,
            str(paths.mic_wav),
            "pt",
            start,
            lambda t: progress("transcribing", "Transcrevendo o mic...", 45 + int(15 * min(1.0, t / span))),
        )
        # Libera a VRAM antes do LLM (Whisper e o qwen 14b nao cabem juntos numa placa de 8GB).
        del model
        gc.collect()
        lap("transcribe", began)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    cands = candidates.build_candidates(film_words, mic_words, shot_cuts, film_silences, start, end)
    progress("choosing", f"{len(cands)} pontos de corte possiveis.", 62)
    bounds = segmenter.choose_boundaries([(c.t, c.score) for c in cands], start, end, options.durations)
    analysis = store.Analysis(
        source=asdict(media),
        options={
            "start": start,
            "end": end,
            "film_track": options.film_track,
            "mic_track": options.mic_track,
            "judge_model": options.judge_model,
            "whisper_model": options.whisper_model,
            **asdict(options.durations),
        },
        transcript={"film": film_segments, "mic": mic_segments},
        mic_speech=[list(interval) for interval in candidates.speech_intervals(mic_words)],
        shot_cuts=shot_cuts,
        candidates=cands,
        clips=clips_from(bounds),
        warnings=warnings,
        timings=timings,
    )
    store.save(analysis, store.analysis_path(source_path))
    progress("done", f"{len(analysis.clips)} clipes.", 100)
    return analysis
