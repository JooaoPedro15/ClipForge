"""Estagio 2: traducao por frase via LLM local.

Recebe a transcricao inteira (cards) + a reference sheet do estagio 1 e
devolve UM grupo por frase: {"cards": [...], "start", "end", "zh", "flag",
"text"}. O SRT final e montado a partir desses grupos, nao dos cards.
"""

import json
from typing import Any

import glossary_service
import llm_prompts
import translation_postprocess

# Cards por chamada. Um corte vertical tipico tem 30-150 cards; acima disso
# a transcricao e fatiada em pedacos (sempre em fronteira de segmento do
# Whisper) pra caber na janela de contexto e nao degradar a saida.
DEFAULT_CHUNK_SIZE = 80
MAX_ATTEMPTS = 2


class LLMTranslationError(RuntimeError):
    """Saida do modelo nao cobre os cards mesmo depois de uma nova tentativa."""


def split_into_chunks(cards: list[dict[str, Any]], chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[list[dict[str, Any]]]:
    """Fatia os cards em pedacos de ate `chunk_size`, cortando de preferencia
    entre segmentos do Whisper (pausa real na fala). Um segmento maior que o
    chunk e cortado no meio mesmo — raro, e melhor que estourar contexto."""
    if len(cards) <= chunk_size:
        return [cards] if cards else []

    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for card in cards:
        starts_new_segment = bool(current) and card.get("segment_id") != current[-1].get("segment_id")
        if len(current) >= chunk_size or (starts_new_segment and _segment_would_overflow(cards, card, current, chunk_size)):
            chunks.append(current)
            current = []
        current.append(card)
    if current:
        chunks.append(current)
    return chunks


def _segment_would_overflow(cards: list[dict[str, Any]], card: dict[str, Any], current: list[dict[str, Any]], chunk_size: int) -> bool:
    segment_len = sum(1 for c in cards if c.get("segment_id") == card.get("segment_id"))
    return len(current) + segment_len > chunk_size


def _coverage_error(groups: list[dict[str, Any]], expected: list[int]) -> str | None:
    seen = [i for g in groups for i in g["cards"]]
    if sorted(seen) != sorted(expected):
        faltando = sorted(set(expected) - set(seen))
        repetidos = sorted({i for i in seen if seen.count(i) > 1})
        extras = sorted(set(seen) - set(expected))
        return f"cobertura quebrada | faltando={faltando} repetidos={repetidos} extras={extras}"
    if seen != sorted(seen):
        return "grupos fora de ordem"
    return None


def _normalize_groups(raw: Any, by_index: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Aceita {"groups": [...]} ou uma lista crua; descarta indices que nao
    existem; start/end/text vem SEMPRE dos cards reais, nunca do modelo."""
    items = raw.get("groups", []) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []

    groups: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        indices: list[int] = []
        for value in item.get("cards", []) or []:
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            if index in by_index:
                indices.append(index)
        indices = sorted(set(indices))
        if not indices:
            continue
        bucket = [by_index[i] for i in indices]
        confidences = [c["avg_logprob"] for c in bucket if c.get("avg_logprob") is not None]
        groups.append(
            {
                "cards": indices,
                "start": bucket[0]["start"],
                "end": bucket[-1]["end"],
                "text": " ".join(c["text"] for c in bucket),
                "zh": str(item.get("zh", "") or "").strip(),
                "flag": str(item.get("flag", "") or "").strip(),
                "avg_logprob": min(confidences) if confidences else None,
            }
        )
    return groups


def _translate_chunk(
    chunk: list[dict[str, Any]],
    sheet: dict[str, Any],
    client: Any,
    max_chars: int,
    min_duration: float,
) -> list[dict[str, Any]]:
    transcript = glossary_service.cards_to_llm_transcript(chunk)
    unclear = set(sheet.get("unclear", []))
    for entry in transcript:
        if entry["i"] in unclear:
            entry["low_confidence"] = True

    system, user = llm_prompts.build_translation_messages(transcript, sheet, max_chars=max_chars, min_duration=min_duration)
    by_index = {c["i"]: c for c in chunk}
    expected = [c["i"] for c in chunk]

    last_error = "sem resposta"
    for attempt in range(MAX_ATTEMPTS):
        raw = client.chat_json(system=system, user=user)
        groups = _normalize_groups(raw, by_index)
        error = _coverage_error(groups, expected)
        if error is None:
            return groups
        last_error = error
        # Segunda tentativa: devolve o erro pro modelo em vez de desistir.
        user = (
            user
            + "\n\n## Previous attempt was rejected\n\n"
            + f"{error}. Every index from {expected[0]} to {expected[-1]} must appear in exactly one group, in order. "
            + "Return the full corrected JSON."
        )

    raise LLMTranslationError(f"estagio 2: {last_error} (cards {expected[0]}..{expected[-1]})")


def translate_with_llm(
    cards: list[dict[str, Any]],
    sheet: dict[str, Any],
    client: Any,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    max_chars: int = 20,
    min_duration: float = 1.2,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for chunk in split_into_chunks(cards, chunk_size):
        groups.extend(_translate_chunk(chunk, sheet, client, max_chars, min_duration))

    for group in groups:
        # Rede de seguranca: nome que sobrou em latim ou variante conhecida
        # vira a grafia canonica do glossario.
        group["zh"] = translation_postprocess.normalize_names(group["zh"], sheet)
        if not group["flag"]:
            group["flag"] = translation_postprocess.confidence_flag(group.get("avg_logprob"))
    return groups
