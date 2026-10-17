"""Plano de edicao do video longo: tira regravadas e o mais fraco ate a duracao alvo, apara pausas e escolhe zooms."""

from dataclasses import dataclass, field
from typing import Any

from preedit.audio import Loudness
from preedit.features import pause_features, phrase_features, retake_features, zoom_features
from preedit.models import FormatModels, probabilities
from preedit.phrases import Phrase, build_phrases, ends_sentence, phrase_of_words, retake_pairs
from preedit.project_labels import merge_ranges
from preedit.types import Range

TARGET_TOLERANCE = 0.05
# Frase que prepara uma frase forte (nota >= 0.8) colada nela nao sai: sem ela a piada perde o sentido.
PROTECT_SCORE = 0.8
PROTECT_GAP = 0.7
# Folga de cada lado de um corte (nao corta a palavra no talo).
CUT_PAD = 0.12
DEFAULT_PAUSE_KEEP = 0.3
RETAKE_THRESHOLD = 0.5
ZOOM_FLOOR = 0.2


@dataclass
class Segment:
    start: float
    end: float
    zoom: float | None = None


@dataclass
class EditPlan:
    segments: list[Segment]
    # (segundos no video final, nome do marcador)
    markers: list[tuple[float, str]] = field(default_factory=list)
    duration: float = 0.0
    zooms: int = 0
    warnings: list[str] = field(default_factory=list)


def _pause_keeps(words: list[dict[str, Any]], phrases: list[Phrase], loud: Loudness, interest: dict[int, float], models: FormatModels) -> list[float]:
    """Pausa que sobra entre cada frase e a seguinte, se as duas ficarem (previsao uma vez so, em lote)."""
    mapping = phrase_of_words(phrases)
    gaps = [phrases[i + 1].start - phrases[i].end for i in range(len(phrases) - 1)]
    if models.pausa is None or not gaps:
        return [min(gap, DEFAULT_PAUSE_KEEP) for gap in gaps]
    rows = [pause_features(words, phrases[i].last, mapping, loud, interest) for i in range(len(gaps))]
    predicted = models.pausa.predict(rows)
    return [max(0.0, min(gap, float(ms) / 1000)) for gap, ms in zip(gaps, predicted, strict=True)]


def _ranges(phrases: list[Phrase], keep: dict[int, bool], pause_keep: list[float]) -> list[Range]:
    kept = [phrase for phrase in phrases if keep[phrase.index]]
    ranges = []
    for position, phrase in enumerate(kept):
        before = kept[position - 1] if position else None
        after = kept[position + 1] if position + 1 < len(kept) else None
        if before is not None and before.index == phrase.index - 1:
            start = phrase.start - pause_keep[before.index] * 0.55
        else:
            gap = phrase.start - (phrases[phrase.index - 1].end if phrase.index else 0.0)
            start = max(0.0, phrase.start - min(CUT_PAD, gap))
        if after is not None and after.index == phrase.index + 1:
            end = phrase.end + pause_keep[phrase.index] * 0.45
        else:
            gap = (phrases[phrase.index + 1].start - phrase.end) if phrase.index + 1 < len(phrases) else CUT_PAD
            end = phrase.end + min(CUT_PAD, gap)
        ranges.append(Range(round(start, 3), round(end, 3)))
    return merge_ranges(ranges, gap=0.001)


def _total(ranges: list[Range]) -> float:
    return sum(item.duration for item in ranges)


def _to_final(time: float, ranges: list[Range]) -> float:
    elapsed = 0.0
    for item in ranges:
        if time < item.start:
            return elapsed
        if time <= item.end:
            return elapsed + time - item.start
        elapsed += item.duration
    return elapsed


def _protected(phrase: Phrase, phrases: list[Phrase], keep: dict[int, bool], score: dict[int, float]) -> bool:
    if phrase.index + 1 >= len(phrases):
        return False
    following = phrases[phrase.index + 1]
    return (
        keep[following.index]
        and score[following.index] >= PROTECT_SCORE
        and following.start - phrase.end < PROTECT_GAP
        and not ends_sentence(phrase.text)
    )


