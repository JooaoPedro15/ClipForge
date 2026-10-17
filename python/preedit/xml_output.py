"""XML do Pre-editor: os trechos colados no molde, o zoom no clipe da trilha certa e marcadores nos cortes."""

import copy
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath
from typing import Any

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

# Escala e centro (horiz, vert) do Basic Motion.
Motion = tuple[float, tuple[float, float]]
# Zoom "aproximando": entra em 0,4 s e continua chegando perto (+10% de escala) ate o fim do clipe.
ENTRY_SEC = 0.4
CREEP = 0.10
MIN_ANIMATED_SEC = 0.5


# Keyframes (quadro a partir do comeco do clipe, movimento) do zoom que vai se aproximando. Depois de entrar,
# segue na mesma reta normal->zoom: o ponto que nao se mexe entre os dois (o rosto) continua parado.
def zoom_keyframes(normal: Motion, zoomed: Motion, frames: int, fps: float) -> list[tuple[int, Motion]]:
    (s0, (h0, v0)), (s1, (h1, v1)) = normal, zoomed
    if fps <= 0 or frames / fps < MIN_ANIMATED_SEC or s1 <= s0:
        return []
    entry = min(round(ENTRY_SEC * fps), frames // 3)
    t = (s1 * (1 + CREEP) - s0) / (s1 - s0)
    beyond = (s0 + t * (s1 - s0), (h0 + t * (h1 - h0), v0 + t * (v1 - v0)))
    return [(0, normal), (entry, zoomed), (frames - 1, beyond)]


def _motion(filter_element: ET.Element | None, default_scale: float) -> Motion:
    if filter_element is None:
        return default_scale, (0.0, 0.0)
    center = filter_element.find("effect/parameter[parameterid='center']/value")
    if center is None:
        return motion_scale_of(filter_element, default_scale), (0.0, 0.0)
    return motion_scale_of(filter_element, default_scale), (float(center.findtext("horiz", "0")), float(center.findtext("vert", "0")))


def motion_scale_of(filter_element: ET.Element, default_scale: float) -> float:
    value = filter_element.findtext("effect/parameter[parameterid='scale']/value")
    return float(value) if value else default_scale


def _number(value: float) -> str:
    return f"{round(value, 4):g}"


def _write_keyframes(motion: ET.Element, keys: list[tuple[int, Motion]]) -> None:
    effect = motion.find("effect")
    params = {param.findtext("parameterid"): param for param in effect.findall("parameter")}
    for name in ("scale", "center"):
        if name not in params:
            params[name] = ET.SubElement(effect, "parameter")
            ET.SubElement(params[name], "parameterid").text = name
        for old in params[name].findall("keyframe"):
            params[name].remove(old)
    for when, (scale, (horiz, vert)) in keys:
        key = ET.SubElement(params["scale"], "keyframe")
        ET.SubElement(key, "when").text = str(when)
        ET.SubElement(key, "value").text = _number(scale)
        key = ET.SubElement(params["center"], "keyframe")
        ET.SubElement(key, "when").text = str(when)
        value = ET.SubElement(key, "value")
        ET.SubElement(value, "horiz").text = _number(horiz)
        ET.SubElement(value, "vert").text = _number(vert)


# Enquadramento do zoom na forca prevista: na reta do molde (normal -> zoom do molde), pra que o ponto que o
# molde mantem parado (o rosto) continue no lugar mesmo quando o nivel previsto e outro que o do molde.
def _zoomed(normal: Motion, zoom: ZoomTrack, level: float) -> Motion:
    (s0, (h0, v0)) = normal
    molde_scale = motion_scale_of(zoom.filter, zoom.base_scale)
    target = zoom.base_scale * level
    if molde_scale <= s0:
        return target, zoom.center
    t = (target - s0) / (molde_scale - s0)
    return target, (h0 + t * (zoom.center[0] - h0), v0 + t * (zoom.center[1] - v0))


def _apply_zoom(item: ET.Element, zoom: ZoomTrack, level: float, frames: int = 0, fps: float = 0.0, style: str = "seco") -> None:
    current = basic_motion(item)
    normal = _motion(current, zoom.base_scale)
    zoomed = _zoomed(normal, zoom, level)
    motion = copy.deepcopy(zoom.filter)
    scale = motion.find("effect/parameter[parameterid='scale']/value")
    if scale is not None:
        scale.text = _number(zoomed[0])
    center = motion.find("effect/parameter[parameterid='center']/value")
    if center is not None:
        _set_text(center, "horiz", _number(zoomed[1][0]))
        _set_text(center, "vert", _number(zoomed[1][1]))
    if style == "aproximando":
        keys = zoom_keyframes(normal, zoomed, frames, fps)
        if keys:
            _write_keyframes(motion, keys)
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


def _empty_sequence(template: Any) -> tuple[ET.Element, dict[tuple[str, int], ET.Element]]:
    sequence = copy.deepcopy(template.sequence)
    tracks = {("video", i): t for i, t in enumerate(sequence.findall("media/video/track"), 1)}
    tracks |= {("audio", i): t for i, t in enumerate(sequence.findall("media/audio/track"), 1)}
    for track in tracks.values():
        for child in [c for c in track if c.tag in CLIP_TAGS]:
            track.remove(child)
    for marker in sequence.findall("marker"):
        sequence.remove(marker)
    return sequence, tracks


# Uma sequencia com os trechos de cada bruto na ordem (gravacao pausada no OBS vira varios arquivos).
# O primeiro bruto usa o arquivo do molde; os outros ganham ids proprios com a definicao refeita.
def build_xml(molde: PreeditMolde, parts: list[tuple[SourceMedia, EditPlan]], sequence_name: str, zoom_style: str = "seco") -> ET.Element:
    template = molde.template
    if not any(plan.segments for _, plan in parts):
        raise ValueError("Nenhum trecho pra montar o XML.")
    needed = required_audio_streams(template)
    for source, _ in parts:
        if source.audio_streams < needed:
            raise ValueError(f"O molde usa a faixa de audio {needed}, mas {PureWindowsPath(source.path).name} so tem {source.audio_streams}.")

    rate = template.rate
    sequence, tracks = _empty_sequence(template)
    definitions = dict(template.definitions)
    base = definitions[f"file:{template.source_file_id}"]
    next_id = template.next_id
    timeline = 0
    clip_number = 0
    from_source = [proto for proto in template.prototypes if proto.from_source]
    for number, (source, plan) in enumerate(parts, 1):
        file_id = template.source_file_id if number == 1 else f"{template.source_file_id}-{number}"
        definition = copy.deepcopy(base)
        definition.set("id", file_id)
        definitions[f"file:{file_id}"] = _source_definition(definition, source)
        source_name = PureWindowsPath(source.path).name
        source_duration = str(rate.to_frames(source.duration_sec))
        plan_start = timeline
        for segment in plan.segments:
            source_in, source_out = rate.to_frames(segment.start), rate.to_frames(segment.end)
            length = source_out - source_in
            if length <= 0:
                continue
            clip_number += 1
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
                for reference in item.findall("file"):
                    if reference.get("id") == template.source_file_id:
                        reference.set("id", file_id)
                if number > 1:
                    # Cada arquivo e um master clip: senao o Premiere pode tocar o primeiro bruto no lugar do segundo.
                    for master in item.findall("masterclipid"):
                        master.text = f"{master.text}-{number}"
                if segment.zoom and molde.zoom and proto.kind == "video" and proto.track == molde.zoom.track:
                    _apply_zoom(item, molde.zoom, segment.zoom, length, rate.fps, zoom_style)
                for link in item.findall("link"):
                    ref = link.findtext("linkclipref")
                    if ref in new_ids:
                        _set_text(link, "linkclipref", new_ids[ref])
                        _set_text(link, "clipindex", str(clip_number))
                    else:
                        item.remove(link)
                _append_clip(tracks[(proto.kind, proto.track)], item)
            timeline += length
        sequence.extend(_marker(plan_start + rate.to_frames(at), name) for at, name in plan.markers)

    _set_text(sequence, "uuid", str(uuid.uuid4()))
    _set_text(sequence, "name", sequence_name)
    _set_text(sequence, "duration", str(timeline))
    _expand_first_references(sequence, definitions, set())

    root = ET.Element("xmeml", {"version": template.version})
    root.append(sequence)
    return root


def write_xml(
    molde: PreeditMolde, parts: list[tuple[SourceMedia, EditPlan]], out_path: str | Path, sequence_name: str, zoom_style: str = "seco"
) -> Path:
    root = build_xml(molde, parts, sequence_name, zoom_style)
    ET.indent(root, space="\t")
    text = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="unicode") + "\n"
    out = Path(out_path)
    out.write_text(text, encoding="utf-8")
    return out
