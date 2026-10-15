"""Molde do Pre-editor: um video pronto do usuario exportado do Premiere (Final Cut Pro XML) com um zoom.

Diferente do molde dos Cortes (que exige V1 filme, V2 webcam e V3 loop), aqui qualquer layout serve:
a gravacao e o arquivo com mais clipes de video (uma vinheta antes dela nao conta), as trilhas que a
recortam viram prototipos e a trilha que tem um clipe com escala maior que
a do primeiro clipe dela e a trilha do zoom (centro do rosto ja nas unidades do XML).
"""

import copy
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from cortes.xmeml_template import (
    Prototype,
    Template,
    TemplateError,
    _as_reference,
    _collect_definitions,
    _int,
    _ref_id,
    read_rate,
)

ZOOM_MIN_RATIO = 1.05


@dataclass
class ZoomTrack:
    track: int
    base_scale: float
    # Basic Motion do clipe com zoom do molde (copiado em cada clipe com zoom).
    filter: ET.Element
    center: tuple[float, float]


@dataclass
class PreeditMolde:
    template: Template
    zoom: ZoomTrack | None


def basic_motion(clip: ET.Element) -> ET.Element | None:
    for filter_element in clip.findall("filter"):
        if filter_element.findtext("effect/effectid") == "basic":
            return filter_element
    return None


def motion_scale(clip: ET.Element) -> float:
    motion = basic_motion(clip)
    value = motion.findtext("effect/parameter[parameterid='scale']/value") if motion is not None else None
    return float(value) if value else 100.0


def _center(motion: ET.Element) -> tuple[float, float]:
    value = motion.find("effect/parameter[parameterid='center']/value")
    if value is None:
        return 0.0, 0.0
    return float(value.findtext("horiz", "0")), float(value.findtext("vert", "0"))


def parse_molde(root: ET.Element) -> PreeditMolde:
    if root.tag != "xmeml":
        raise TemplateError("O arquivo nao e um XML do Premiere (falta <xmeml>). Exporte em Arquivo > Exportar > Final Cut Pro XML.")
    sequence = root.find("sequence")
    if sequence is None:
        raise TemplateError("O XML nao tem nenhuma sequencia.")
    rate = read_rate(sequence)

    tracks = [("video", i, t) for i, t in enumerate(sequence.findall("media/video/track"), 1)]
    tracks += [("audio", i, t) for i, t in enumerate(sequence.findall("media/audio/track"), 1)]
    video_clips = [clip for kind, _, track in tracks if kind == "video" for clip in track.findall("clipitem") if _ref_id(clip, "file")]
    if not video_clips:
        raise TemplateError("O molde precisa de pelo menos um clipe de video recortando a gravacao.")
    # Empate fica com o primeiro arquivo que aparece.
    counts = Counter(_ref_id(clip, "file") for clip in video_clips)
    source_file_id = max(counts, key=lambda file_id: counts[file_id])
    first_start = min(_int(clip, "start") for clip in video_clips if _ref_id(clip, "file") == source_file_id)

    prototypes = []
    zoom: ZoomTrack | None = None
    for kind, index, track in tracks:
        clip = next((c for c in track.findall("clipitem") if _int(c, "start") == first_start), None)
        if clip is None:
            # Trilha da gravacao fora de alinhamento sumiria do XML (ex.: o audio do microfone).
            if any(_ref_id(c, "file") == source_file_id for c in track.findall("clipitem")):
                raise TemplateError(
                    f"No molde, a trilha de {kind} {index} usa a gravacao mas nao comeca junto com o primeiro clipe dela: "
                    "alinhe o comeco das trilhas e exporte de novo."
                )
            continue
        from_source = _ref_id(clip, "file") == source_file_id
        prototypes.append(Prototype(kind, index, _as_reference(clip), from_source))
        if kind != "video" or not from_source or zoom is not None:
            continue
        base = motion_scale(clip)
        for other in track.findall("clipitem"):
            motion = basic_motion(other)
            if motion is not None and _ref_id(other, "file") == source_file_id and motion_scale(other) >= base * ZOOM_MIN_RATIO:
                zoom = ZoomTrack(index, base, copy.deepcopy(motion), _center(motion))
                break

    numbers = [int(match.group(1)) for clip in root.iter("clipitem") if (match := re.fullmatch(r"clipitem-(\d+)", clip.get("id", "")))]
    template = Template(
        sequence=sequence,
        rate=rate,
        prototypes=prototypes,
        source_file_id=source_file_id,
        definitions=_collect_definitions(root, sequence),
        gap_frames=0,
        next_id=max(numbers, default=0) + 1,
        version=root.get("version", "4"),
    )
    return PreeditMolde(template, zoom)


def load_molde(path: str | Path) -> PreeditMolde:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise TemplateError(f"Nao consegui ler o XML do molde: {error}") from error
    return parse_molde(root)
