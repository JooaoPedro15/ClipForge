"""Conferencia de sentido da legenda em chines, pra quem nao le chines.

1. Retraducao "as cegas": o modelo traduz a legenda de volta pro portugues
   SEM ver a fala original — se visse, "corrigiria" a retraducao e o erro
   sumiria. A retraducao vai pra tela de revisao: o criador compara duas
   frases em portugues.
2. Checagem de negacao: se a fala tem negacao ("nao", "faltou", "nem"...) e
   a retraducao nao tem (ou o contrario), o sentido foi invertido — a linha
   volta pro modelo. Num teste com 10 linhas reais pegou 9 dos erros e nao
   deu nenhum alarme falso.

Um "juiz" LLM comparando as duas frases foi testado e descartado: no 14B
local errou 3 em 10 (reprovava linha boa com motivo inventado) e levava
~40s por linha.
"""

import json
import re
from typing import Any

import llm_prompts

# "faltou X fazer" = X ainda NAO fez: conta como negacao pra comparacao.
_NEGATION_RE = re.compile(
    r"\b(n[aã]o|nunca|nem|nenhum|nenhuma|ningu[eé]m|nada|jamais|sem|falt(?:ou|a|ava|ar|aram))\b",
    re.IGNORECASE,
)


def _negations(text: str) -> list[str]:
    return [m.group(0).lower() for m in _NEGATION_RE.finditer(text)]


def negation_mismatch(source_pt: str, back_pt: str) -> str:
    """Vazio se as duas frases concordam em ter (ou nao ter) negacao; senao
    uma explicacao curta em portugues."""
    source_neg = _negations(source_pt)
    back_neg = _negations(back_pt)
    if source_neg and not back_neg:
        return f"a fala tem negação ('{source_neg[0]}') e a legenda não"
    if back_neg and not source_neg:
        return f"a legenda tem negação ('{back_neg[0]}') que a fala não tem"
    return ""


def back_translate(zh: str, sheet: dict[str, Any], client: Any) -> str:
    """Retraducao literal zh -> pt-BR. Recebe so o chines e o mapa de nomes.
    Qualquer falha devolve "" — a conferencia e um extra e nunca derruba a
    traducao."""
    names = {c["zh"]: c["source_name"] for c in sheet.get("characters", []) if c.get("zh") and c.get("source_name")}
    user = json.dumps({"names": names, "zh": zh}, ensure_ascii=False)
    try:
        raw = client.chat_json(system=llm_prompts.PROMPT_RETRADUCAO, user=user, temperature=0)
    except Exception:
        return ""
    if not isinstance(raw, dict):
        return ""
    return str(raw.get("pt", "") or "").strip()
