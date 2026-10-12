"""Le as legendas corrigidas direto de um projeto do Premiere (.prproj).

O .prproj e um XML em gzip. Cada objeto e filho direto da raiz e aponta pros outros
por ObjectRef (ObjectID) ou ObjectURef (ObjectUID). O usuario corrige a legenda e
depois a transforma em grafico de texto (pra ter efeitos), o que apaga a trilha de
legenda: o que sobra e um clipe de grafico por legenda, com o tempo na linha do tempo
da sequencia (em ticks) e o texto num blob base64 (flatbuffer).
"""

import base64
import gzip
import json
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from style_alignment import Card

# Unidade de tempo interna do Premiere.
TICKS_PER_SECOND = 254_016_000_000
TEXT_COMPONENT = "AE.ADBE Text"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
# O bruto que o app legendou: o usuario exporta o audio da sequencia (Sequencia 42.mp3).
ORIGINAL_EXTENSIONS = (".mp3", ".wav", ".m4a", ".mp4", ".mov", ".mkv")


class ProjectError(Exception):
    """Erro com mensagem pronta pra mostrar ao usuario."""


@dataclass
class ProjectSequence:
    name: str
    # Tempo do video final: ja descontado o inicio da exportacao.
    cards: list[Card]
    final_path: str | None = None
    original_path: str | None = None
    tracks: list[int] = field(default_factory=list)


@dataclass
class _Clip:
    start: float
    end: float
    text: str


def flatbuffer_strings(raw: bytes) -> list[str]:
    """Strings de um flatbuffer: 4 bytes de tamanho, o texto em UTF-8 e um zero no fim."""
    found = []
    for offset in range(len(raw) - 4):
        (length,) = struct.unpack_from("<I", raw, offset)
        end = offset + 4 + length
        if not 1 <= length <= 2000 or end >= len(raw) or raw[end] != 0:
            continue
        try:
            text = raw[offset + 4 : end].decode("utf-8")
        except UnicodeDecodeError:
            continue
        if all(char.isprintable() or char in "\r\n\t" for char in text):
            found.append(text)
    return found


# O texto e a ultima string do blob (antes dela vem o nome da fonte). Quebra de linha vira espaco.
def text_from_blob(raw: bytes) -> str:
    strings = flatbuffer_strings(raw)
    return " ".join(strings[-1].split()) if strings else ""


class _Index:
    def __init__(self, root: ET.Element):
        self.by_id: dict[str, ET.Element] = {}
        self.by_uid: dict[str, ET.Element] = {}
        for child in root:
            if "ObjectID" in child.attrib:
                self.by_id[child.attrib["ObjectID"]] = child
            if "ObjectUID" in child.attrib:
                self.by_uid[child.attrib["ObjectUID"]] = child
        # Blob repetido e gravado uma vez so: as outras copias vem vazias, so com o hash.
        self.blobs: dict[str, str] = {}
        for element in root.iter():
            digest = element.get("BinaryHash")
            if digest and (element.text or "").strip():
                self.blobs.setdefault(digest, element.text.strip())

    def deref(self, element: ET.Element | None) -> ET.Element | None:
        if element is None:
            return None
        if "ObjectRef" in element.attrib:
            return self.by_id.get(element.attrib["ObjectRef"])
        if "ObjectURef" in element.attrib:
            return self.by_uid.get(element.attrib["ObjectURef"])
        return None

    def blob(self, element: ET.Element | None) -> bytes | None:
        if element is None:
            return None
        data = (element.text or "").strip() or self.blobs.get(element.get("BinaryHash", ""), "")
        return base64.b64decode(data) if data else None


def load_root(project_path: str | Path) -> ET.Element:
    path = Path(project_path)
    if not path.exists():
        raise ProjectError(f"Projeto do Premiere nao encontrado: {path}")
    raw = path.read_bytes()
    try:
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return ET.fromstring(raw)
    except (OSError, EOFError, ET.ParseError) as error:
        raise ProjectError("Nao deu pra ler o projeto (o Premiere pode estar salvando agora): salve e tente de novo.") from error


