"""Palavras do Whisper com cache em json ao lado da midia, e o modelo carregado uma vez so."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import subtitle_service
from events import emit

# Modelos guardados no modulo (nao na funcao): destruir o modelo do ctranslate2 na GPU as vezes derruba
# o processo no Windows (0xC0000409). Vivo ate o fim, o "done" sai antes; depois o servico sai com os._exit.
_LOADED_MODELS: dict[tuple[str, str, str], Any] = {}


def model_loader(model_size: str, device: str, compute_type: str) -> Callable[[], Any]:
    key = (model_size, device, compute_type)

    def get_model() -> Any:
        if key not in _LOADED_MODELS:
            emit("status", "preparing", "loading-model", f"Carregando modelo {model_size}...", progress=8)
            _LOADED_MODELS[key] = subtitle_service.load_whisper_model(model_size, device, compute_type)
        return _LOADED_MODELS[key]

    return get_model


def transcribe_words(model: Any, media_path: str, language: str, beam_size: int) -> list[dict[str, Any]]:
    segments, _info = subtitle_service.run_whisper(model, media_path, language, beam_size)
    words: list[dict[str, Any]] = []
    for segment_index, segment in enumerate(segments):
        words.extend(subtitle_service.whisper_word_dicts(segment, segment_index, len(words)))
    return words


# Transcreve so na primeira vez; depois le o json (o Whisper e a parte cara).
def load_words(
    media: Path, get_model: Callable[[], Any], language: str, beam_size: int, cache: Path | None = None
) -> list[dict[str, Any]]:
    words_path = cache or media.with_suffix(".words.json")
    if words_path.exists():
        return json.loads(words_path.read_text(encoding="utf-8"))
    words = transcribe_words(get_model(), str(media), language, beam_size)
    # Transcricao vazia (faixa errada, so musica) nao vira cache: senao ficaria vazia pra sempre.
    if words:
        words_path.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    return words
