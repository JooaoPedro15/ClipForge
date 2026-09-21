"""Estagio 2: traducao por frase via LLM local.

Recebe a transcricao inteira (cards) + a reference sheet do estagio 1 e
devolve UM grupo por frase: {"cards": [...], "start", "end", "zh", "flag",
"text"}. O SRT final e montado a partir desses grupos, nao dos cards.

Divisao de trabalho: o Python propoe as fronteiras de frase (pontuacao que o
Whisper ja poe nos cards + limites de duracao/palavras) e o modelo traduz
UMA frase por chamada, vendo a transcricao inteira e as linhas anteriores
ja traduzidas. Deixar o modelo agrupar/traduzir tudo de uma vez nao
funcionou com modelo local de 7B: ou resumia o video numa linha so, ou
traduzia o fluxo e redistribuia o conteudo deslocado entre as frases
(timing errado). Uma frase por chamada trava o alinhamento; o prefixo fixo
(sheet + transcricao) fica em cache no Ollama, entao custa ~1s por frase.
Frase que sai longa demais e dividida em duas linhas na pontuacao chinesa,
com o tempo repartido em fronteira de card.
"""

from typing import Any

import glossary_service
import llm_prompts
import translation_postprocess

# Temperatura por tentativa: a 1a e deterministica; as seguintes recebem o
# erro de volta E um pouco de temperatura, senao o modelo repete a resposta.
ATTEMPT_TEMPERATURES = (0, 0.4, 0.7)

# Limites da proposta de frase (ver propose_sentences).
MIN_WORDS_BEFORE_COMMA_BREAK = 5
MAX_WORDS_PER_SENTENCE = 14
MAX_SENTENCE_DURATION = 6.0
# Frase mais curta que isso na tela nao da tempo de ler — funde com a vizinha.
MIN_SENTENCE_DURATION = 1.2

_HARD_STOPS = (".", "?", "!", "…")
_SOFT_STOPS = (",", ";", ":")
# Card que comeca com uma dessas palavras continua a oracao anterior ("vai ver
# o tumulo" + "do Bernardo"). Fechar frase antes dele deixa um pedaco sem
# sentido pro modelo — que ai inventa ("伯纳多死了").
_CONTINUATION_WORDS = {
    "de", "do", "da", "dos", "das", "com", "que", "pra", "pro", "para", "em", "no", "na",
    "nos", "nas", "sem", "por", "pelo", "pela", "ao", "aos", "à", "às",
}
# Card que TERMINA (sem pontuacao) numa dessas palavras esta no meio da oracao
# ("do Bernardo, não" + "tô entendendo"): tambem nao fecha frase ali.
_DANGLING_WORDS = _CONTINUATION_WORDS | {
    "não", "e", "ou", "mas", "o", "a", "os", "as", "um", "uma", "se", "já", "todo", "toda",
    "meu", "minha", "seu", "sua", "esse", "essa", "este", "esta", "aquele", "aquela",
    "muito", "mais", "tão", "tá", "vai", "foi", "é",
}
# Sem pontuacao nem ponto de corte limpo, a frase pode crescer ate este teto
# (a linha em chines longa demais e dividida em duas depois).
HARD_MAX_WORDS_PER_SENTENCE = 24
_ZH_SPLIT_MARKS = "，。？！；"
_ZH_TRAILING_MARKS = "，。；"


class LLMTranslationError(RuntimeError):
    """Saida do modelo nao cobre as frases mesmo depois de uma nova tentativa."""


def _words(bucket: list[dict[str, Any]]) -> int:
    return sum(len(c["text"].split()) for c in bucket)


def _duration(bucket: list[dict[str, Any]]) -> float:
    return bucket[-1]["end"] - bucket[0]["start"]


def _make_sentence(sentence_id: int, bucket: list[dict[str, Any]]) -> dict[str, Any]:
    confidences = [c["avg_logprob"] for c in bucket if c.get("avg_logprob") is not None]
    return {
        "id": sentence_id,
        "cards": [c["i"] for c in bucket],
        "start": bucket[0]["start"],
        "end": bucket[-1]["end"],
        "text": " ".join(c["text"].strip() for c in bucket),
        "avg_logprob": min(confidences) if confidences else None,
    }


