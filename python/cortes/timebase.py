"""Tempo no Premiere: segundos, quadros (timebase/NTSC) e ticks."""

from dataclasses import dataclass
from typing import Self

# O Premiere guarda tempo tambem em ticks (pproTicksIn/Out no XML): 254016000000 por segundo.
TICKS_PER_SECOND = 254_016_000_000


@dataclass(frozen=True)
class Rate:
    timebase: int
    ntsc: bool

    @classmethod
    def from_fps(cls, fps: float) -> Self:
        timebase = round(fps)
        # 29,97 / 59,94 / 23,976: timebase arredondado com NTSC ligado.
        ntsc = abs(fps - timebase) > 1e-3 and abs(fps - timebase * 1000 / 1001) < 1e-2
        return cls(timebase, ntsc)

    @property
    def fps(self) -> float:
        return self.timebase * 1000 / 1001 if self.ntsc else float(self.timebase)

    def to_frames(self, seconds: float) -> int:
        return round(seconds * self.fps)

    def to_seconds(self, frames: int) -> float:
        return frames / self.fps

    def to_ticks(self, frames: int) -> int:
        # Conta inteira: em NTSC cada quadro dura 1001/(timebase*1000) s.
        if self.ntsc:
            return frames * TICKS_PER_SECOND * 1001 // (self.timebase * 1000)
        return frames * TICKS_PER_SECOND // self.timebase


def parse_clock(text: str) -> float:
    """'2:24.44' -> 144.44; '1:02:03' -> 3723.0; '95.5' -> 95.5."""
    parts = text.strip().split(":")
    if not 1 <= len(parts) <= 3 or any(part == "" for part in parts):
        raise ValueError(f"Tempo invalido: {text!r}")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return round(seconds, 3)


def format_clock(seconds: float) -> str:
    centis = round(seconds * 100)
    whole, cs = divmod(centis, 100)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    base = f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
    return f"{base}.{cs:02d}"


def parse_ranges(text: str) -> list[tuple[float, float]]:
    """'2:24.44-3:39.72,3:39.72-5:28.56' -> [(144.44, 219.72), (219.72, 328.56)]."""
    ranges = []
    for chunk in text.split(","):
        start_text, separator, end_text = chunk.strip().partition("-")
        if not separator:
            raise ValueError(f"Trecho sem '-': {chunk!r}")
        start, end = parse_clock(start_text), parse_clock(end_text)
        if end <= start:
            raise ValueError(f"Trecho invertido ou vazio: {chunk!r}")
        ranges.append((start, end))
    return ranges