def _seconds(item: ET.Element, tag: str) -> float:
    # Valor padrao (0) nao e gravado: clipe no inicio da sequencia vem sem <Start>.
    # (O clipe de legenda guarda o TrackItem um nivel mais fundo que o de video.)
    return int(item.findtext(f".//ClipTrackItem/TrackItem/{tag}") or 0) / TICKS_PER_SECOND


def _tracks(index: _Index, sequence: ET.Element, group_tag: str) -> list[ET.Element]:
    tracks = []
    for track_group in sequence.findall("TrackGroups/TrackGroup"):
        group = index.deref(track_group.find("Second"))
        if group is None or group.tag != group_tag:
            continue
        for reference in group.findall("TrackGroup/Tracks/Track"):
            track = index.deref(reference)
            if track is not None:
                tracks.append(track)
    return tracks


def _track_items(index: _Index, track: ET.Element, item_tag: str) -> list[ET.Element]:
    items = [index.deref(reference) for reference in track.findall(".//ClipItems/TrackItems/TrackItem")]
    return [item for item in items if item is not None and item.tag == item_tag]


# Texto do grafico: camadas de texto do proprio clipe (o estilo vinculado guarda so um "Aa" de exemplo).
def _graphic_text(index: _Index, item: ET.Element) -> str:
    chain = index.deref(item.find("ClipTrackItem/ComponentOwner/Components"))
    if chain is None:
        return ""
    texts = []
    for reference in chain.findall("ComponentChain/Components/Component"):
        component = index.deref(reference)
        if component is None or component.findtext("MatchName") != TEXT_COMPONENT:
            continue
        for param_reference in component.findall("Component/Params/Param"):
            param = index.deref(param_reference)
            if param is not None and param.tag == "ArbVideoComponentParam":
                raw = index.blob(param.find("StartKeyframeValue"))
                if raw:
                    texts.append(text_from_blob(raw))
                break
    return " ".join(text for text in texts if text)


def _caption_text(index: _Index, item: ET.Element) -> str:
    block = index.deref(item.find("BlockVector/BlockVectorItem"))
    raw = index.blob(block.find("FormattedTextData")) if block is not None else None
    return text_from_blob(raw) if raw else ""


def _overlaps(clip: _Clip, chosen: list[_Clip]) -> bool:
    return any(clip.start < other.end - 1e-3 and other.start < clip.end - 1e-3 for other in chosen)


# Trilha com mais textos e a da legenda; de outra trilha so entra o que nao fica por cima dela
# (legenda continuada em V5 entra, titulo por cima da legenda nao).
def _merge_tracks(tracks: list[tuple[int, list[_Clip]]]) -> tuple[list[_Clip], list[int]]:
    ranked = sorted((track for track in tracks if track[1]), key=lambda track: -len(track[1]))
    chosen: list[_Clip] = []
    used: list[int] = []
    for number, clips in ranked:
        added = [clip for clip in clips if not _overlaps(clip, chosen)]
        if added:
            chosen.extend(added)
            used.append(number)
    return sorted(chosen, key=lambda clip: clip.start), sorted(used)


def _subtitle_clips(index: _Index, sequence: ET.Element) -> tuple[list[_Clip], list[int]]:
    graphic_tracks = []
    for number, track in enumerate(_tracks(index, sequence, "VideoTrackGroup"), start=1):
        clips = []
        for item in _track_items(index, track, "VideoClipTrackItem"):
            text = _graphic_text(index, item)
            if text:
                clips.append(_Clip(_seconds(item, "Start"), _seconds(item, "End"), text))
        graphic_tracks.append((number, clips))
    merged = _merge_tracks(graphic_tracks)
    if merged[0]:
        return merged

    # Projeto antigo, legenda ainda na trilha de legenda (nunca virou grafico).
    caption_tracks = []
    for number, track in enumerate(_tracks(index, sequence, "DataTrackGroup"), start=1):
        clips = []
        for item in _track_items(index, track, "CaptionDataClipTrackItem"):
            text = _caption_text(index, item)
            if text:
                clips.append(_Clip(_seconds(item, "Start"), _seconds(item, "End"), text))
        caption_tracks.append((number, clips))
    return _merge_tracks(caption_tracks)


