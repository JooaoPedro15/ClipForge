"""Pontos onde da pra cortar: ninguem falando (filme e mic), de preferencia num corte de plano."""

import bisect
from dataclasses import dataclass

MIN_GAP_SEC = 0.7  # buraco minimo sem fala
MERGE_SEC = 3.0  # candidatos mais perto que isso: fica o de maior nota
EDGE_SEC = 1.0  # nada colado no inicio/fim do trecho
JUDGE_WEIGHT = 0.6
SENTENCE_END = (".", "?", "!", "…")


@dataclass
class Candidate:
    id: str
    t: float
    rule: float
    judge: float | None = None

    @property
    def score(self) -> float:
        if self.judge is None:
            return self.rule
        return round((1 - JUDGE_WEIGHT) * self.rule + JUDGE_WEIGHT * self.judge, 2)


def speech_intervals(words: list[dict], merge_gap: float = MIN_GAP_SEC) -> list[tuple[float, float]]:
    spans = sorted((float(word["start"]), float(word["end"])) for word in words if word["end"] > word["start"])
    merged: list[tuple[float, float]] = []
    for start, end in spans:
        if merged and start - merged[-1][1] < merge_gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def silent_gaps(
    film_words: list[dict], mic_words: list[dict], start: float, end: float, min_gap: float = MIN_GAP_SEC
) -> list[tuple[float, float]]:
    busy = [(s, e) for s, e in speech_intervals([*film_words, *mic_words], min_gap) if e > start and s < end]
    gaps = []
    cursor = start
    for speech_start, speech_end in busy:
        if speech_start - cursor >= min_gap:
            gaps.append((cursor, speech_start))
        cursor = max(cursor, speech_end)
    if end - cursor >= min_gap:
        gaps.append((cursor, end))
    return gaps


def rule_score(gap_sec: float, on_shot_cut: bool, in_silence: bool, after_sentence_end: bool) -> float:
    score = min(gap_sec, 4.0)
    score += 3.0 if on_shot_cut else 0.0
    score += 1.5 if in_silence else 0.0
    score += 1.5 if after_sentence_end else 0.0
    return round(min(score, 10.0), 2)


def build_candidates(
    film_words: list[dict],
    mic_words: list[dict],
    shot_cuts: list[float],
    film_silences: list[tuple[float, float]],
    start: float,
    end: float,
) -> list[Candidate]:
    film_by_end = sorted(film_words, key=lambda word: word["end"])
    ends = [word["end"] for word in film_by_end]
    cuts = sorted(shot_cuts)
    raw: list[tuple[float, float]] = []
    for gap_start, gap_end in silent_gaps(film_words, mic_words, start, end):
        middle = (gap_start + gap_end) / 2
        inside = cuts[bisect.bisect_left(cuts, gap_start) : bisect.bisect_right(cuts, gap_end)]
        t = min(inside, key=lambda cut: abs(cut - middle)) if inside else middle
        if t - start < EDGE_SEC or end - t < EDGE_SEC:
            continue
        last = bisect.bisect_right(ends, t) - 1
        sentence_end = last >= 0 and film_by_end[last]["word"].strip().endswith(SENTENCE_END)
        silent = any(a <= t <= b for a, b in film_silences)
        raw.append((t, rule_score(gap_end - gap_start, bool(inside), silent, sentence_end)))

    kept: list[tuple[float, float]] = []
    for t, score in raw:  # silent_gaps ja devolve em ordem de tempo
        if kept and t - kept[-1][0] < MERGE_SEC:
            if score > kept[-1][1]:
                kept[-1] = (t, score)
            continue
        kept.append((t, score))
    return [Candidate(id=f"C{n}", t=round(t, 3), rule=score) for n, (t, score) in enumerate(kept, 1)]