def propose_sentences(
    cards: list[dict[str, Any]],
    min_words: int = MIN_WORDS_BEFORE_COMMA_BREAK,
    max_words: int = MAX_WORDS_PER_SENTENCE,
    max_duration: float = MAX_SENTENCE_DURATION,
    min_duration: float = MIN_SENTENCE_DURATION,
) -> list[dict[str, Any]]:
    """Agrupa cards consecutivos em frases usando a pontuacao do Whisper:
    ponto/interrogacao fecham sempre; virgula fecha quando ja ha palavras
    suficientes (senao "e aí o Edgar," viraria linha sozinha). Estourando
    o teto de palavras/duracao, corta na ultima virgula do bloco em vez de
    no meio da oracao."""
    sentences: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    last_soft_break = -1  # posicao (em current) do ultimo card terminado em virgula

    def flush(bucket: list[dict[str, Any]]) -> None:
        if bucket:
            sentences.append(_make_sentence(len(sentences), bucket))

    def continues_next(position: int) -> bool:
        if position + 1 >= len(cards):
            return False
        first_word = cards[position + 1]["text"].strip().split(" ")[0].lower()
        return first_word in _CONTINUATION_WORDS

    def dangles(text: str) -> bool:
        last_word = text.split(" ")[-1].lower() if text else ""
        return last_word in _DANGLING_WORDS

    for position, card in enumerate(cards):
        current.append(card)
        text = card["text"].strip()
        if text.endswith(_HARD_STOPS):
            flush(current)
            current, last_soft_break = [], -1
            continue
        if text.endswith(_SOFT_STOPS):
            if _words(current) >= min_words and not continues_next(position):
                flush(current)
                current, last_soft_break = [], -1
                continue
            last_soft_break = len(current) - 1
            continue
        if _words(current) >= max_words or _duration(current) >= max_duration:
            clean_cut = not continues_next(position) and not dangles(text)
            if 0 <= last_soft_break < len(current) - 1:
                flush(current[: last_soft_break + 1])
                current = current[last_soft_break + 1 :]
            elif clean_cut or _words(current) >= HARD_MAX_WORDS_PER_SENTENCE:
                flush(current)
                current = []
            last_soft_break = -1
    flush(current)
    return _merge_short_sentences(sentences, cards, min_duration)


def _merge_short_sentences(
    sentences: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    min_duration: float,
) -> list[dict[str, Any]]:
    """Frase abaixo do tempo minimo de leitura e fundida com a vizinha mais
    curta (em palavras), pra nao estourar o teto da vizinha a toa. Repete
    ate nao sobrar frase curta ou nao ter mais com quem fundir."""
    by_index = {c["i"]: c for c in cards}
    buckets = [[by_index[i] for i in s["cards"]] for s in sentences]
    changed = True
    while changed and len(buckets) > 1:
        changed = False
        for k, bucket in enumerate(buckets):
            if _duration(bucket) >= min_duration:
                continue
            neighbours = [j for j in (k - 1, k + 1) if 0 <= j < len(buckets)]
            j = min(neighbours, key=lambda j: _words(buckets[j]))
            lo, hi = sorted((j, k))
            buckets[lo : hi + 1] = [buckets[lo] + buckets[hi]]
            changed = True
            break
    return [_make_sentence(n, b) for n, b in enumerate(buckets)]


