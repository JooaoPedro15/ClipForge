"""Nota 0-10 da IA local pra cada frase: quanto ela segura quem assiste (a pergunta muda por formato).

Mesmo padrao do juiz dos Cortes: transcricao em janelas de 10 min com 1 min de sobreposicao, marcador por
frase, resposta JSON e nova tentativa com temperatura maior quando a resposta vem fora do formato.
"""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from llm_service import LLMResponseError, LLMUnavailableError

from preedit.phrases import Phrase

# Janelas de 5 min: com um marcador por frase, 10 min de fala rapida chegam perto do contexto do modelo (8192).
WINDOW_SEC = 300.0
OVERLAP_SEC = 30.0
NEUTRAL = 5.0
ATTEMPT_TEMPERATURES = (0, 0.4, 0.7)
# Aceita a resposta se pelo menos essa parte dos marcadores veio com nota valida.
MIN_ANSWERED = 0.8

_ANSWER = (
    " Cada linha e uma frase com um marcador como [F12] e o tempo. Para CADA marcador, de uma nota inteira de 0 a 10."
    ' Responda so com JSON no formato {"notas": {"F12": 7}}, com todos os marcadores pedidos e nenhum outro.'
)
PROMPTS = {
    "longo": (
        "Voce ajuda a editar um video longo de YouTube a partir da gravacao bruta. Um bom video tem historia com"
        " inicio, meio e fim, graca e curiosidade que prende ate o fim. A pergunta para cada frase e: 'essa frase"
        " mantem o video interessante? e engracada, tensa ou importante pro que vem depois?'. 0 = enrolacao, erro"
        " ou repeticao; 10 = momento forte." + _ANSWER
    ),
    "short": (
        "Voce ajuda a achar Shorts (40 s a 1 min) numa gravacao bruta. Um bom Short e um momento engracado com"
        " inicio, meio e fim, que gera curiosidade e prende ate o final. A pergunta para cada frase e: 'essa frase"
        " e engracada ou surpreendente? prende quem esta rolando o feed?'. 0 = sem graca; 10 = arranca risada."
        + _ANSWER
    ),
}


def _clock(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60:02d}:{whole % 60:02d}"


def build_windows(phrases: list[Phrase]) -> list[list[Phrase]]:
    if not phrases:
        return []
    windows = []
    start, end = phrases[0].start, phrases[-1].end
    while True:
        window = [phrase for phrase in phrases if start <= phrase.start < start + WINDOW_SEC]
        if window:
            windows.append(window)
        if start + WINDOW_SEC >= end:
            return windows
        start += WINDOW_SEC - OVERLAP_SEC


def _validate(payload: Any, wanted: set[str]) -> dict[str, float]:
    notes = payload.get("notas") if isinstance(payload, dict) else None
    if not isinstance(notes, dict):
        raise LLMResponseError("Resposta sem o campo 'notas'.")
    valid = {
        key: float(value)
        for key, value in notes.items()
        if key in wanted and isinstance(value, int | float) and not isinstance(value, bool) and 0 <= value <= 10
    }
    if len(valid) < len(wanted) * MIN_ANSWERED:
        raise LLMResponseError(f"So {len(valid)} de {len(wanted)} notas validas.")
    return valid


# Notas por frase e quantas janelas a IA nao respondeu direito nem na terceira tentativa (ficaram com nota 5).
def score_phrases(client: Any, phrases: list[Phrase], fmt: str) -> tuple[dict[int, float], int]:
    collected: dict[int, list[float]] = {}
    fallbacks = 0
    for window in build_windows(phrases):
        user = "\n".join(f"[F{phrase.index}] {_clock(phrase.start)} {phrase.text}" for phrase in window)
        wanted = {f"F{phrase.index}" for phrase in window}
        notes: dict[str, float] = {}
        for temperature in ATTEMPT_TEMPERATURES:
            try:
                notes = _validate(client.chat_json(system=PROMPTS[fmt], user=user, temperature=temperature), wanted)
                break
            except LLMResponseError:
                continue
        if not notes:
            fallbacks += 1
        for phrase in window:
            collected.setdefault(phrase.index, []).append(notes.get(f"F{phrase.index}", NEUTRAL))
    # Frase nas duas janelas da sobreposicao fica com a media.
    return {index: sum(values) / len(values) for index, values in collected.items()}, fallbacks


def transcript_hash(phrases: list[Phrase]) -> str:
    return hashlib.sha1("\n".join(phrase.text for phrase in phrases).encode("utf-8")).hexdigest()


def interest_cache(recording: str, fmt: str) -> Path:
    return Path(recording).with_suffix(f".interest.{fmt}.json")


def load_interest(
    recording: str, phrases: list[Phrase], fmt: str, make_client: Callable[[], Any]
) -> tuple[dict[int, float], str | None]:
    cache = interest_cache(recording, fmt)
    digest = transcript_hash(phrases)
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("hash") == digest:
            return {int(key): float(value) for key, value in data["scores"].items()}, None
    try:
        client = make_client()
        # Como os Cortes e a traducao: liga o Ollama se ele estiver fechado.
        ensure = getattr(client, "ensure_server_running", None)
        if callable(ensure):
            ensure()
        scores, fallbacks = score_phrases(client, phrases, fmt)
    except LLMUnavailableError as error:
        neutral = {phrase.index: NEUTRAL for phrase in phrases}
        return neutral, f"IA local indisponivel ({error}): todas as frases ficaram com nota 5."
    if fallbacks:
        # Sem cache: na proxima vez a IA tenta de novo essas janelas.
        return scores, f"A IA nao respondeu direito em {fallbacks} trecho(s) de {Path(recording).name}: nota 5 neles."
    payload = {"hash": digest, "model": getattr(client, "model", ""), "scores": {str(k): v for k, v in scores.items()}}
    cache.write_text(json.dumps(payload), encoding="utf-8")
    return scores, None
