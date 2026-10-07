"""Transforma o alinhamento em exemplos de treino (quebras) e amostras de tempo.

Toda feature sai do video CRU (words.json original): e isso que o modelo vai ver
na hora de gerar. Pausas do video final estao encurtadas pelos cortes do usuario
e ensinariam errado.
"""

from typing import Any

from style_alignment import BreakAlignment, Card, SpeechAlignment
from text_utils import WEAK_TRAILING_WORDS, normalize_token

# Mesma ordem de gap_features (aparece assim na arvore que a tela mostra).
FEATURE_NAMES = [
    "pausa_ms",
    "palavras_na_legenda",
    "legenda_ms",
    "caracteres_na_legenda",
    "palavra_fraca",
    "pontuacao",
    "proxima_abre_frase",
    "fim_de_segmento",
    "palavras_por_segundo",
]

# Palavras que costumam abrir frase: quebrar ANTES delas e natural.
OPENER_WORDS = {"ai", "mas", "entao", "porque", "e", "so"}
SPEECH_RATE_WINDOW = 5


# Retrato do espaco entre a palavra `index` e a seguinte, com a legenda atual comecando em `card_start`.
def gap_features(words: list[dict[str, Any]], card_start: int, index: int) -> list[float]:
    word = words[index]
    next_word = words[index + 1] if index + 1 < len(words) else word
    text = str(word["word"]).strip()

    pause_ms = max(0.0, (float(next_word["start"]) - float(word["end"])) * 1000)
    words_in_card = float(index - card_start + 1)
    card_ms = max(0.0, (float(word["end"]) - float(words[card_start]["start"])) * 1000)
    card_chars = float(len(" ".join(str(item["word"]).strip() for item in words[card_start : index + 1])))
    weak_word = 1.0 if normalize_token(text) in WEAK_TRAILING_WORDS else 0.0
    if text.endswith((".", "?", "!", "…")):
        punctuation = 2.0
    elif text.endswith((",", ";", ":")):
        punctuation = 1.0
    else:
        punctuation = 0.0
    next_opener = 1.0 if normalize_token(str(next_word["word"])) in OPENER_WORDS else 0.0
    segment_end = 1.0 if word.get("segment_end") else 0.0

    window = words[max(0, index - SPEECH_RATE_WINDOW + 1) : index + 1]
    span = float(window[-1]["end"]) - float(window[0]["start"])
    speech_rate = len(window) / span if span > 0 else 0.0

    return [pause_ms, words_in_card, card_ms, card_chars, weak_word, punctuation, next_opener, segment_end, speech_rate]


# Um exemplo {x: features, y: quebrou?} por espaco rotulado; o estado da legenda segue as quebras do usuario.
def build_gap_examples(words: list[dict[str, Any]], alignment: BreakAlignment) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    card_start = 0
    current_card = alignment.word_card.get(0)

    for index in range(len(words) - 1):
        label = alignment.labels.get(index)
        next_card = alignment.word_card.get(index + 1)

        if label is not None:
            examples.append({"x": gap_features(words, card_start, index), "y": label})
            if label == 1:
                card_start = index + 1
                current_card = next_card
            continue

        # Espaco sem rotulo (perto de palavra trocada): nao vira exemplo, mas ainda
        # acompanha em qual legenda do usuario estamos pra manter o estado certo.
        if next_card is not None and next_card != current_card:
            if current_card is not None:
                card_start = index + 1
            current_card = next_card

    return examples


# Quanto antes da fala a legenda entra, quanto segura depois, quais buracos o usuario fecha e o tamanho delas.
def build_timing_samples(
    words: list[dict[str, Any]],
    cards: list[Card],
    breaks: BreakAlignment,
    speech: SpeechAlignment,
) -> dict[str, list[Any]]:
    lead_in_ms: list[float] = []
    hold_ms: list[float] = []
    for card_index, (speech_start, speech_end) in sorted(speech.card_speech.items()):
        card = cards[card_index]
        lead_in_ms.append((speech_start - card.start) * 1000)
        hold_ms.append((card.end - speech_end) * 1000)

    card_words: dict[int, list[int]] = {}
    for word_index, card_index in breaks.word_card.items():
        card_words.setdefault(card_index, []).append(word_index)

    glue: list[dict[str, float]] = []
    for card_index in range(len(cards) - 1):
        current = card_words.get(card_index)
        following = card_words.get(card_index + 1)
        if not current or not following:
            continue
        # Buraco no video CRU (o que existe na hora de gerar) x buraco que o usuario deixou.
        raw_gap_ms = (float(words[min(following)]["start"]) - float(words[max(current)]["end"])) * 1000
        user_gap_ms = (cards[card_index + 1].start - cards[card_index].end) * 1000
        glue.append({"raw_gap_ms": max(0.0, raw_gap_ms), "user_gap_ms": user_gap_ms})

    return {
        "lead_in_ms": lead_in_ms,
        "hold_ms": hold_ms,
        "glue": glue,
        "card_words": [sum(1 for raw in card.text.split() if normalize_token(raw)) for card in cards],
        "card_ms": [max(0.0, (card.end - card.start) * 1000) for card in cards],
    }
