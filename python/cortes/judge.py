"""Juiz: o LLM local da nota 0-10 pra cada candidato ("aqui termina uma cena?").

A transcricao vai em janelas de 10 min (1 min de sobreposicao), uma chamada por janela.
O Python decide onde da pra cortar; o modelo so opina e a programacao dinamica garante as duracoes.
"""

from collections.abc import Callable
from typing import Any

from llm_service import LLMResponseError

from cortes.candidates import Candidate
from cortes.transcript import clock, transcript_lines

WINDOW_SEC = 600.0
OVERLAP_SEC = 60.0
ATTEMPT_TEMPERATURES = (0, 0.4, 0.7)

SYSTEM_PROMPT = (
    "Voce ajuda a cortar um react de filme em clipes para TikTok. A transcricao mistura as falas do filme "
    "(FILME) e os comentarios de quem reage (VOCE), com o tempo de cada linha. Marcadores como [C12] sao "
    "pontos onde o video pode ser cortado. Para CADA marcador, de uma nota inteira de 0 a 10 para a pergunta: "
    "'aqui termina uma cena e comeca outra?'. 10 = fim claro de cena (a conversa acabou, mudou o lugar ou o "
    "momento, uma revelacao terminou). 5 = pausa natural, mas o assunto continua. 0 = no meio de uma conversa "
    'ou acao. Responda so com JSON no formato {"notas": {"C12": 7, "C13": 2}}, com todos os marcadores '
    "pedidos e nenhum outro."
)


class JudgeResponseError(ValueError):
    """Resposta fora do formato; a mensagem vira o motivo da nova tentativa."""


def build_windows(
    start: float, end: float, window: float = WINDOW_SEC, overlap: float = OVERLAP_SEC
) -> list[tuple[float, float]]:
    windows = []
    window_start = start
    while True:
        window_end = min(window_start + window, end)
        windows.append((window_start, window_end))
        if window_end >= end:
            return windows
        window_start = window_end - overlap


def validate_scores(payload: Any, expected_ids: list[str]) -> dict[str, int]:
    notas = payload.get("notas") if isinstance(payload, dict) else None
    if not isinstance(notas, dict):
        raise JudgeResponseError('faltou o objeto "notas"')
    unknown = sorted(set(notas) - set(expected_ids))
    if unknown:
        raise JudgeResponseError(f"marcadores que nao existem nesta parte: {', '.join(unknown)}")
    missing = [marker for marker in expected_ids if marker not in notas]
    if missing:
        raise JudgeResponseError(f"faltou nota para: {', '.join(missing)}")
    scores = {}
    for key, value in notas.items():
        valid = (
            not isinstance(value, bool)
            and isinstance(value, int | float)
            and 0 <= value <= 10
            and value == int(value)
        )
        if not valid:
            raise JudgeResponseError(f"a nota de {key} precisa ser inteira de 0 a 10, veio {value!r}")
        scores[key] = int(value)
    return scores


def build_user_message(lines: list[str], ids: list[str]) -> str:
    return "Transcricao:\n" + "\n".join(lines) + "\n\nMarcadores para dar nota: " + ", ".join(ids)


def judge_window(client: Any, lines: list[str], ids: list[str]) -> dict[str, int]:
    user = build_user_message(lines, ids)
    last_error = ""
    for temperature in ATTEMPT_TEMPERATURES:
        message = user if not last_error else f"{user}\n\nSua resposta anterior foi rejeitada: {last_error}. Responda de novo no formato pedido."
        try:
            return validate_scores(client.chat_json(system=SYSTEM_PROMPT, user=message, temperature=temperature), ids)
        except (JudgeResponseError, LLMResponseError) as error:
            last_error = str(error)
    raise JudgeResponseError(last_error)


def judge_candidates(
    client: Any,
    film_segments: list[dict],
    mic_segments: list[dict],
    candidates: list[Candidate],
    start: float,
    end: float,
    on_window: Callable[[int, int], None] | None = None,
) -> list[str]:
    """Preenche candidate.judge (media das janelas que o viram). Devolve avisos das janelas que falharam.
    LLMUnavailableError (servidor caiu, modelo nao baixado) sobe pra quem chamou."""
    windows = build_windows(start, end)
    collected: dict[str, list[int]] = {}
    warnings = []
    for number, (window_start, window_end) in enumerate(windows, 1):
        inside = [candidate for candidate in candidates if window_start <= candidate.t <= window_end]
        if inside:
            lines = transcript_lines(film_segments, mic_segments, window_start, window_end, inside)
            try:
                scores = judge_window(client, lines, [candidate.id for candidate in inside])
            except JudgeResponseError as error:
                warnings.append(
                    f"Juiz falhou na janela {number} ({clock(window_start)}-{clock(window_end)}): {error}. "
                    "Ali valeu so a regra."
                )
            else:
                for key, value in scores.items():
                    collected.setdefault(key, []).append(value)
        if on_window:
            on_window(number, len(windows))
    for candidate in candidates:
        values = collected.get(candidate.id)
        candidate.judge = round(sum(values) / len(values), 2) if values else None
    return warnings
