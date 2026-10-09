"""Monta o XML final: os prototipos do molde clonados uma vez por clipe, numa sequencia so."""

import copy
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from urllib.parse import quote

from cortes.media import SourceMedia
from cortes.timebase import Rate
from cortes.xmeml_template import Template

CLIP_TAGS = ("clipitem", "transitionitem", "generatoritem")


@dataclass(frozen=True)
class ClipSpec:
    start: float  # segundos no bruto
    end: float
    title: str = ""
    score: float | None = None


def to_pathurl(path: str) -> str:
    """'E:\\Bruto\\a b.mp4' -> 'file://localhost/E%3a/Bruto/a%20b.mp4' (como o Premiere grava)."""
    windows = PureWindowsPath(path)
    drive = windows.drive.replace(":", "%3a")
    parts = [quote(part, safe="") for part in windows.parts[1:]]
    return "file://localhost/" + "/".join([drive, *parts])


def required_audio_streams(template: Template) -> int:
    """Maior faixa de audio do bruto que o molde usa (sourcetrack/trackindex comeca em 1)."""
    indexes = [
        int(proto.element.findtext("sourcetrack/trackindex", "0"))
        for proto in template.prototypes
        if proto.kind == "audio" and proto.from_source
    ]
    return max(indexes, default=0)


def _set_text(parent: ET.Element, tag: str, text: str) -> None:
    child = parent.find(tag)
    if child is None:
        child = ET.SubElement(parent, tag)
    child.text = text


def _source_definition(definition: ET.Element, source: SourceMedia) -> ET.Element:
    updated = copy.deepcopy(definition)
    file_rate = Rate.from_fps(source.fps)
    _set_text(updated, "name", PureWindowsPath(source.path).name)
    _set_text(updated, "pathurl", to_pathurl(source.path))
    _set_text(updated, "duration", str(file_rate.to_frames(source.duration_sec)))
    for rate in updated.iter("rate"):
        _set_text(rate, "timebase", str(file_rate.timebase))
        _set_text(rate, "ntsc", "TRUE" if file_rate.ntsc else "FALSE")
    for characteristics in updated.iter("samplecharacteristics"):
        if characteristics.find("width") is not None:
            _set_text(characteristics, "width", str(source.width))
            _set_text(characteristics, "height", str(source.height))
    return updated


def _set_times(item: ET.Element, rate: Rate, start: int, end: int, source_in: int, source_out: int) -> None:
    for tag, value in (("start", start), ("end", end), ("in", source_in), ("out", source_out)):
        _set_text(item, tag, str(value))
    # O Premiere prefere os ticks quando eles existem; sem atualizar, o clipe abriria no lugar do molde.
    if item.find("pproTicksIn") is not None:
        _set_text(item, "pproTicksIn", str(rate.to_ticks(source_in)))
        _set_text(item, "pproTicksOut", str(rate.to_ticks(source_out)))


def _append_clip(track: ET.Element, item: ET.Element) -> None:
    # Clipitems vem antes de <enabled>/<locked> na trilha, como o Premiere grava.
    position = next((i for i, child in enumerate(track) if child.tag not in CLIP_TAGS), len(track))
    track.insert(position, item)


def _expand_first_references(element: ET.Element, definitions: dict[str, ET.Element], defined: set[str]) -> None:
    """Na ordem do documento, a primeira referencia (<file id="x"/>) a cada arquivo/sequencia vira a
    definicao completa; as seguintes continuam so referencia (regra do xmeml)."""
    for index, child in enumerate(list(element)):
        if child.tag in ("file", "sequence") and child.get("id"):
            key = f"{child.tag}:{child.get('id')}"
            if len(child) == 0 and key not in defined and key in definitions:
                child = copy.deepcopy(definitions[key])
                element[index] = child
            if len(child):
                defined.add(key)
        _expand_first_references(child, definitions, defined)