def _normalize_line(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    # Tolera o modelo devolver {"lines": [{...}]} em vez do objeto direto.
    if "zh" not in raw and isinstance(raw.get("lines"), list) and raw["lines"]:
        raw = raw["lines"][0]
    if not isinstance(raw, dict):
        return None
    try:
        sentence_id = int(raw.get("id"))
    except (TypeError, ValueError):
        sentence_id = None
    return {
        "id": sentence_id,
        "zh": str(raw.get("zh", "") or "").strip(),
        "flag": str(raw.get("flag", "") or "").strip(),
    }


def _has_latin(text: str) -> bool:
    return any("a" <= ch.lower() <= "z" for ch in text)


def _fit_line(zh: str, bucket: list[dict[str, Any]], max_chars: int, min_duration: float) -> list[tuple[list, str]] | None:
    """Encaixa a linha no limite: cabe inteira -> 1 parte; longa mas divisivel
    na pontuacao com as duas metades no limite E cada metade com tempo de
    leitura -> 2 partes; senao None (o chamador pede uma linha mais curta)."""
    if len(zh) <= max_chars:
        return [(bucket, zh)]
    halves = _split_long_line(zh, max_chars)
    if not halves:
        return None
    parts = _split_cards_proportionally(bucket, len(halves[0]) / len(zh))
    if not parts or not all(_duration(p) >= min_duration for p in parts):
        return None
    return [(parts[0], halves[0]), (parts[1], halves[1])]


def _translate_sentence(
    target: dict[str, Any],
    payload: list[dict[str, Any]],
    previous_lines: list[dict[str, Any]],
    sheet: dict[str, Any],
    client: Any,
    bucket: list[dict[str, Any]],
    max_chars: int,
    min_duration: float,
) -> tuple[dict[str, Any], list[tuple[list, str]]]:
    """Traduz UMA frase. Devolve (linha do modelo, partes [(cards, zh)]).
    Resposta rejeitada (id errado, vazia, latim, longa demais sem divisao
    possivel) volta pro modelo com o motivo e um pouco de temperatura."""
    system, user = llm_prompts.build_translation_messages(payload, sheet, target, previous_lines, max_chars=max_chars)
    last_error = "sem resposta"
    line = None
    fallback: tuple[dict[str, Any], list[tuple[list, str]]] | None = None
    for temperature in ATTEMPT_TEMPERATURES:
        line = _normalize_line(client.chat_json(system=system, user=user, temperature=temperature))
        if line is None:
            last_error = "resposta nao e um objeto JSON"
        elif line["id"] not in (None, target["id"]):
            last_error = f"modelo respondeu a frase {line['id']} em vez da {target['id']}"
        elif not line["zh"]:
            last_error = "zh vazio"
        else:
            zh = translation_postprocess.normalize_names(line["zh"], sheet).strip(_ZH_TRAILING_MARKS)
            parts = _fit_line(zh, bucket, max_chars, min_duration)
            if parts is not None and not _has_latin(zh):
                return line, parts
            # Entrega utilizavel (a validacao vai reprovar apontando o grupo),
            # guardada caso as tentativas seguintes nao melhorem.
            if fallback is None or len(zh) < len(fallback[1][0][1]):
                fallback = (line, [(bucket, zh)])
            if _has_latin(zh):
                # Nome (ou palavra solta) que ficou em latim: o modelo tem a
                # grafia no glossario, so precisa ser lembrado.
                last_error = f"Latin script left in zh ('{zh}'); use only Chinese characters, names from the reference sheet"
            else:
                last_error = f"zh is {len(zh)} characters ('{zh}'); rewrite it in at most {max_chars} characters, drop filler words"
        user = (
            user
            + "\n\n## Previous attempt was rejected\n\n"
            + f"{last_error}. Return one JSON object for sentence id {target['id']} with a non-empty zh."
        )
    if fallback is not None:
        return fallback
    raise LLMTranslationError(f"estagio 2: {last_error} (frase {target['id']}: '{target['text']}')")


def _split_long_line(zh: str, max_chars: int) -> list[str] | None:
    """Divide uma linha longa em duas na pontuacao chinesa mais proxima do
    meio. None se nao houver ponto de corte que deixe as duas metades no
    limite — ai a validacao reprova, o que e o comportamento desejado."""
    candidates = [i for i, ch in enumerate(zh) if ch in _ZH_SPLIT_MARKS and 0 < i < len(zh) - 1]
    if not candidates:
        return None
    middle = len(zh) / 2
    for cut in sorted(candidates, key=lambda i: abs(i - middle)):
        left, right = zh[: cut + 1].strip(_ZH_TRAILING_MARKS), zh[cut + 1 :].strip(_ZH_TRAILING_MARKS)
        if left and right and len(left) <= max_chars and len(right) <= max_chars:
            return [left, right]
    return None


def _split_cards_proportionally(bucket: list[dict[str, Any]], ratio: float) -> tuple[list, list] | None:
    """Reparte os cards da frase em dois blocos na fronteira de card mais
    proxima da proporcao `ratio` (tamanho da 1a linha / total)."""
    if len(bucket) < 2:
        return None
    total = bucket[-1]["end"] - bucket[0]["start"]
    if total <= 0:
        return None
    target = bucket[0]["start"] + total * ratio
    best = min(range(1, len(bucket)), key=lambda k: abs(bucket[k]["start"] - target))
    return bucket[:best], bucket[best:]


def _build_group(bucket: list[dict[str, Any]], zh: str, flag: str) -> dict[str, Any]:
    sentence = _make_sentence(0, bucket)
    return {
        "cards": sentence["cards"],
        "start": sentence["start"],
        "end": sentence["end"],
        "text": sentence["text"],
        "zh": zh,
        "flag": flag,
        "avg_logprob": sentence["avg_logprob"],
    }


def translate_with_llm(
    cards: list[dict[str, Any]],
    sheet: dict[str, Any],
    client: Any,
    max_chars: int = 20,
    min_duration: float = MIN_SENTENCE_DURATION,
) -> list[dict[str, Any]]:
    by_index = {c["i"]: c for c in cards}
    sentences = propose_sentences(cards, min_duration=min_duration)
    unclear = set(sheet.get("unclear", []))

    payload = []
    for sentence in sentences:
        low = sentence["avg_logprob"] is not None and sentence["avg_logprob"] < glossary_service.LOW_CONFIDENCE_THRESHOLD
        low = low or any(i in unclear for i in sentence["cards"])
        payload.append(
            {
                "id": sentence["id"],
                "start": sentence["start"],
                "end": sentence["end"],
                "text": sentence["text"],
                "low_confidence": low,
            }
        )

    groups: list[dict[str, Any]] = []
    previous_lines: list[dict[str, Any]] = []
    for sentence, target in zip(sentences, payload):
        bucket = [by_index[i] for i in sentence["cards"]]
        line, parts = _translate_sentence(target, payload, previous_lines, sheet, client, bucket, max_chars, min_duration)
        previous_lines.append({"id": sentence["id"], "zh": "".join(zh for _, zh in parts)})
        for part_bucket, zh in parts:
            groups.append(_build_group(part_bucket, zh, line["flag"]))

    for group in groups:
        if not group["flag"]:
            group["flag"] = translation_postprocess.confidence_flag(group.get("avg_logprob"))
    return groups
