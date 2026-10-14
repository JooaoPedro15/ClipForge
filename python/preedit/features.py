"""Sinais de cada decisao do Pre-editor. A ordem segue as listas de nomes (e assim que a arvore mostra)."""

from typing import Any

from text_utils import WEAK_TRAILING_WORDS, normalize_token

from preedit.audio import Loudness
from preedit.phrases import Phrase, ends_sentence, similarity

PHRASE_FEATURES = [
    "duracao",
    "palavras_por_s",
    "volume_medio",
    "volume_pico",
    "pico_isolado",
    "nota_ia",
    "nota_ia_vizinhas",
    "posicao",
    "sim_anterior",
    "sim_seguinte",
    "exclamacao",
    "pergunta",
]
RETAKE_FEATURES = ["similaridade", "distancia_s", "razao_tamanho", "nota_ia_primeira", "nota_ia_segunda", "primeira_completa"]
PAUSE_FEATURES = ["pausa_ms", "fim_de_frase", "conector_antes", "nota_ia_seguinte", "volume_depois"]
ZOOM_FEATURES = ["volume_pico", "pico_isolado", "nota_ia", "exclamacao", "desde_ultimo_zoom_s", "duracao", "posicao"]

NEUTRAL = 5.0
# Distancia maxima contada desde o ultimo zoom (alem disso, "faz tempo").
MAX_SINCE_ZOOM = 120.0


def _relative_volume(loud: Loudness, start: float, end: float) -> tuple[float, float, float]:
    """Media e pico relativos a mediana do video, e quanto o pico passa da media (grito, risada)."""
    mean, peak = loud.stats(start, end)
    median = loud.median
    return mean - median, peak - median, peak - mean


def phrase_features(phrases: list[Phrase], index: int, loud: Loudness, interest: dict[int, float], total: float) -> list[float]:
    phrase = phrases[index]
    mean, peak, isolated = _relative_volume(loud, phrase.start, phrase.end)
    neighbors = [interest.get(i, NEUTRAL) for i in (index - 1, index + 1) if 0 <= i < len(phrases)]
    words = max(1, len(phrase.text.split()))
    return [
        phrase.duration,
        words / max(phrase.duration, 0.1),
        mean,
        peak,
        isolated,
        interest.get(phrase.index, NEUTRAL),
        sum(neighbors) / len(neighbors) if neighbors else NEUTRAL,
        phrase.start / total if total else 0.0,
        similarity(phrases[index - 1], phrase) if index > 0 else 0.0,
        similarity(phrase, phrases[index + 1]) if index + 1 < len(phrases) else 0.0,
        1.0 if phrase.text.rstrip().endswith("!") else 0.0,
        1.0 if phrase.text.rstrip().endswith("?") else 0.0,
    ]


def retake_features(phrases: list[Phrase], first: int, second: int, interest: dict[int, float]) -> list[float]:
    a, b = phrases[first], phrases[second]
    return [
        similarity(a, b),
        b.start - a.end,
        len(a.tokens) / max(1, len(b.tokens)),
        interest.get(a.index, NEUTRAL),
        interest.get(b.index, NEUTRAL),
        1.0 if ends_sentence(a.text) else 0.0,
    ]


def pause_features(
    words: list[dict[str, Any]], word_index: int, phrase_of_word: list[int], loud: Loudness, interest: dict[int, float]
) -> list[float]:
    word, following = words[word_index], words[word_index + 1]
    text = str(word["word"]).strip()
    after_start = float(following["start"])
    return [
        (after_start - float(word["end"])) * 1000,
        1.0 if ends_sentence(text) else 0.0,
        1.0 if normalize_token(text) in WEAK_TRAILING_WORDS else 0.0,
        interest.get(phrase_of_word[word_index + 1], NEUTRAL),
        loud.stats(after_start, after_start + 0.5)[0] - loud.median,
    ]


def zoom_features(phrase: Phrase, loud: Loudness, interest: dict[int, float], since_last_zoom: float, position: float) -> list[float]:
    _mean, peak, isolated = _relative_volume(loud, phrase.start, phrase.end)
    return [
        peak,
        isolated,
        interest.get(phrase.index, NEUTRAL),
        1.0 if phrase.text.rstrip().endswith("!") else 0.0,
        min(since_last_zoom, MAX_SINCE_ZOOM),
        phrase.duration,
        position,
    ]
