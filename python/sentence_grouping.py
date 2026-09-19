from typing import Any

DEFAULT_MAX_GROUP_DURATION = 7.0


def group_cards_into_sentences(
    cards: list[dict[str, Any]],
    max_group_duration: float = DEFAULT_MAX_GROUP_DURATION,
) -> list[dict[str, Any]]:
    """Agrupa cards consecutivos do mesmo segment_id (mesma "frase" detectada
    pela VAD do Whisper — sem pausa entre eles) numa unica entrada de traducao.
    Isso e o que substitui a etapa de "estagio 1" de um LLM: a fronteira de
    frase ja veio de graca da propria transcricao, nao precisa de um modelo
    decidindo onde cortar.
    """
    if not cards:
        return []

    groups: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = [cards[0]]

    def flush(bucket: list[dict[str, Any]]) -> dict[str, Any]:
        confidences = [c["avg_logprob"] for c in bucket if c.get("avg_logprob") is not None]
        return {
            "cards": [c["i"] for c in bucket],
            "start": bucket[0]["start"],
            "end": bucket[-1]["end"],
            "text": " ".join(c["text"] for c in bucket),
            # None quando nenhum card do grupo tem avg_logprob (ex.: cards.json
            # de video transcrito antes da Task 1 existir) — nao estoura em
            # min() de sequencia vazia.
            "avg_logprob": min(confidences) if confidences else None,
        }

    for card in cards[1:]:
        same_segment = card["segment_id"] == current[-1]["segment_id"]
        would_exceed_duration = (card["end"] - current[0]["start"]) > max_group_duration
        if same_segment and not would_exceed_duration:
            current.append(card)
        else:
            groups.append(flush(current))
            current = [card]

    groups.append(flush(current))
    return groups
