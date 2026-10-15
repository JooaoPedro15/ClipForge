"""Ensino por video final: acha o arquivo que cada sequencia exportou (o Premiere grava nome e trecho no projeto).

Parear so pela duracao nao serve: o usuario exporta trechos de sequencias compridas, e numa pasta com memes e
musicas um Short de 26 s tem dezenas de arquivos com a mesma duracao.
"""

import unicodedata
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from premiere_project import SequenceEdit

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv"}
# Folga do export (preenchimento do audio, um quadro a mais).
DURATION_TOLERANCE = 0.5


@dataclass
class Candidate:
    project: str
    sequence: SequenceEdit
    # Quando o projeto foi salvo: a mesma exportacao em varias versoes (Auto-Save) conta uma vez, a mais antiga.
    modified: float


@dataclass
class Pair:
    project: str
    sequence: SequenceEdit
    video: str
    # Trecho exportado, em segundos da sequencia.
    start: float
    end: float


def name_key(path: str) -> str:
    # Acento pode vir composto ou decomposto, e o Windows nao diferencia maiuscula.
    return unicodedata.normalize("NFC", PureWindowsPath(path).name).casefold()


def scan_videos(folder: Path) -> dict[str, list[Path]]:
    """Videos da pasta (com subpastas) por nome. A legenda queimada do app (`.hardsub.`) fica de fora."""
    files: dict[str, list[Path]] = {}
    for path in sorted(folder.rglob("*"), key=lambda item: item.relative_to(folder).as_posix()):
        if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES and ".hardsub." not in path.name.lower():
            files.setdefault(name_key(str(path)), []).append(path)
    return files


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= DURATION_TOLERANCE


def _unique_exports(candidates: list[Candidate]) -> tuple[list[Candidate], int]:
    """Uma por exportacao (arquivo + trecho), a da versao mais antiga; e quantas sequencias nao tem exportacao."""
    kept: dict[tuple[str, float, float], Candidate] = {}
    without: set[str] = set()
    for item in sorted(candidates, key=lambda candidate: candidate.modified):
        export = item.sequence.export
        if export is None:
            without.add(item.sequence.name)
            continue
        kept.setdefault((name_key(export[0]), round(export[1], 1), round(export[2], 1)), item)
    return list(kept.values()), len(without)


def _match(item: Candidate, options: list[Path], duration_of: Callable[[str], float]) -> Pair | None:
    _, start, end = item.sequence.export
    durations = [(option, duration_of(str(option))) for option in options]
    # O trecho gravado vem primeiro em todas as copias; so depois a sequencia inteira.
    for option, seconds in durations:
        if _same(seconds, end - start):
            return Pair(item.project, item.sequence, str(option), start, end)
    for option, seconds in durations:
        if _same(seconds, item.sequence.duration):
            # Export de "sequencia inteira" com entrada/saida antigas gravadas no projeto.
            return Pair(item.project, item.sequence, str(option), 0.0, item.sequence.duration)
    return None


# Nunca chuta: arquivo que nao esta na pasta, duracao que nao bate e dois exports pro mesmo arquivo ficam de fora.
def pair_videos(
    candidates: list[Candidate], files: dict[str, list[Path]], duration_of: Callable[[str], float]
) -> tuple[list[Pair], list[dict], int]:
    exports, without = _unique_exports(candidates)
    by_video: dict[str, list[Pair]] = defaultdict(list)
    skipped: list[dict] = []
    for item in exports:
        path = item.sequence.export[0]
        name = item.sequence.name
        options = files.get(name_key(path), [])
        if not options:
            skipped.append({"recording": PureWindowsPath(path).name, "reason": f"video exportado nao encontrado na pasta ({name})"})
            continue
        pair = _match(item, options, duration_of)
        if pair is None:
            skipped.append({"recording": str(options[0]), "reason": f"o video nao tem a duracao do trecho exportado ({name})"})
            continue
        by_video[pair.video].append(pair)

    pairs = []
    for video in sorted(by_video):
        same_file = by_video[video]
        if len(same_file) > 1:
            names = ", ".join(sorted(pair.sequence.name for pair in same_file))
            skipped.append({"recording": video, "reason": f"mais de uma exportacao para o mesmo arquivo ({names})"})
        else:
            pairs.append(same_file[0])
    return pairs, skipped, without
