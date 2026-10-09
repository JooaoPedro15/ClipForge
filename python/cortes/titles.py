"""Titulo curto e nota de gancho por clipe (LLM local) + nota final misturando a reacao no mic."""

from typing import Any

from llm_service import LLMResponseError

ATTEMPT_TEMPERATURES = (0, 0.4, 0.7)
TITLE_MAX_CHARS = 40
MAX_PROMPT_CHARS = 6000
HOOK_WEIGHT = 0.7

SYSTEM_PROMPT = (
    "Voce escreve titulos para clipes de TikTok cortados de um react de filme. A transcricao mistura as falas "
    "do filme (FILME) e os comentarios de quem reage (VOCE). Responda so com JSON no formato "
    '{"titulo": "...", "gancho": 7}. titulo: em portugues, ate 40 caracteres, sem aspas e sem hashtag, '
    "chamando atencao pro que acontece no clipe. gancho: inteiro de 0 a 10, o quanto o clipe prende quem esta "
    "rolando o feed (10 = prende muito)."
)


class TitleResponseError(ValueError):
    """Resposta fora do formato; a mensagem vira o motivo da nova tentativa."""


def validate_title(payload: Any) -> tuple[str, int]:
    if not isinstance(payload, dict):
        raise TitleResponseError("a resposta nao e um objeto JSON")
    title = str(payload.get("titulo", "")).strip().strip("\"'“”").strip()
    if not title:
        raise TitleResponseError("titulo vazio")
    if len(title) > TITLE_MAX_CHARS:
        raise TitleResponseError(f"titulo com {len(title)} caracteres (maximo {TITLE_MAX_CHARS})")
    hook = payload.get("gancho")
    valid = not isinstance(hook, bool) and isinstance(hook, int | float) and 0 <= hook <= 10 and hook == int(hook)
    if not valid:
        raise TitleResponseError(f"gancho precisa ser inteiro de 0 a 10, veio {hook!r}")
    return title, int(hook)


def title_clip(client: Any, lines: list[str]) -> tuple[str, int]:
    text = "\n".join(lines)
    if len(text) > MAX_PROMPT_CHARS:
        text = text[:MAX_PROMPT_CHARS] + "\n[...]"
    user = f"Transcricao do clipe:\n{text}"
    last_error = ""
    for temperature in ATTEMPT_TEMPERATURES:
        message = user if not last_error else f"{user}\n\nSua resposta anterior foi rejeitada: {last_error}. Responda de novo no formato pedido."
        try:
            return validate_title(client.chat_json(system=SYSTEM_PROMPT, user=message, temperature=temperature))
        except (TitleResponseError, LLMResponseError) as error:
            last_error = str(error)
    raise TitleResponseError(last_error)


def reaction_fraction(mic_speech: list[list[float]], start: float, end: float) -> float:
    if end <= start:
        return 0.0
    covered = sum(max(0.0, min(b, end) - max(a, start)) for a, b in mic_speech)
    return covered / (end - start)


def clip_scores(hooks: list[int | None], reactions: list[float]) -> list[float]:
    """Nota final 0-10: 70% gancho + 30% reacao (normalizada pelo clipe com mais reacao do react)."""
    peak = max(reactions, default=0.0)
    scores = []
    for hook, reaction in zip(hooks, reactions, strict=True):
        reaction10 = 10 * reaction / peak if peak > 0 else 0.0
        score = reaction10 if hook is None else HOOK_WEIGHT * hook + (1 - HOOK_WEIGHT) * reaction10
        scores.append(round(score, 1))
    return scores
