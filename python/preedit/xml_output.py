"""XML do Pre-editor: os trechos colados no molde, o zoom no clipe da trilha certa e marcadores nos cortes."""

import copy
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath

from cortes.media import SourceMedia
from cortes.xmeml_writer import (
    CLIP_TAGS,
    _append_clip,
    _expand_first_references,
    _set_text,
    _set_times,
    _source_definition,
    required_audio_streams,
)

from preedit.editor import EditPlan
from preedit.molde import PreeditMolde, ZoomTrack, basic_motion


def _apply_zoom(item: ET.Element, zoom: ZoomTrack, level: float) -> None:
    motion = copy.deepcopy(zoom.filter)
    scale = motion.find("effect/parameter[parameterid='scale']/value")
    if scale is not None:
        scale.text = f"{zoom.base_scale * level:g}"
    current = basic_motion(item)
    if current is None:
        item.append(motion)
        return
    position = list(item).index(current)
    item.remove(current)
    item.insert(position, motion)


def _marker(frame: int, name: str) -> ET.Element:
    marker = ET.Element("marker")
    ET.SubElement(marker, "comment").text = ""
    ET.SubElement(marker, "name").text = name
    ET.SubElement(marker, "in").text = str(frame)
    ET.SubElement(marker, "out").text = "-1"
    return marker


def build_xml(molde: PreeditMolde, source: SourceMedia, plan: EditPlan, sequence_name: str) -> ET.Element:
    template = molde.template
    if not plan.segments:
        raise ValueError("Nenhum trecho pra montar o XML.")
    needed = required_audio_streams(template)
    if source.audio_streams < needed:
        raise ValueError(f"O molde usa a faixa de audio {needed}, mas {PureWindowsPath(source.path).name} so tem {source.audio_streams}.")

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
    from_source = [proto for proto in template.prototypes if proto.from_source]
    for number, segment in enumerate(plan.segments, 1):
        source_in, source_out = rate.to_frames(segment.start), rate.to_frames(segment.end)
        length = source_out - source_in
        if length <= 0:
            continue
        new_ids = {}
        for proto in from_source:
            new_ids[proto.element.get("id")] = f"clipitem-{next_id}"
            next_id += 1
        for proto in from_source:
            item = copy.deepcopy(proto.element)
            item.set("id", new_ids[proto.element.get("id")])
            _set_times(item, rate, timeline, timeline + length, source_in, source_out)
            _set_text(item, "name", source_name)
            _set_text(item, "duration", source_duration)
            if segment.zoom and molde.zoom and proto.kind == "video" and proto.track == molde.zoom.track:
                _apply_zoom(item, molde.zoom, segment.zoom)
            for link in item.findall("link"):
                ref = link.findtext("linkclipref")
                if ref in new_ids:
                    _set_text(link, "linkclipref", new_ids[ref])
                    _set_text(link, "clipindex", str(number))
                else:
                    item.remove(link)
            _append_clip(tracks[(proto.kind, proto.track)], item)
        timeline += length

    _set_text(sequence, "uuid", str(uuid.uuid4()))
    _set_text(sequence, "name", sequence_name)
    _set_text(sequence, "duration", str(timeline))
    sequence.extend(_marker(rate.to_frames(at), name) for at, name in plan.markers)

    definitions = dict(template.definitions)
    source_key = f"file:{template.source_file_id}"
    definitions[source_key] = _source_definition(definitions[source_key], source)
    _expand_first_references(sequence, definitions, set())

    root = ET.Element("xmeml", {"version": template.version})
    root.append(sequence)
    return root


def write_xml(molde: PreeditMolde, source: SourceMedia, plan: EditPlan, out_path: str | Path, sequence_name: str) -> Path:
    root = build_xml(molde, source, plan, sequence_name)
    ET.indent(root, space="\t")
    text = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="unicode") + "\n"
    out = Path(out_path)
    out.write_text(text, encoding="utf-8")
    return out
