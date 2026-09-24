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
Frase que sai longa demais e dividida em quantas linhas forem precisas na
pontuacao chinesa, com o tempo repartido em fronteira de card.
"""

from typing import Any

import glossary_service
import llm_prompts
import subtitle_validation
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
# O modelo as vezes fecha a linha com virgula/ponto ASCII — em chines isso
# nao existe: virgula e ponto viram a forma de largura inteira, o resto cai.
_LATIN_TO_ZH_PUNCTUATION = {",": "，", ".": "。", ";": "；", "?": "？", "!": "！", ":": "："}
# Conectivos de abertura: o modelo de 7B abre quase toda linha com o mesmo
# ("结果..., 结果..., 结果..."), o que le pessimo numa sequencia de legendas.
# Repetir o conectivo da linha anterior faz a resposta voltar pro modelo; se
# ele insistir, o conectivo e simplesmente removido (o sentido nao depende
# dele, e a linha ainda encurta).
_OPENING_CONNECTIVES = ("结果", "然后", "接着", "于是", "后来", "但是", "不过", "而且", "所以")


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


def _opening_connective(zh: str) -> str:
    for connective in _OPENING_CONNECTIVES:
        if zh.startswith(connective):
            return connective
    return ""


def _drop_opening_connective(zh: str) -> str:
    connective = _opening_connective(zh)
    rest = zh[len(connective) :].lstrip(_ZH_TRAILING_MARKS) if connective else zh
    return rest or zh


def _fit_line(zh: str, bucket: list[dict[str, Any]], max_chars: int, min_duration: float) -> list[tuple[list, str]] | None:
    """Encaixa a linha no limite: cabe inteira -> 1 parte; longa mas divisivel
    na pontuacao, com cada pedaco dentro do limite E com tempo de leitura ->
    N partes; senao None (o chamador pede uma linha mais curta)."""
    lines = split_line_into_parts(zh, max_chars)
    if lines is None:
        return None
    if len(lines) == 1:
        return [(bucket, lines[0])]
    buckets = split_cards_into_parts(bucket, [len(line) for line in lines], min_duration)
    if buckets is None:
        return None
    return list(zip(buckets, lines))


def _translate_sentence(
    target: dict[str, Any],
    payload: list[dict[str, Any]],
    previous_lines: list[dict[str, Any]],
    sheet: dict[str, Any],
    client: Any,
    bucket: list[dict[str, Any]],
    max_chars: int,
    min_duration: float,
    previous_connective: str = "",
) -> tuple[dict[str, Any], list[tuple[list, str]]]:
    """Traduz UMA frase. Devolve (linha do modelo, partes [(cards, zh)]).
    Resposta rejeitada (id errado, vazia, latim, longa demais sem divisao
    possivel, conectivo repetido) volta pro modelo com o motivo e um pouco
    de temperatura."""
    system, user = llm_prompts.build_translation_messages(payload, sheet, target, previous_lines, max_chars=max_chars)
    last_error = "sem resposta"
    line = None
    candidates: list[tuple[dict[str, Any], str]] = []
    for temperature in ATTEMPT_TEMPERATURES:
        line = _normalize_line(client.chat_json(system=system, user=user, temperature=temperature))
        if line is None:
            last_error = "resposta nao e um objeto JSON"
        elif line["id"] not in (None, target["id"]):
            last_error = f"modelo respondeu a frase {line['id']} em vez da {target['id']}"
        elif not line["zh"]:
            last_error = "zh vazio"
        else:
            zh = normalize_punctuation(translation_postprocess.normalize_names(line["zh"], sheet))
            zh = _strip(zh)
            repeats_connective = bool(previous_connective) and _opening_connective(zh) == previous_connective
            swap = subtitle_validation.character_swap_error(zh, target["text"], sheet)
            marriage = subtitle_validation.marriage_object_error(zh, sheet)
            parts = _fit_line(zh, bucket, max_chars, min_duration)
            if parts is not None and not _has_latin(zh) and not repeats_connective and not swap and not marriage:
                return line, parts
            # Guarda a tentativa: se nenhuma sair limpa, a melhor delas ainda
            # e entregue (a validacao reprova apontando o grupo, ou o
            # conectivo repetido cai fora no final).
            candidates.append((line, zh))
            if _has_latin(zh):
                # Nome (ou palavra solta) que ficou em latim: o modelo tem a
                # grafia no glossario, so precisa ser lembrado.
                last_error = f"Latin script left in zh ('{zh}'); use only Chinese characters, names from the reference sheet"
            elif swap:
                last_error = f"{swap}; translate the sentence you were given, keeping its own characters"
            elif marriage:
                last_error = (
                    f"{marriage}. 嫁给 only takes a male object and 娶 only a female object; "
                    f"for two people of the same gender write A和B结婚"
                )
            elif parts is None:
                last_error = f"zh is {len(zh)} characters ('{zh}'); rewrite it in at most {max_chars} characters, drop filler words"
            else:
                last_error = (
                    f"the previous line already opens with '{previous_connective}'; "
                    f"write this one with a different connective or none at all"
                )
        user = (
            user
            + "\n\n## Previous attempt was rejected\n\n"
            + f"{last_error}. Return one JSON object for sentence id {target['id']} with a non-empty zh."
        )
    if candidates:
        # Personagem trocado e o pior defeito (a legenda conta outra historia);
        # depois letra latina, depois linha longa demais, so entao o tamanho.
        line, zh = min(
            candidates,
            key=lambda c: (
                bool(subtitle_validation.character_swap_error(c[1], target["text"], sheet)),
                _has_latin(c[1]),
                bool(subtitle_validation.marriage_object_error(c[1], sheet)),
                _fit_line(c[1], bucket, max_chars, min_duration) is None,
                len(c[1]),
            ),
        )
        if previous_connective and _opening_connective(zh) == previous_connective:
            # O modelo insistiu no mesmo conectivo: tira ele e reencaixa.
            zh = _drop_opening_connective(zh)
        return line, _fit_line(zh, bucket, max_chars, min_duration) or [(bucket, zh)]
    raise LLMTranslationError(f"estagio 2: {last_error} (frase {target['id']}: '{target['text']}')")


def split_line_into_parts(zh: str, max_chars: int) -> list[str] | None:
    """Divide a linha em quantas partes forem precisas pra caber no limite,
    sempre na pontuacao chinesa, usando o MENOR numero de linhas possivel —
    uma virgula nao vira automaticamente quebra de linha, oracoes curtas
    seguidas ficam na mesma legenda enquanto couberem.
    None quando um pedaco sozinho ja estoura o limite — nao ha onde cortar
    sem partir a oracao, entao o chamador pede uma traducao mais curta."""
    chunks = []
    current = ""
    for char in zh:
        current += char
        if char in _ZH_SPLIT_MARKS:
            chunks.append(current)
            current = ""
    if current:
        chunks.append(current)

    parts: list[str] = []
    line = ""
    for chunk in chunks:
        stripped = chunk.strip(_ZH_TRAILING_MARKS)
        if len(stripped) > max_chars:
            return None
        if len(_strip(line + chunk)) <= max_chars:
            line += chunk
            continue
        if line:
            parts.append(_strip(line))
        line = chunk
    if _strip(line):
        parts.append(_strip(line))
    return parts or None


def _strip(text: str) -> str:
    return text.strip(_ZH_TRAILING_MARKS)


def normalize_punctuation(zh: str) -> str:
    """Troca pontuacao latina pela equivalente de largura inteira e remove a
    que nao tem equivalente (aspas, parenteses)."""
    result = []
    for char in zh:
        if char in _LATIN_TO_ZH_PUNCTUATION:
            result.append(_LATIN_TO_ZH_PUNCTUATION[char])
        elif char in "\"'()[]":
            continue
        else:
            result.append(char)
    return "".join(result)


def split_cards_into_parts(
    bucket: list[dict[str, Any]],
    line_lengths: list[int],
    min_duration: float,
) -> list[list[dict[str, Any]]] | None:
    """Reparte os cards da frase em len(line_lengths) blocos, cortando nas
    fronteiras de card mais proximas da proporcao de cada linha. None quando
    nao ha cards suficientes ou algum bloco ficaria curto demais pra ler."""
    if len(bucket) < len(line_lengths):
        return None
    total_chars = sum(line_lengths)
    total_time = bucket[-1]["end"] - bucket[0]["start"]
    if total_chars <= 0 or total_time <= 0:
        return None

    cuts: list[int] = []
    accumulated = 0
    for length in line_lengths[:-1]:
        accumulated += length
        target = bucket[0]["start"] + total_time * (accumulated / total_chars)
        # Cada bloco precisa de pelo menos 1 card, entao o corte k fica entre
        # o corte anterior + 1 e "sobra um card pra cada bloco seguinte".
        lower = (cuts[-1] if cuts else 0) + 1
        parts_after = len(line_lengths) - len(cuts) - 1
        highest = len(bucket) - parts_after
        if lower > highest:
            return None
        cuts.append(min(range(lower, highest + 1), key=lambda k: abs(bucket[k]["start"] - target)))

    parts = []
    previous = 0
    for cut in [*cuts, len(bucket)]:
        parts.append(bucket[previous:cut])
        previous = cut
    if any(_duration(part) < min_duration for part in parts):
        return None
    return parts


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
    previous_connective = ""
    for sentence, target in zip(sentences, payload):
        bucket = [by_index[i] for i in sentence["cards"]]
        line, parts = _translate_sentence(
            target, payload, previous_lines, sheet, client, bucket, max_chars, min_duration, previous_connective
        )
        previous_connective = _opening_connective(parts[0][1])
        previous_lines.append({"id": sentence["id"], "zh": "".join(zh for _, zh in parts)})
        for part_bucket, zh in parts:
            groups.append(_build_group(part_bucket, zh, line["flag"]))

    for group in groups:
        if not group["flag"]:
            group["flag"] = translation_postprocess.confidence_flag(group.get("avg_logprob"))
    return groups
