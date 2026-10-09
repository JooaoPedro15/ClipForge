"""Le o XML de molde exportado do Premiere (Final Cut Pro XML / xmeml).

O molde e uma sequencia com pelo menos um clipe montado do jeito do usuario:
V1 = filme e V2 = webcam (os dois recortando o mesmo bruto), V3 = loop do link
(sequencia aninhada) e as trilhas de audio. O modulo guarda os clipitems do
primeiro clipe (prototipos) pra repetir em cada clipe novo.
"""

import copy
import itertools
import re
import statistics
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from cortes.timebase import Rate

DEFAULT_GAP_SEC = 10.0
REQUIRED_VIDEO_TRACKS = ("V1", "V2", "V3")


class TemplateError(ValueError):
    """Molde que nao da pra usar; a mensagem diz o que falta."""


@dataclass
class Prototype:
    kind: str  # "video" ou "audio"
    track: int  # 1 = V1/A1, contando dentro do tipo
    element: ET.Element  # clipitem do primeiro clipe, com file/sequence so como referencia
    from_source: bool  # True = recorta o bruto; False = loop (sequencia aninhada)


@dataclass
class Template:
    sequence: ET.Element
    rate: Rate
    prototypes: list[Prototype]
    source_file_id: str
    definitions: dict[str, ET.Element]  # "file:file-1" / "sequence:sequence-2" -> definicao completa
    gap_frames: int
    next_id: int  # primeiro numero livre pra clipitem-N
    version: str


def read_rate(element: ET.Element) -> Rate:
    rate = element.find("rate")
    if rate is None:
        raise TemplateError(f"<{element.tag}> sem <rate>.")
    return Rate(int(rate.findtext("timebase", "30")), rate.findtext("ntsc", "FALSE").upper() == "TRUE")


def _int(element: ET.Element, tag: str) -> int:
    text = element.findtext(tag)
    if text is None:
        raise TemplateError(f"clipitem {element.get('id')} sem <{tag}>.")
    return int(text)


def _ref_id(clip: ET.Element, tag: str) -> str | None:
    child = clip.find(tag)
    return child.get("id") if child is not None else None


def _as_reference(clip: ET.Element) -> ET.Element:
    """Copia do clipitem com os filhos file/sequence trocados por referencia (<file id="..."/>)."""
    clone = copy.deepcopy(clip)
    for index, child in enumerate(list(clone)):
        if child.tag in ("file", "sequence") and len(child):
            clone[index] = ET.Element(child.tag, {"id": child.get("id", "")})
    return clone


def _collect_definitions(root: ET.Element, main: ET.Element) -> dict[str, ET.Element]:
    # No xmeml a primeira aparicao de um arquivo/sequencia traz a definicao completa;
    # as seguintes so o id. Guarda a completa de cada um.
    definitions: dict[str, ET.Element] = {}
    for element in root.iter():
        if element is main or element.tag not in ("file", "sequence") or not len(element):
            continue
        definitions.setdefault(f"{element.tag}:{element.get('id')}", copy.deepcopy(element))
    return definitions


def parse_template(root: ET.Element) -> Template:
    if root.tag != "xmeml":
        raise TemplateError(
            "O arquivo nao e um XML do Premiere (falta <xmeml>). Exporte em Arquivo > Exportar > Final Cut Pro XML."
        )
    sequence = root.find("sequence")
    if sequence is None:
        raise TemplateError("O XML nao tem nenhuma sequencia.")
    rate = read_rate(sequence)

    tracks = [("video", i, t) for i, t in enumerate(sequence.findall("media/video/track"), 1)]
    tracks += [("audio", i, t) for i, t in enumerate(sequence.findall("media/audio/track"), 1)]
    video = {f"V{index}": track for kind, index, track in tracks if kind == "video"}
    for name in REQUIRED_VIDEO_TRACKS:
        if name not in video or video[name].find("clipitem") is None:
            raise TemplateError(
                f"O molde precisa de pelo menos um clipe na trilha {name} (V1 filme, V2 webcam, V3 loop)."
            )

    first_v1 = video["V1"].find("clipitem")
    first_start = _int(first_v1, "start")
    source_file_id = _ref_id(first_v1, "file")
    if source_file_id is None:
        raise TemplateError("O primeiro clipe de V1 nao aponta pra um arquivo de video.")
    if _ref_id(video["V2"].find("clipitem"), "file") != source_file_id:
        raise TemplateError("V1 e V2 precisam recortar o mesmo bruto (o primeiro clipe de cada uma aponta pra outro arquivo).")

    prototypes = []
    for kind, index, track in tracks:
        clip = next((c for c in track.findall("clipitem") if _int(c, "start") == first_start), None)
        if clip is not None:
            prototypes.append(Prototype(kind, index, _as_reference(clip), _ref_id(clip, "file") == source_file_id))
    if not any(p.kind == "video" and p.track == 3 for p in prototypes):
        raise TemplateError("O loop em V3 precisa comecar junto com o primeiro clipe de V1.")

    v1_items = sorted(video["V1"].findall("clipitem"), key=lambda c: _int(c, "start"))
    gaps = [_int(b, "start") - _int(a, "end") for a, b in itertools.pairwise(v1_items)]
    positive = [gap for gap in gaps if gap > 0]
    gap_frames = round(statistics.median(positive)) if positive else rate.to_frames(DEFAULT_GAP_SEC)

    numbers = [
        int(match.group(1))
        for clip in root.iter("clipitem")
        if (match := re.fullmatch(r"clipitem-(\d+)", clip.get("id", "")))
    ]

    return Template(
        sequence=sequence,
        rate=rate,
        prototypes=prototypes,
        source_file_id=source_file_id,
        definitions=_collect_definitions(root, sequence),
        gap_frames=gap_frames,
        next_id=max(numbers, default=0) + 1,
        version=root.get("version", "4"),
    )


def load_template(path: str | Path) -> Template:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise TemplateError(f"Nao consegui ler o XML do molde: {error}") from error
    return parse_template(root)
