import json
import re
from pathlib import Path
from typing import Any

# Nomes comuns em portugues que aparecem capitalizados mas NAO sao nome proprio de
# personagem — evita falso positivo no heuristico de extracao de nomes.
STOPWORDS_CAPITALIZADAS = {
    "Deus", "Nossa", "Senhor", "Youtube", "Instagram", "Tiktok", "Brasil",
}

DEFAULT_CHANNEL_GLOSSARY_PATH = "D:\\Projetos\\subtitle-forge\\glossario_canal.json"


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
        if name.lower() not in text.lower():
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
        name for name in known_by_name if any(name in text for text in cards_text)
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
