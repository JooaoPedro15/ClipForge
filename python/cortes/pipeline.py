"""Orquestra a analise do bruto: leitura -> transcricao -> candidatos -> fronteiras -> cortes.json."""

import gc
import itertools
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import ffmpeg_utils
import llm_service
import subtitle_service

from cortes import candidates, extract, judge, segmenter, store, titles, transcribe
from cortes.media import probe_source
from cortes.transcript import transcript_lines

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


def make_client(model: str) -> llm_service.OllamaClient:
    return llm_service.OllamaClient(model=model, base_url=os.environ.get("CLIPFORGE_OLLAMA_URL", llm_service.DEFAULT_BASE_URL))


def run_judge(
    model: str,
    film_segments: list[dict],
    mic_segments: list[dict],
    cands: list[candidates.Candidate],
    start: float,
    end: float,
    progress: ProgressFn,
    note: WarnFn,
) -> llm_service.OllamaClient | None:
    """Notas do juiz nos candidatos. Devolve o cliente pronto (os titulos reaproveitam) ou None se o LLM
    nao estiver disponivel; nesse caso fica so a nota de regra e um aviso explica."""
    client = make_client(model)
    if not client.ensure_server_running():
        note("O Ollama nao respondeu; usei so as regras.")
        return None
    try:
        for message in judge.judge_candidates(
            client,
            film_segments,
            mic_segments,
            cands,
            start,
            end,
            lambda done, total: progress("judging", f"Juiz: parte {done} de {total}...", 62 + 18 * done // total),
        ):
            note(message)
    except llm_service.LLMUnavailableError as error:
        note(f"Juiz indisponivel ({error}); usei so as regras.")
        return None
    return client


def _key(clip: store.Clip) -> tuple[float, float]:
    return (round(clip.start, 2), round(clip.end, 2))


def title_clips(
    analysis: store.Analysis,
    client: Any,
    keep: dict[tuple[float, float], store.Clip],
    on_clip: Callable[[int, int], None] | None = None,
    note: WarnFn | None = None,
) -> None:
    """Titulo e gancho de cada clipe (reaproveita os de `keep` com a mesma fronteira) e recalcula a nota."""
    film, mic = analysis.transcript["film"], analysis.transcript["mic"]
    for clip in analysis.clips:
        previous = keep.get(_key(clip))
        if previous is not None and previous.hook is not None:
            clip.title, clip.hook = previous.title, previous.hook
        else:
            clip.title, clip.hook = f"Clipe {clip.n:02d}", None
            if client is not None:
                try:
                    clip.title, clip.hook = titles.title_clip(client, transcript_lines(film, mic, clip.start, clip.end))
                except titles.TitleResponseError as error:
                    if note:
                        note(f"Titulo do clipe {clip.n:02d} falhou ({error}).")
                except llm_service.LLMUnavailableError as error:
                    if note:
                        note(f"O Ollama caiu nos titulos ({error}); o resto ficou sem titulo.")
                    client = None
        if on_clip:
            on_clip(clip.n, len(analysis.clips))
    reactions = [titles.reaction_fraction(analysis.mic_speech, clip.start, clip.end) for clip in analysis.clips]
    scores = titles.clip_scores([clip.hook for clip in analysis.clips], reactions)
    for clip, score in zip(analysis.clips, scores, strict=True):
        clip.score = score


def resegment(
    analysis: store.Analysis,
    durations: segmenter.Durations,
    client: Any,
    on_clip: Callable[[int, int], None] | None = None,
    note: WarnFn | None = None,
) -> store.Analysis:
    """Refaz as fronteiras com outra faixa de duracao, sem reler o bruto nem chamar o juiz de novo."""
    keep = {_key(clip): clip for clip in analysis.clips}
    start, end = analysis.options["start"], analysis.options["end"]
    bounds = segmenter.choose_boundaries([(c.t, c.score) for c in analysis.candidates], start, end, durations)
    analysis.clips = clips_from(bounds)
    analysis.options.update(asdict(durations))
    title_clips(analysis, client, keep, on_clip, note)
    return analysis


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
    client = None
    if options.judge_model:
        began = time.perf_counter()
        client = run_judge(options.judge_model, film_segments, mic_segments, cands, start, end, progress, note)
        lap("judge", began)
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
    began = time.perf_counter()
    title_clips(
        analysis,
        client,
        {},
        lambda done, total: progress("titling", f"Titulos: clipe {done} de {total}...", 80 + 19 * done // total),
        note,
    )
    lap("titles", began)
    store.save(analysis, store.analysis_path(source_path))
    progress("done", f"{len(analysis.clips)} clipes.", 100)
    return analysis
