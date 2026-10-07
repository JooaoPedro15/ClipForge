"""Alinhamento do SRT corrigido pelo usuario com as palavras do Whisper.

A comparacao e pelo TEXTO (palavra normalizada), nunca pelo tempo: o video
final pode ter silencios cortados no Premiere, entao os tempos dele nao batem
com os do video original.
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from text_utils import normalize_token

# Abaixo disso o SRT (ou o video final) quase certamente nao e do mesmo video.
MIN_MATCH_RATIO = 0.6

_TIMESTAMP_RE = re.compile(r"(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})")
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Card:
    start: float
    end: float
    text: str


def parse_timestamp(value: str) -> float:
    match = _TIMESTAMP_RE.search(value)
    if not match:
        raise ValueError(f"Timestamp invalido no SRT: {value!r}")
    hours, minutes, seconds, millis = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis.ljust(3, "0")) / 1000


# Le SRT exportado pelo Premiere: BOM, CRLF e tags de formatacao (<i>, <b>) sao comuns.
def parse_srt_text(content: str) -> list[Card]:
    normalized = content.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cards: list[Card] = []
    for block in re.split(r"\n\s*\n", normalized.strip()):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        arrow_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if arrow_index is None:
            continue
        start_text, end_text = lines[arrow_index].split("-->", 1)
        text = _TAG_RE.sub("", " ".join(lines[arrow_index + 1 :])).strip()
        if text:
            cards.append(Card(start=parse_timestamp(start_text), end=parse_timestamp(end_text), text=text))
    return cards


@dataclass
class BreakAlignment:
    # gap i = espaco entre a palavra original i e i+1 -> 1 se o usuario quebrou a legenda ali.
    labels: dict[int, int]
    # palavra original -> indice da legenda corrigida (so palavras que casaram).
    word_card: dict[int, int]
    match_ratio: float
    # (como o Whisper escreveu, como o usuario escreveu) nas trocas de 1 palavra por 1.
    word_fixes: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class SpeechAlignment:
    # legenda corrigida -> (inicio da fala, fim da fala) no video FINAL.
    card_speech: dict[int, tuple[float, float]]
    match_ratio: float


def _word_tokens(words: list[dict[str, Any]]) -> tuple[list[str], list[int]]:
    tokens: list[str] = []
    indexes: list[int] = []
    for index, word in enumerate(words):
        token = normalize_token(str(word["word"]))
        if token:
            tokens.append(token)
            indexes.append(index)
    return tokens, indexes


def _card_tokens(cards: list[Card]) -> tuple[list[str], list[int], list[str]]:
    tokens: list[str] = []
    card_indexes: list[int] = []
    raw_words: list[str] = []
    for card_index, card in enumerate(cards):
        for raw in card.text.split():
            token = normalize_token(raw)
            if token:
                tokens.append(token)
                card_indexes.append(card_index)
                raw_words.append(raw)
    return tokens, card_indexes, raw_words


def _opcodes(a: list[str], b: list[str]):
    # autojunk=False e obrigatorio: com o padrao, em listas com mais de 200 itens o
    # difflib ignora itens frequentes ("que", "de", "ne") e o alinhamento desanda.
    return SequenceMatcher(None, a, b, autojunk=False).get_opcodes()


def align_breaks(words: list[dict[str, Any]], cards: list[Card]) -> BreakAlignment:
    a_tokens, a_words = _word_tokens(words)
    b_tokens, b_cards, b_raw = _card_tokens(cards)

    word_card: dict[int, int] = {}
    word_position: dict[int, int] = {}
    word_fixes: list[tuple[str, str]] = []
    for tag, a0, a1, b0, b1 in _opcodes(a_tokens, b_tokens):
        if tag == "equal":
            for offset in range(a1 - a0):
                word_index = a_words[a0 + offset]
                word_card[word_index] = b_cards[b0 + offset]
                word_position[word_index] = b0 + offset
        elif tag == "replace" and a1 - a0 == 1 and b1 - b0 == 1:
            word_fixes.append((str(words[a_words[a0]]["word"]).strip(), b_raw[b0]))

    labels: dict[int, int] = {}
    for index in range(len(words) - 1):
        here = word_position.get(index)
        after = word_position.get(index + 1)
        # So rotula quando as duas palavras casaram e estao coladas no SRT corrigido;
        # perto de palavra trocada/apagada o app nao chuta.
        if here is None or after is None or after != here + 1:
            continue
        labels[index] = int(word_card[index] != word_card[index + 1])

    ratio = len(word_card) / max(len(a_tokens), len(b_tokens), 1)
    return BreakAlignment(labels=labels, word_card=word_card, match_ratio=ratio, word_fixes=word_fixes)


def align_speech(cards: list[Card], final_words: list[dict[str, Any]]) -> SpeechAlignment:
    a_tokens, a_words = _word_tokens(final_words)
    b_tokens, b_cards, _raw = _card_tokens(cards)

    position_word: dict[int, int] = {}
    for tag, a0, a1, b0, _b1 in _opcodes(a_tokens, b_tokens):
        if tag == "equal":
            for offset in range(a1 - a0):
                position_word[b0 + offset] = a_words[a0 + offset]

    first_position: dict[int, int] = {}
    last_position: dict[int, int] = {}
    for position, card_index in enumerate(b_cards):
        first_position.setdefault(card_index, position)
        last_position[card_index] = position

    card_speech: dict[int, tuple[float, float]] = {}
    for card_index, first in first_position.items():
        last = last_position[card_index]
        # Primeira e ultima palavra precisam ter casado; senao o tempo da fala e chute.
        if first in position_word and last in position_word:
            start = float(final_words[position_word[first]]["start"])
            end = float(final_words[position_word[last]]["end"])
            card_speech[card_index] = (start, end)

    ratio = len(position_word) / max(len(a_tokens), len(b_tokens), 1)
    return SpeechAlignment(card_speech=card_speech, match_ratio=ratio)