# Ultima exportacao da sequencia em video: (arquivo, inicio, fim) em segundos da sequencia.
def _video_export(sequence: ET.Element) -> tuple[str, float, float | None] | None:
    found = None
    for element in sequence.iter("ExportSettings.Info.SaveAsFile"):
        try:
            settings = json.loads(element.text or "")
        except json.JSONDecodeError:
            continue
        out_path = str(settings.get("OutPath") or "")
        if Path(out_path).suffix.lower() in VIDEO_EXTENSIONS:
            start = max(0, int(settings.get("InPoint") or 0)) / TICKS_PER_SECOND
            end = int(settings["OutPoint"]) / TICKS_PER_SECOND if settings.get("OutPoint") else None
            found = (out_path, start, end)
    return found


# SRTs importados no projeto, pelo nome sem extensao: o bruto fica do lado com o mesmo nome.
def _imported_srts(root: ET.Element) -> dict[str, Path]:
    srts = {}
    for element in root.iter("FilePath"):
        path = Path((element.text or "").removeprefix("\\\\?\\"))
        if path.suffix.lower() == ".srt":
            srts.setdefault(path.stem, path)
    return srts


def _with_original_extension(base: Path) -> str | None:
    for extension in ORIGINAL_EXTENSIONS:
        candidate = base.with_name(base.name + extension)
        if candidate.exists():
            return str(candidate)
    return None


# Bruto da sequencia: na pasta escolhida pelo usuario, arquivo com o nome da sequencia
# (Sequencia 43 -> Sequencia 43.mp3); sem pasta, do lado do SRT importado com esse nome.
def _original_for(name: str, srts: dict[str, Path], originals_dir: Path | None) -> str | None:
    if originals_dir is not None:
        found = _with_original_extension(originals_dir / name)
        if found:
            return found
    srt = srts.get(name)
    return _with_original_extension(srt.with_suffix("")) if srt is not None else None


def _to_final_time(clips: list[_Clip], start: float, end: float | None) -> list[Card]:
    cards = []
    for clip in clips:
        if clip.end <= start or (end is not None and clip.start >= end):
            continue
        clip_end = clip.end if end is None else min(clip.end, end)
        cards.append(Card(start=round(max(clip.start, start) - start, 3), end=round(clip_end - start, 3), text=clip.text))
    return cards


def read_sequences(project_path: str | Path, originals_dir: str | Path | None = None) -> list[ProjectSequence]:
    root = load_root(project_path)
    index = _Index(root)
    srts = _imported_srts(root)
    sequences = []
    for sequence in root.findall("Sequence"):
        name = sequence.findtext("Name") or ""
        clips, tracks = _subtitle_clips(index, sequence)
        if not clips:
            continue
        export = _video_export(sequence)
        final_path, start, end = export if export else (None, 0.0, None)
        cards = _to_final_time(clips, start, end)
        if not cards:
            # Legendas todas fora do trecho exportado: nao ha video final pra comparar.
            continue
        sequences.append(
            ProjectSequence(
                name=name,
                cards=cards,
                final_path=final_path if final_path and Path(final_path).exists() else None,
                original_path=_original_for(name, srts, Path(originals_dir) if originals_dir else None),
                tracks=tracks,
            )
        )
    return sequences


def sequence_cards(project_path: str | Path, name: str) -> list[Card]:
    for sequence in read_sequences(project_path):
        if sequence.name == name:
            return sequence.cards
    raise ProjectError(f"A sequencia '{name}' nao tem legenda em grafico (ou na trilha de legenda) no projeto.")
