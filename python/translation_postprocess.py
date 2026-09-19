import re
from typing import Any

DEFAULT_LOW_CONFIDENCE_THRESHOLD = -0.6


def _mentions_name(name: str, text: str) -> bool:
    """Checa se `name` aparece como PALAVRA INTEIRA em `text` (nao substring
    simples — "Ana" nao deveria "aparecer" dentro de "Anacleto")."""
    return re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE) is not None


def normalize_names(zh_text: str, glossary: dict[str, Any]) -> str:
    """Troca qualquer grafia nao-canonica de nome (latim deixado sem traduzir,
    ou variante conhecida em chines) pela grafia travada no glossario."""
    result = zh_text
    for character in glossary.get("characters", []):
        canonical = character["zh"]
        for variant in [character["source_name"], *character.get("variants", [])]:
            if variant and variant != canonical:
                result = result.replace(variant, canonical)
    return result


_SHE = "她"
_HE = "他"
_MARRIAGE_VERBS = ("嫁给", "娶")


def fix_gender_and_marriage_verb(zh_text: str, source_text: str, glossary: dict[str, Any]) -> str:
    """So mexe quando a frase fonte menciona EXATAMENTE UM personagem
    conhecido com genero definido — caso contrario nao arrisca (evita trocar
    errado numa frase com dois personagens de generos diferentes)."""
    mentioned = [
        c for c in glossary.get("characters", [])
        if c.get("gender") in ("male", "female") and _mentions_name(c["source_name"], source_text)
    ]
    if len(mentioned) != 1:
        return zh_text

    character = mentioned[0]
    result = zh_text

    if character["gender"] == "male" and _SHE in result and _HE not in result:
        result = result.replace(_SHE, _HE)
    elif character["gender"] == "female" and _HE in result and _SHE not in result:
        result = result.replace(_HE, _SHE)

    # Verbo de casamento direcional (娶/嫁给) exige saber quem e o sujeito E o
    # objeto — sem parser, e mais seguro trocar pelo neutro do que arriscar a
    # direcao errada.
    for verb in _MARRIAGE_VERBS:
        if verb in result:
            result = result.replace(verb, "结婚")

    return result


def confidence_flag(avg_logprob: float | None, threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD) -> str:
    if avg_logprob is None:
        return ""
    if avg_logprob < threshold:
        return f"transcricao de baixa confianca (avg_logprob={avg_logprob:.2f})"
    return ""