def _marker(number: int, clip: ClipSpec, timeline_frame: int) -> ET.Element:
    marker = ET.Element("marker")
    ET.SubElement(marker, "comment").text = "" if clip.score is None else f"nota {clip.score:g}/10"
    ET.SubElement(marker, "name").text = f"{number:02d} - {clip.title}" if clip.title else f"{number:02d}"
    ET.SubElement(marker, "in").text = str(timeline_frame)
    ET.SubElement(marker, "out").text = "-1"
    return marker


def build_xml(template: Template, source: SourceMedia, clips: list[ClipSpec], sequence_name: str) -> ET.Element:
    if not clips:
        raise ValueError("Nenhum clipe selecionado pra gerar o XML.")
    needed = required_audio_streams(template)
    if source.audio_streams < needed:
        raise ValueError(
            f"O molde usa a faixa de audio {needed} do bruto, mas {PureWindowsPath(source.path).name} "
            f"so tem {source.audio_streams}."
        )

    rate = template.rate
    sequence = copy.deepcopy(template.sequence)
    tracks = {("video", i): t for i, t in enumerate(sequence.findall("media/video/track"), 1)}
    tracks |= {("audio", i): t for i, t in enumerate(sequence.findall("media/audio/track"), 1)}
    for track in tracks.values():
        for child in [c for c in track if c.tag in CLIP_TAGS]:
            track.remove(child)
    for marker in sequence.findall("marker"):
        sequence.remove(marker)

    source_name = PureWindowsPath(source.path).name
    source_duration = str(rate.to_frames(source.duration_sec))
    next_id = template.next_id
    timeline = 0
    markers = []
    for number, clip in enumerate(clips, 1):
        source_in, source_out = rate.to_frames(clip.start), rate.to_frames(clip.end)
        length = source_out - source_in
        if length <= 0:
            raise ValueError(f"Clipe {number} sem duracao ({clip.start}-{clip.end}).")
        new_ids = {}
        for proto in template.prototypes:
            new_ids[proto.element.get("id")] = f"clipitem-{next_id}"
            next_id += 1
        for proto in template.prototypes:
            item = copy.deepcopy(proto.element)
            item.set("id", new_ids[proto.element.get("id")])
            if proto.from_source:
                _set_times(item, rate, timeline, timeline + length, source_in, source_out)
                _set_text(item, "name", source_name)
                _set_text(item, "duration", source_duration)
            else:
                loop_in = int(item.findtext("in", "0"))
                loop_length = int(item.findtext("duration", "0"))
                if loop_length and loop_in + length > loop_length:
                    raise ValueError(
                        f"Clipe {number} ({length / rate.fps:.0f}s) e maior que o loop do molde "
                        f"({(loop_length - loop_in) / rate.fps:.0f}s). Aumente o loop no Premiere ou use um maximo menor."
                    )
                _set_times(item, rate, timeline, timeline + length, loop_in, loop_in + length)
            for link in item.findall("link"):
                ref = link.findtext("linkclipref")
                if ref in new_ids:
                    _set_text(link, "linkclipref", new_ids[ref])
                    _set_text(link, "clipindex", str(number))
                else:
                    item.remove(link)
            _append_clip(tracks[(proto.kind, proto.track)], item)
        markers.append(_marker(number, clip, timeline))
        timeline += length + template.gap_frames

    _set_text(sequence, "uuid", str(uuid.uuid4()))
    _set_text(sequence, "name", sequence_name)
    _set_text(sequence, "duration", str(timeline - template.gap_frames))
    sequence.extend(markers)

    definitions = dict(template.definitions)
    source_key = f"file:{template.source_file_id}"
    definitions[source_key] = _source_definition(definitions[source_key], source)
    _expand_first_references(sequence, definitions, set())

    root = ET.Element("xmeml", {"version": template.version})
    root.append(sequence)
    return root


def write_xml(
    template: Template, source: SourceMedia, clips: list[ClipSpec], out_path: str | Path, sequence_name: str
) -> Path:
    root = build_xml(template, source, clips, sequence_name)
    ET.indent(root, space="\t")
    text = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="unicode") + "\n"
    out = Path(out_path)
    out.write_text(text, encoding="utf-8")
    return out
