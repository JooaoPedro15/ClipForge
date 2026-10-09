"""Whisper nas faixas extraidas, reaproveitando o carregamento e os parametros de Legendas."""

from collections.abc import Callable
from typing import Any

import subtitle_service


def transcribe_track(
    model: Any,
    wav_path: str,
    language: str | None,
    offset: float,
    on_progress: Callable[[float], None] | None = None,
    beam_size: int = subtitle_service.DEFAULT_BEAM_SIZE,
) -> tuple[list[dict], list[dict]]:
    """Devolve (palavras, segmentos) com tempo no bruto (soma `offset`, o inicio do trecho).
    language=None deixa o Whisper detectar: o filme pode estar dublado ou no original."""
    segments, _info = subtitle_service.run_whisper(model, wav_path, language, beam_size, word_timestamps=True)
    words: list[dict] = []
    texts: list[dict] = []
    for index, segment in enumerate(segments):
        for word in subtitle_service.whisper_word_dicts(segment, index):
            text = word["word"].strip()
            if text:
                words.append({"word": text, "start": round(word["start"] + offset, 3), "end": round(word["end"] + offset, 3)})
        text = str(segment.text).strip()
        if text:
            texts.append(
                {"start": round(float(segment.start) + offset, 3), "end": round(float(segment.end) + offset, 3), "text": text}
            )
        if on_progress:
            on_progress(float(segment.end))
    return words, texts
