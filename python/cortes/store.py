"""Analise salva ao lado do bruto (<bruto>.cortes.json) e escolha de quais clipes vao pro XML."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from cortes.candidates import Candidate

VERSION = 1


@dataclass
class Clip:
    n: int
    start: float
    end: float
    title: str = ""
    hook: int | None = None
    score: float | None = None


@dataclass
class Analysis:
    source: dict  # campos de SourceMedia
    options: dict  # start/end resolvidos, faixas, modelos, duracoes
    transcript: dict  # {"film": [{start, end, text}], "mic": [...]}
    mic_speech: list[list[float]]  # intervalos com o usuario falando (nota de reacao)
    shot_cuts: list[float]
    candidates: list[Candidate]
    clips: list[Clip]
    warnings: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)


def analysis_path(source_path: str | Path) -> Path:
    return Path(source_path).with_suffix(".cortes.json")


def save(analysis: Analysis, path: str | Path) -> Path:
    out = Path(path)
    out.write_text(json.dumps({"version": VERSION, **asdict(analysis)}, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def load(path: str | Path) -> Analysis:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != VERSION:
        raise ValueError(
            f"{Path(path).name} e de uma versao do modulo de cortes que este app nao le (versao {data.get('version')})."
        )
    return Analysis(
        source=data["source"],
        options=data["options"],
        transcript=data["transcript"],
        mic_speech=data["mic_speech"],
        shot_cuts=data["shot_cuts"],
        candidates=[Candidate(**item) for item in data["candidates"]],
        clips=[Clip(**item) for item in data["clips"]],
        warnings=data.get("warnings", []),
        timings=data.get("timings", {}),
    )


def select_clips(clips: list[Clip], numbers: str | None = None, top: int | None = None) -> list[Clip]:
    """numbers='1,3' escolhe por numero; top=N fica com as N maiores notas. Sempre na ordem do filme."""
    chosen = clips
    if numbers:
        wanted = {int(part) for part in numbers.split(",") if part.strip()}
        missing = sorted(wanted - {clip.n for clip in clips})
        if missing:
            raise ValueError(f"Clipe(s) que nao existem na analise: {', '.join(map(str, missing))}.")
        chosen = [clip for clip in clips if clip.n in wanted]
    if top is not None:
        if top < 1:
            raise ValueError("--top precisa ser 1 ou mais.")
        ranked = sorted(chosen, key=lambda clip: clip.score if clip.score is not None else -1.0, reverse=True)
        keep = {clip.n for clip in ranked[:top]}
        chosen = [clip for clip in chosen if clip.n in keep]
    return chosen
