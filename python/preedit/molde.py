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
from pathlib import Path, PureWindowsPath

from cortes.media import SourceMedia
from cortes.timebase import Rate
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


def _rate(parent: ET.Element, rate: Rate) -> None:
    element = ET.SubElement(parent, "rate")
    ET.SubElement(element, "timebase").text = str(rate.timebase)
    ET.SubElement(element, "ntsc").text = "TRUE" if rate.ntsc else "FALSE"


def _size(parent: ET.Element, source: SourceMedia) -> None:
    characteristics = ET.SubElement(parent, "samplecharacteristics")
    ET.SubElement(characteristics, "width").text = str(source.width)
    ET.SubElement(characteristics, "height").text = str(source.height)


# Sem molde: sequencia do tamanho e do fps da gravacao, o video em V1 e cada faixa de audio numa trilha
# (jogo, microfone...). Sem zoom: sem um clipe com zoom do usuario nao da pra saber onde fica o rosto.
def default_molde(source: SourceMedia) -> PreeditMolde:
    rate = Rate.from_fps(source.fps)
    name = PureWindowsPath(source.path).name
    root = ET.Element("xmeml", {"version": "4"})
    sequence = ET.SubElement(root, "sequence", {"id": "sequence-1"})
    ET.SubElement(sequence, "name").text = "Pre-edicao"
    ET.SubElement(sequence, "duration").text = "0"
    _rate(sequence, rate)
    media = ET.SubElement(sequence, "media")
    video = ET.SubElement(media, "video")
    _size(ET.SubElement(video, "format"), source)
    audio = ET.SubElement(media, "audio")

    clips = [("video", 1)] + [("audio", index) for index in range(1, source.audio_streams + 1)]
    ids = {clip: f"clipitem-{number}" for number, clip in enumerate(clips, 1)}
    for kind, index in clips:
        item = ET.SubElement(ET.SubElement(video if kind == "video" else audio, "track"), "clipitem", {"id": ids[(kind, index)]})
        ET.SubElement(item, "name").text = name
        ET.SubElement(item, "duration").text = "0"
        _rate(item, rate)
        for tag in ("start", "end", "in", "out"):
            ET.SubElement(item, tag).text = "0"
        file = ET.SubElement(item, "file", {"id": "file-1"})
        if kind == "video":
            # A primeira aparicao do arquivo traz a definicao; o XML final troca pelos dados da gravacao.
            ET.SubElement(file, "name").text = name
            ET.SubElement(file, "pathurl").text = ""
            _rate(file, rate)
            ET.SubElement(file, "duration").text = "0"
            file_media = ET.SubElement(file, "media")
            _size(ET.SubElement(file_media, "video"), source)
            ET.SubElement(ET.SubElement(file_media, "audio"), "channelcount").text = "2"
        else:
            source_track = ET.SubElement(item, "sourcetrack")
            ET.SubElement(source_track, "mediatype").text = "audio"
            ET.SubElement(source_track, "trackindex").text = str(index)
        # Video e audios ligados: no Premiere eles andam juntos.
        for other_kind, other_index in clips:
            link = ET.SubElement(item, "link")
            ET.SubElement(link, "linkclipref").text = ids[(other_kind, other_index)]
            ET.SubElement(link, "mediatype").text = other_kind
            ET.SubElement(link, "trackindex").text = str(other_index)
            ET.SubElement(link, "clipindex").text = "1"
    return parse_molde(root)