def _choose_zooms(
    phrases: list[Phrase], keep: dict[int, bool], ranges: list[Range], loud: Loudness, interest: dict[int, float], models: FormatModels
) -> list[tuple[float, float, float]]:
    """Zooms (inicio, fim, nivel) na gravacao: os mais provaveis, no ritmo aprendido e com distancia minima."""
    params = models.params
    total = _total(ranges)
    wanted = round(float(params.get("zooms_per_min", 0.0)) * total / 60)
    kept = [phrase for phrase in phrases if keep[phrase.index]]
    if models.zoom is None or wanted <= 0 or not kept:
        return []
    rows = [zoom_features(p, loud, interest, 120.0, _to_final(p.start, ranges) / total if total else 0.0) for p in kept]
    chance = probabilities(models.zoom, rows)
    levels = models.nivel.predict(rows) if models.nivel is not None else [params["zoom_level_median"]] * len(rows)
    order = sorted(range(len(kept)), key=lambda i: -chance[i])
    shortest, longest = float(params["zoom_duration_p10"]), float(params["zoom_duration_p90"])
    chosen: list[tuple[float, float, float]] = []
    taken_final: list[float] = []
    for i in order:
        if len(chosen) >= wanted or chance[i] < ZOOM_FLOOR:
            break
        phrase = kept[i]
        length = max(shortest, min(longest, phrase.duration))
        start = max(phrase.start, phrase.end - length)
        at = _to_final(start, ranges)
        if any(abs(at - other) < float(params["zoom_min_gap_s"]) for other in taken_final):
            continue
        chosen.append((start, phrase.end, round(float(levels[i]), 3)))
        taken_final.append(at)
    return sorted(chosen)


def _segments(ranges: list[Range], zooms: list[tuple[float, float, float]]) -> list[Segment]:
    segments: list[Segment] = []
    for item in ranges:
        cursor = item.start
        for start, end, level in zooms:
            if end <= item.start or start >= item.end:
                continue
            start, end = max(start, item.start), min(end, item.end)
            if start > cursor:
                segments.append(Segment(cursor, start))
            segments.append(Segment(start, end, level))
            cursor = end
        if cursor < item.end:
            segments.append(Segment(cursor, item.end))
    return [segment for segment in segments if segment.end - segment.start > 0.01]


# Um marcador no comeco de cada sequencia de frases tiradas (inclusive no inicio do video), com o motivo da primeira.
def _markers(phrases: list[Phrase], keep: dict[int, bool], reasons: dict[int, str], ranges: list[Range]) -> list[tuple[float, str]]:
    markers = []
    in_removed_run = False
    for phrase in phrases:
        if keep[phrase.index]:
            in_removed_run = False
            continue
        if not in_removed_run:
            markers.append((round(_to_final(phrase.start, ranges), 3), reasons.get(phrase.index, "sem graca")))
        in_removed_run = True
    return markers


# Gravacao pausada no OBS (varios arquivos): o tempo do video final e dividido pela fala de cada um.
def split_target(speech_sec: list[float], target_sec: float) -> list[float]:
    total = sum(speech_sec)
    if total <= 0:
        return [0.0 for _ in speech_sec]
    return [target_sec * seconds / total for seconds in speech_sec]


def plan_long(
    words: list[dict[str, Any]], loud: Loudness, interest: dict[int, float], models: FormatModels, target_sec: float
) -> EditPlan:
    phrases = build_phrases(words)
    if not phrases:
        return EditPlan([], warnings=["A gravacao nao tem fala reconhecida."])
    total = float(words[-1]["end"])
    keep = {phrase.index: True for phrase in phrases}
    reasons: dict[int, str] = {}

    pairs = retake_pairs(phrases)
    if models.regravada is not None and pairs:
        chances = probabilities(models.regravada, [retake_features(phrases, a, b, interest) for a, b in pairs])
        for (first, _second), chance in zip(pairs, chances, strict=True):
            if chance >= RETAKE_THRESHOLD:
                keep[first] = False
                reasons[first] = "regravada"

    scores = probabilities(models.trecho, [phrase_features(phrases, p.index, loud, interest, total) for p in phrases])
    score = {phrase.index: value for phrase, value in zip(phrases, scores, strict=True)}
    pause_keep = _pause_keeps(words, phrases, loud, interest, models)

    warnings = []
    ranges = _ranges(phrases, keep, pause_keep)
    limit = target_sec * (1 + TARGET_TOLERANCE)
    if _total(ranges) < target_sec * (1 - TARGET_TOLERANCE):
        warnings.append(f"A gravacao ja e mais curta que {target_sec / 60:.0f} min depois das pausas: nenhum trecho tirado por tempo.")
    for phrase in sorted(phrases, key=lambda item: score[item.index]):
        if _total(ranges) <= limit:
            break
        if not keep[phrase.index] or _protected(phrase, phrases, keep, score):
            continue
        keep[phrase.index] = False
        reasons[phrase.index] = "sem graca"
        ranges = _ranges(phrases, keep, pause_keep)

    zooms = _choose_zooms(phrases, keep, ranges, loud, interest, models)
    return EditPlan(
        segments=_segments(ranges, zooms),
        markers=_markers(phrases, keep, reasons, ranges),
        duration=round(_total(ranges), 3),
        zooms=len(zooms),
        warnings=warnings,
    )
