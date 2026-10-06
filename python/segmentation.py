"""Segmentacao da fala em legendas (cards). Puro: recebe palavras como dicts
{word, start, end} e nao conhece o Whisper nem arquivos."""

from typing import Any

from text_utils import WEAK_TRAILING_WORDS, normalize_token

DEFAULT_TARGET_WORDS = 3
DEFAULT_MIN_SUBTITLE_WORDS = 1
DEFAULT_MAX_SUBTITLE_WORDS = 5
DEFAULT_MAX_FAST_SUBTITLE_WORDS = 6
DEFAULT_MIN_SUBTITLE_DURATION = 0.45
DEFAULT_MAX_SUBTITLE_DURATION = 2.0
DEFAULT_IDEAL_SUBTITLE_DURATION_MIN = 0.8
DEFAULT_IDEAL_SUBTITLE_DURATION_MAX = 1.4

# Alguns segmentos "naturais" do Whisper (max_words=0, sem quebra por contagem de
# palavras) podem ficar longos demais quando a fala e continua e a VAD nao detecta
# pausa — sem limite, a legenda fica parada na tela por varios segundos (ou o video
# inteiro) em vez de acompanhar a fala. Acima desse limite, refatia o segmento em
# blocos menores usando os timestamps por palavra, com parametros mais soltos que o
# modo "shorts" (frases mais longas, tipico de legenda de video horizontal).
NATURAL_SPLIT_MAX_DURATION = 7.0
NATURAL_SPLIT_TARGET_WORDS = 8
NATURAL_SPLIT_MIN_WORDS = 3
NATURAL_SPLIT_MAX_WORDS = 14
NATURAL_SPLIT_MAX_WORDS_FAST = 18
NATURAL_SPLIT_MIN_SUBTITLE_DURATION = 1.0
NATURAL_SPLIT_IDEAL_DURATION_MIN = 2.5
NATURAL_SPLIT_IDEAL_DURATION_MAX = 5.0


# Mede a duracao coberta por um grupo de palavras com timestamps do Whisper.
def get_words_duration(words: list[dict[str, Any]]) -> float:
    if not words:
        return 0.0

    start = words[0].get("start")
    end = words[-1].get("end")

    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return 0.0

    return max(0.0, float(end) - float(start))


# Segmenta timestamps por palavra buscando blocos naturais em torno de target_words palavras.
def segment_words_naturally(
    words: list[dict[str, Any]],
    target_words: int = DEFAULT_TARGET_WORDS,
    min_words: int = DEFAULT_MIN_SUBTITLE_WORDS,
    max_words: int = DEFAULT_MAX_SUBTITLE_WORDS,
    max_words_fast_speech: int = DEFAULT_MAX_FAST_SUBTITLE_WORDS,
    min_duration: float = DEFAULT_MIN_SUBTITLE_DURATION,
    max_duration: float = DEFAULT_MAX_SUBTITLE_DURATION,
    ideal_duration_min: float = DEFAULT_IDEAL_SUBTITLE_DURATION_MIN,
    ideal_duration_max: float = DEFAULT_IDEAL_SUBTITLE_DURATION_MAX,
) -> list[list[dict[str, Any]]]:
    word_items = list(words)
    if not word_items:
        return []

    min_words = max(1, min_words)
    target_words = max(min_words, target_words or DEFAULT_TARGET_WORDS)
    max_words = max(target_words, max_words)
    max_words_fast_speech = max(max_words, max_words_fast_speech)

    segments: list[list[dict[str, Any]]] = []
    index = 0

    while index < len(word_items):
        remaining = len(word_items) - index
        normal_limit = min(max_words, remaining)
        fast_limit = min(max_words_fast_speech, remaining)
        fast_duration = get_words_duration(word_items[index : index + fast_limit])
        limit = fast_limit if fast_limit > normal_limit and 0 < fast_duration <= max_duration else normal_limit
        best_count = min(target_words, limit)
        best_score = float("inf")

        for count in range(min(min_words, remaining), limit + 1):
            candidate = word_items[index : index + count]
            duration = get_words_duration(candidate)
            remaining_after = remaining - count
            trailing_word = normalize_token(str(candidate[-1].get("word", "")))
            score = abs(count - target_words) * 10

            if trailing_word in WEAK_TRAILING_WORDS and remaining_after > 0:
                score += 80

            if remaining_after == 1 and count < limit:
                score += 45

            if duration > 0:
                if duration < min_duration:
                    score += (min_duration - duration) * 30
                elif ideal_duration_min <= duration <= ideal_duration_max:
                    score -= 6
                elif duration < ideal_duration_min:
                    score += (ideal_duration_min - duration) * 8
                elif duration <= max_duration:
                    score += (duration - ideal_duration_max) * 8
                else:
                    score += 40 + (duration - max_duration) * 60

            if count > max_words:
                score += (count - max_words) * 6

            if score < best_score:
                best_score = score
                best_count = count

        while best_count < limit:
            trailing_word = normalize_token(str(word_items[index + best_count - 1].get("word", "")))
            if trailing_word not in WEAK_TRAILING_WORDS:
                break
            best_count += 1

        if remaining - best_count == 1 and best_count < limit:
            best_count += 1

        segments.append(word_items[index : index + best_count])
        index += best_count

    return segments


# Refatia um segmento natural longo demais em blocos menores (parametros do modo horizontal).
def split_long_segment_words(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return segment_words_naturally(
        words,
        target_words=NATURAL_SPLIT_TARGET_WORDS,
        min_words=NATURAL_SPLIT_MIN_WORDS,
        max_words=NATURAL_SPLIT_MAX_WORDS,
        max_words_fast_speech=NATURAL_SPLIT_MAX_WORDS_FAST,
        min_duration=NATURAL_SPLIT_MIN_SUBTITLE_DURATION,
        max_duration=NATURAL_SPLIT_MAX_DURATION,
        ideal_duration_min=NATURAL_SPLIT_IDEAL_DURATION_MIN,
        ideal_duration_max=NATURAL_SPLIT_IDEAL_DURATION_MAX,
    )


# Transforma um segmento do Whisper em cards de legenda:
# - max_words > 0 (shorts): grupos curtos de palavras;
# - segmento natural longo (> NATURAL_SPLIT_MAX_DURATION): refatiado;
# - senao (ou sem palavras): o segmento inteiro vira um card.
# `text` guarda o texto cru (case original): a traducao usa os cards.
def cards_for_segment(
    words: list[dict[str, Any]],
    segment: dict[str, Any],
    max_words: int,
    first_index: int,
) -> list[dict[str, Any]]:
    if max_words > 0 and words:
        groups = segment_words_naturally(words, target_words=max_words)
    elif words and (segment["end"] - segment["start"]) > NATURAL_SPLIT_MAX_DURATION:
        groups = split_long_segment_words(words)
    else:
        return [
            {
                "i": first_index,
                "start": segment["start"],
                "end": segment["end"],
                "text": str(segment["text"]).strip(),
                "segment_id": segment["id"],
                "avg_logprob": segment["avg_logprob"],
            }
        ]

    return [
        {
            "i": first_index + offset,
            "start": group[0]["start"],
            "end": group[-1]["end"],
            "text": " ".join(str(word["word"]).strip() for word in group),
            "segment_id": segment["id"],
            "avg_logprob": segment["avg_logprob"],
        }
        for offset, group in enumerate(groups)
    ]
