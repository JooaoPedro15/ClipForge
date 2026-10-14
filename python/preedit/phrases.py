"""Frases da transcricao (pedacos entre pausas) e pares de regravada (a mesma frase dita de novo logo depois)."""

import difflib
from dataclasses import dataclass
from typing import Any

from text_utils import normalize_token

PHRASE_PAUSE = 0.35
SENTENCE_END = (".", "?", "!", "…")
RETAKE_MAX_GAP = 20.0
RETAKE_MAX_DISTANCE = 3
RETAKE_MIN_SIMILARITY = 0.6


@dataclass(frozen=True)
class Phrase:
    index: int
    # Indices da primeira e da ultima palavra (inclusive).
    first: int
    last: int
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def tokens(self) -> list[str]:
        return [token for raw in self.text.split() if (token := normalize_token(raw))]


def ends_sentence(text: str) -> bool:
    return text.rstrip().endswith(SENTENCE_END)


def build_phrases(words: list[dict[str, Any]]) -> list[Phrase]:
    phrases: list[Phrase] = []
    first = 0
    for index, word in enumerate(words):
        is_last = index == len(words) - 1
        gap = 0.0 if is_last else float(words[index + 1]["start"]) - float(word["end"])
        if is_last or gap > PHRASE_PAUSE or ends_sentence(str(word["word"])):
            chunk = words[first : index + 1]
            text = " ".join(str(item["word"]).strip() for item in chunk)
            phrases.append(Phrase(len(phrases), first, index, float(chunk[0]["start"]), float(chunk[-1]["end"]), text))
            first = index + 1
    return phrases


def phrase_of_words(phrases: list[Phrase]) -> list[int]:
    mapping: list[int] = []
    for phrase in phrases:
        mapping.extend([phrase.index] * (phrase.last - phrase.first + 1))
    return mapping


def similarity(a: Phrase, b: Phrase) -> float:
    left, right = a.tokens, b.tokens
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right, autojunk=False).ratio()


# Frase parecida dita de novo em ate 3 frases e 20 s: candidata a regravada (o modelo decide se a primeira sai).
def retake_pairs(phrases: list[Phrase]) -> list[tuple[int, int]]:
    pairs = []
    for first in phrases:
        if len(first.tokens) < 2:
            continue
        for second in phrases[first.index + 1 : first.index + 1 + RETAKE_MAX_DISTANCE]:
            if second.start - first.end > RETAKE_MAX_GAP:
                break
            if similarity(first, second) >= RETAKE_MIN_SIMILARITY:
                pairs.append((first.index, second.index))
    return pairs
