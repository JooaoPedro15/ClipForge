import json
import re
from pathlib import Path
from typing import Any

import llm_prompts

# Nomes comuns em portugues que aparecem capitalizados mas NAO sao nome proprio de
# personagem — evita falso positivo no heuristico de extracao de nomes.
STOPWORDS_CAPITALIZADAS = {
    "Deus", "Nossa", "Senhor", "Youtube", "Instagram", "Tiktok", "Brasil",
}

DEFAULT_CHANNEL_GLOSSARY_PATH = "D:\\Projetos\\subtitle-forge\\glossario_canal.json"


def _mentions_name(name: str, text: str) -> bool:
    """Checa se `name` aparece como PALAVRA INTEIRA em `text` (nao substring).
    Substring simples (`name in text`) dava falso positivo: um nome curto
    conhecido tipo "Ana" "aparecia" dentro de "Anacleto", um personagem
    diferente que so por acaso comeca com as mesmas letras."""
    return re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE) is not None


def extract_candidate_names(cards_text: list[str]) -> set[str]:
    """Extrai nomes proprios candidatos via heuristica: palavra capitalizada,
    que aparece em posicao NAO-inicial de pelo menos um card (pra nao pegar
    inicio de frase capitalizado por convencao), com frequencia total >= 2."""
    counts: dict[str, int] = {}
    non_initial: set[str] = set()

    for text in cards_text:
        words = text.split()
        for index, word in enumerate(words):
            cleaned = re.sub(r"[^\w]", "", word)
            if not cleaned or not cleaned[0].isupper() or cleaned.upper() == cleaned:
                continue
            if cleaned in STOPWORDS_CAPITALIZADAS:
                continue
            counts[cleaned] = counts.get(cleaned, 0) + 1
            if index > 0:
                non_initial.add(cleaned)

    return {name for name, count in counts.items() if count >= 2 and name in non_initial}


_MALE_SIGNALS = re.compile(r"\b(o|ele|dele|rejeitado|sozinho|irmao|filho|tio)\b", re.IGNORECASE)
_FEMALE_SIGNALS = re.compile(r"\b(a|ela|dela|rejeitada|sozinha|irma|filha|tia)\b", re.IGNORECASE)


def infer_gender(name: str, cards_text: list[str]) -> str:
    """Procura sinais gramaticais (artigo, pronome, concordancia de particípio)
    perto de cada mencao do nome. Heuristica simples — nao entende contexto,
    so conta sinais nas frases onde o nome aparece."""
    male_score = 0
    female_score = 0

    for text in cards_text:
        if not _mentions_name(name, text):
            continue
        male_score += len(_MALE_SIGNALS.findall(text))
        female_score += len(_FEMALE_SIGNALS.findall(text))

    if male_score > female_score:
        return "male"
    if female_score > male_score:
        return "female"
    return "unknown"


def load_channel_glossary(path: str = DEFAULT_CHANNEL_GLOSSARY_PATH) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"characters": [], "terms": []}


def merge_into_channel_glossary(video_glossary: dict[str, Any], path: str = DEFAULT_CHANNEL_GLOSSARY_PATH) -> dict[str, Any]:
    """Funde o glossario deste video no do canal. Entrada ja existente NUNCA e
    sobrescrita — e isso que garante o mesmo nome saindo igual em todo video."""
    canal = load_channel_glossary(path)
    for chave, id_ in (("characters", "source_name"), ("terms", "source")):
        existentes = {e[id_] for e in canal.get(chave, [])}
        for entrada in video_glossary.get(chave, []):
            if entrada[id_] not in existentes:
                canal.setdefault(chave, []).append(entrada)
                existentes.add(entrada[id_])

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(canal, ensure_ascii=False, indent=2), encoding="utf-8")
    return canal


def build_video_glossary(
    cards_text: list[str],
    channel_glossary: dict[str, Any],
    translator: Any,
    source_lang: str,
    target_lang: str,
) -> dict[str, Any]:
    """Monta o glossario deste video: reusa grafia ja travada no glossario do
    canal quando existe; pra nome novo, traduz o nome ISOLADO (nao a frase)
    uma unica vez via NLLB e trava esse resultado como canonico pro resto do
    video (chamadas repetidas do NLLB pro mesmo texto isolado sao
    deterministicas, entao travar na primeira vez garante consistencia)."""
    known_by_name = {c["source_name"]: c for c in channel_glossary.get("characters", [])}
    # Nome novo precisa da frequencia >=2 do heuristico pra nao dar falso
    # positivo. Nome JA conhecido do glossario do canal e diferente: ja foi
    # vetado em vídeo anterior, entao basta aparecer uma vez neste video pra
    # ser reaproveitado (senao um personagem recorrente que so e citado uma
    # vez neste video especifico ficaria de fora da lista).
    candidates = extract_candidate_names(cards_text) | {
        name for name in known_by_name if any(_mentions_name(name, text) for text in cards_text)
    }

    characters: list[dict[str, Any]] = []
    names_to_translate = [name for name in candidates if name not in known_by_name]

    translated_lookup: dict[str, str] = {}
    if names_to_translate:
        translated = translator.translate_segments(names_to_translate, source_lang=source_lang, target_lang=target_lang)
        translated_lookup = dict(zip(names_to_translate, translated))

    for name in candidates:
        if name in known_by_name:
            entry = dict(known_by_name[name])
        else:
            entry = {
                "source_name": name,
                "variants": [],
                "zh": translated_lookup[name],
                "gender": infer_gender(name, cards_text),
            }
        characters.append(entry)

    return {"characters": characters, "terms": []}


