"""Tipos do Pre-editor. Tempos sempre em segundos da gravacao original."""

from dataclasses import dataclass, field

FORMATS = ("longo", "short")


@dataclass(frozen=True)
class Range:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class Zoom:
    start: float
    end: float
    # Escala do clipe dividida pela escala normal da trilha (1.7 = 170% sobre 100%).
    level: float


@dataclass
class RecordingLabels:
    recording: str
    format: str
    # O que ficou no video, sem copias, em ordem.
    kept: list[Range]
    zooms: list[Zoom]
    # Fonte que ja era saida do Pre-editor atual: silencios mexidos, nao ensina pausa.
    preedited: bool = False
    sequences: list[str] = field(default_factory=list)

    @property
    def span(self) -> Range:
        return Range(self.kept[0].start, self.kept[-1].end)
