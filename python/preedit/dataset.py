"""Exemplos de treino de uma gravacao: cruza o gabarito do projeto com a transcricao, o volume e as notas da IA."""

import itertools
from typing import Any

from preedit.audio import Loudness
from preedit.features import pause_features, phrase_features, retake_features, zoom_features
from preedit.phrases import build_phrases, phrase_of_words, retake_pairs
from preedit.types import Range, RecordingLabels

# Frase/palavra com pelo menos metade do tempo dentro do que ficou conta como mantida.
KEEP_COVERAGE = 0.5
MIN_PAUSE = 0.1
# Frase com zoom: um zoom cobre pelo menos 40% da parte dela que ficou (ou 0,5 s).
ZOOM_MIN_SHARE = 0.4
ZOOM_MIN_SEC = 0.5


def overlap(start: float, end: float, ranges: list[Range]) -> float:
    return sum(max(0.0, min(end, item.end) - max(start, item.start)) for item in ranges)


def coverage(start: float, end: float, ranges: list[Range]) -> float:
    return overlap(start, end, ranges) / (end - start) if end > start else 0.0


def build_examples(labels: RecordingLabels, words: list[dict[str, Any]], loud: Loudness, interest: dict[int, float]) -> dict:
    phrases = build_phrases(words)
    mapping = phrase_of_words(phrases)
    span = labels.span
    total = float(words[-1]["end"]) if words else 0.0
    in_span = [p for p in phrases if p.end > span.start and p.start < span.end]
    kept = {p.index: coverage(p.start, p.end, labels.kept) >= KEEP_COVERAGE for p in phrases}
    inside = {p.index for p in in_span}

    # Video final: tudo o que esta no mp4 ficou e nao se sabe o que saiu; so o zoom ensina.
    phrase_rows = [] if labels.final else [{"x": phrase_features(phrases, p.index, loud, interest, total), "y": int(kept[p.index])} for p in in_span]

    retake_rows = (
        []
        if labels.final
        else [
            {"x": retake_features(phrases, first, second, interest), "y": int(not kept[first] and kept[second])}
            for first, second in retake_pairs(phrases)
            if first in inside and second in inside
        ]
    )

    pause_rows = []
    if not labels.preedited and not labels.final:
        for index in range(len(words) - 1):
            word, following = words[index], words[index + 1]
            gap_start, gap_end = float(word["end"]), float(following["start"])
            if gap_end - gap_start < MIN_PAUSE:
                continue
            word_kept = coverage(float(word["start"]), gap_start, labels.kept) >= KEEP_COVERAGE
            next_kept = coverage(gap_end, float(following["end"]), labels.kept) >= KEEP_COVERAGE
            if word_kept and next_kept:
                pause_rows.append(
                    {"x": pause_features(words, index, mapping, loud, interest), "y": overlap(gap_start, gap_end, labels.kept) * 1000}
                )

    final_sec = sum(item.duration for item in labels.kept)
    zoom_rows = []
    position = 0.0
    last_zoom_end: float | None = None
    for phrase in in_span:
        kept_part = overlap(phrase.start, phrase.end, labels.kept)
        if not kept[phrase.index] or kept_part <= 0:
            continue
        touching = [z for z in labels.zooms if overlap(z.start, z.end, [Range(phrase.start, phrase.end)]) > 0]
        zoomed_sec = sum(overlap(z.start, z.end, [Range(phrase.start, phrase.end)]) for z in touching)
        zoomed = bool(touching) and zoomed_sec >= min(ZOOM_MIN_SHARE * kept_part, ZOOM_MIN_SEC)
        since = position - last_zoom_end if last_zoom_end is not None else float("inf")
        zoom_rows.append(
            {
                "x": zoom_features(phrase, loud, interest, since, position / final_sec if final_sec else 0.0),
                "y": int(zoomed),
                "level": max(z.level for z in touching) if zoomed else None,
            }
        )
        position += kept_part
        if zoomed:
            last_zoom_end = position

    starts = [zoom.start for zoom in labels.zooms]
    return {
        "recording": labels.recording,
        "format": labels.format,
        "final": labels.final,
        "phrase": phrase_rows,
        "retake": retake_rows,
        "pause": pause_rows,
        "zoom": zoom_rows,
        "stats": {
            "final_sec": final_sec,
            "zooms": len(labels.zooms),
            "zoom_durations": [round(z.end - z.start, 3) for z in labels.zooms],
            "zoom_levels": [z.level for z in labels.zooms],
            "zoom_gaps": [round(b - a, 3) for a, b in itertools.pairwise(starts)],
        },
    }