# Whisper: avg_logprob abaixo disso = segmento reconhecido com pouca confianca.
# O card vai pro LLM marcado como low_confidence pra ele NAO preencher buraco
# com texto inventado (origem provavel da alucinacao "REJEITADO" -> frase
# fluente sem relacao com a fonte).
LOW_CONFIDENCE_THRESHOLD = -0.6


def cards_to_llm_transcript(cards: list[dict[str, Any]], threshold: float = LOW_CONFIDENCE_THRESHOLD) -> list[dict[str, Any]]:
    """Reduz os cards ao que o modelo precisa ver (sem segment_id) e marca os
    de baixa confianca em vez de manda-los como texto normal."""
    transcript = []
    for card in cards:
        logprob = card.get("avg_logprob")
        transcript.append(
            {
                "i": card["i"],
                "start": card["start"],
                "end": card["end"],
                "text": card["text"],
                "low_confidence": logprob is not None and logprob < threshold,
            }
        )
    return transcript


def _normalize_character(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_name": str(entry.get("source_name", "")).strip(),
        "variants": [str(v) for v in entry.get("variants", []) or []],
        "zh": str(entry.get("zh", "")).strip(),
        "gender": entry.get("gender") if entry.get("gender") in ("male", "female") else "unknown",
        "relations": str(entry.get("relations", "unknown") or "unknown"),
        "note": str(entry.get("note", "") or ""),
    }


def build_video_glossary_llm(
    cards: list[dict[str, Any]],
    channel_glossary: dict[str, Any],
    video_type: str,
    client: Any,
) -> dict[str, Any]:
    """Estagio 1 via LLM local: manda a transcricao INTEIRA + glossario do canal
    (travado) + tipo de video, e recebe a "reference sheet" que alimenta o
    estagio 2. Grafia/genero ja presentes no glossario do canal sobrescrevem
    o que o modelo devolveu — a consistencia entre videos vem daqui, nao da
    obediencia do modelo ao prompt."""
    transcript = cards_to_llm_transcript(cards)
    system, user = llm_prompts.build_glossary_messages(transcript, video_type, channel_glossary)
    raw = client.chat_json(system=system, user=user)
    if not isinstance(raw, dict):
        raw = {}

    cards_text = [c["text"] for c in cards]
    locked_characters = {c["source_name"]: c for c in channel_glossary.get("characters", [])}
    locked_terms = {t["source"]: t for t in channel_glossary.get("terms", [])}

    characters: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw.get("characters", []) or []:
        character = _normalize_character(entry)
        if not character["source_name"] or character["source_name"] in seen:
            continue
        locked = locked_characters.get(character["source_name"])
        if locked:
            # Entrada travada: grafia e genero vem do canal, o resto (relacoes,
            # nota, variantes vistas neste video) pode vir do modelo.
            character["zh"] = locked["zh"]
            character["gender"] = locked.get("gender", character["gender"])
            character["variants"] = sorted(set(character["variants"]) | set(locked.get("variants", [])))
        seen.add(character["source_name"])
        characters.append(character)

    # Personagem recorrente do canal citado neste video mas omitido pelo modelo
    # entra mesmo assim — senao o estagio 2 nao teria a grafia travada dele.
    for name, locked in locked_characters.items():
        if name not in seen and any(_mentions_name(name, text) for text in cards_text):
            characters.append(_normalize_character(locked))
            seen.add(name)

    terms: list[dict[str, Any]] = []
    for entry in raw.get("terms", []) or []:
        source = str(entry.get("source", "")).strip()
        if not source:
            continue
        term = {"source": source, "zh": str(entry.get("zh", "")).strip(), "note": str(entry.get("note", "") or "")}
        if source in locked_terms:
            term["zh"] = locked_terms[source]["zh"]
        terms.append(term)

    unclear: list[int] = []
    for value in raw.get("unclear", []) or []:
        try:
            unclear.append(int(value))
        except (TypeError, ValueError):
            continue

    return {
        "summary": str(raw.get("summary", "") or ""),
        "characters": characters,
        "terms": terms,
        "register": str(raw.get("register", "") or ""),
        "unclear": sorted(set(unclear)),
    }
