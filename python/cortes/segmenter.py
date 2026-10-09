"""Escolhe as fronteiras dos clipes: programacao dinamica no formato do corte de haste.

melhor[j] = max sobre i (MIN <= t_j - t_i <= MAX) de melhor[i] + (nota(j) - BASE) - LAMBDA * |dur - ALVO| / ALVO

BASE = mediana das notas dos candidatos do trecho. Sem ela, todo corte somaria nota positiva e a
programacao dinamica cortaria o maximo que as duracoes deixam; com ela, so vale cortar num ponto
melhor que o tipico do trecho, e a quantidade de clipes vem do ALVO.
"""

import bisect
import math
import statistics
from dataclasses import dataclass

EMERGENCY_SCORE = -20.0  # ponto sem candidato: abaixo de qualquer candidato centrado (>= -10)
GRID_SEC = 1.0
NEAR_CANDIDATE_SEC = 0.5
DEFAULT_LAMBDA = 4.0  # peso do desvio da duracao alvo (calibrado no gabarito)


@dataclass(frozen=True)
class Durations:
    min_sec: float = 70.0
    target_sec: float = 150.0
    max_sec: float = 240.0


def _points(candidates: list[tuple[float, float]], start: float, end: float) -> list[tuple[float, float]]:
    inside = sorted((t, score) for t, score in candidates if start < t < end)
    times = [t for t, _ in inside]
    grid = []
    t = start + GRID_SEC
    while t < end - 1e-9:
        i = bisect.bisect_left(times, t)
        near = any(abs(times[k] - t) <= NEAR_CANDIDATE_SEC for k in (i - 1, i) if 0 <= k < len(times))
        if not near:
            grid.append((t, EMERGENCY_SCORE))
        t += GRID_SEC
    return [(start, 0.0), *sorted(inside + grid), (end, 0.0)]


def _solve(points: list[tuple[float, float]], durations: Durations, lam: float, last_min: float) -> list[float] | None:
    times = [t for t, _ in points]
    n = len(points)
    best = [-math.inf] * n
    previous = [-1] * n
    best[0] = 0.0
    for j in range(1, n):
        minimum = last_min if j == n - 1 else durations.min_sec
        lo = bisect.bisect_left(times, times[j] - durations.max_sec - 1e-9)
        hi = bisect.bisect_right(times, times[j] - minimum + 1e-9)
        for i in range(lo, min(hi, j)):
            if best[i] == -math.inf:
                continue
            length = times[j] - times[i]
            value = best[i] + points[j][1] - lam * abs(length - durations.target_sec) / durations.target_sec
            if value > best[j]:
                best[j] = value
                previous[j] = i
    if best[-1] == -math.inf:
        return None
    bounds = []
    j = n - 1
    while j != -1:
        bounds.append(round(times[j], 3))
        j = previous[j]
    return bounds[::-1]


def choose_boundaries(
    candidates: list[tuple[float, float]],
    start: float,
    end: float,
    durations: Durations | None = None,
    lam: float = DEFAULT_LAMBDA,
) -> list[float]:
    """candidates = [(tempo, nota 0-10)]. Devolve [inicio, fronteira1, ..., fim]: todo clipe entre min e max;
    o ultimo so fica abaixo do min quando nao existe outra solucao (trecho curto demais)."""
    durations = durations or Durations()
    if end <= start:
        raise ValueError("Trecho vazio: o fim precisa vir depois do inicio.")
    inside = [(t, score) for t, score in candidates if start < t < end]
    base = statistics.median(score for _t, score in inside) if inside else 0.0
    points = _points([(t, score - base) for t, score in inside], start, end)
    bounds = _solve(points, durations, lam, durations.min_sec)
    if bounds is None:
        bounds = _solve(points, durations, lam, 0.0)
    if bounds is None:
        raise ValueError(f"Nao ha como cortar {end - start:.0f}s em clipes de no maximo {durations.max_sec:.0f}s.")
    return bounds
