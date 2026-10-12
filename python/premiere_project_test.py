import base64
import gzip
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import premiere_project
from premiere_project import TICKS_PER_SECOND
from style_alignment import Card


def blob(*strings: str) -> str:
    """Imita o flatbuffer do Premiere: cabecalho, depois cada string com tamanho na frente e zero no fim."""
    raw = b"\x0c\x00\x00\x00\x00\x00\x06\x00"
    for text in strings:
        data = text.encode("utf-8")
        raw += struct.pack("<I", len(data)) + data + b"\x00" * (4 - len(data) % 4)
    return base64.b64encode(raw + b"\x06\x00\x08\x00").decode()


def ticks(seconds: float) -> int:
    return round(seconds * TICKS_PER_SECOND)


class FakeProject:
    """Monta um .prproj minimo: objetos soltos na raiz, ligados por ObjectRef/ObjectURef."""

    def __init__(self):
        self.objects: list[str] = []
        self.counter = 100

    def _next(self) -> str:
        self.counter += 1
        return str(self.counter)

    def _text_component(self, text: str, digest: str, empty: bool = False) -> str:
        param, component, style = self._next(), self._next(), self._next()
        value = "" if empty else blob("AvenirNextWorld-Black", text)
        self.objects.append(
            f'<ArbVideoComponentParam ObjectID="{param}"><Name>Texto de origem</Name>'
            f'<StartKeyframeValue Encoding="base64" BinaryHash="{digest}">{value}</StartKeyframeValue></ArbVideoComponentParam>'
        )
        # Estilo vinculado: guarda um "Aa" de exemplo que nao e a legenda.
        style_param = self._next()
        self.objects.append(
            f'<ArbVideoComponentParam ObjectID="{style_param}"><StartKeyframeValue Encoding="base64" '
            f'BinaryHash="estilo">{blob("AvenirNextWorld-Black", "Aa")}</StartKeyframeValue></ArbVideoComponentParam>'
        )
        self.objects.append(
            f'<StyleProjectItem ObjectUID="style-{style}"><Component><Params><Param Index="0" ObjectRef="{style_param}"/>'
            f"</Params></Component><MatchName>AE.ADBE Text</MatchName></StyleProjectItem>"
        )
        self.objects.append(
            f'<VideoFilterComponent ObjectID="{component}"><Component><Params><Param Index="0" ObjectRef="{param}"/></Params>'
            f'<DisplayName>Texto</DisplayName><ParentStyle ObjectURef="style-{style}"/></Component>'
            f"<MatchName>AE.ADBE Text</MatchName></VideoFilterComponent>"
        )
        return component

    def _clip(self, start: float, end: float, components: list[str]) -> str:
        chain, item = self._next(), self._next()
        motion = self._next()
        self.objects.append(f'<VideoFilterComponent ObjectID="{motion}"><MatchName>AE.ADBE Motion</MatchName></VideoFilterComponent>')
        listed = "".join(f'<Component Index="{i}" ObjectRef="{ref}"/>' for i, ref in enumerate([motion, *components]))
        self.objects.append(f'<VideoComponentChain ObjectID="{chain}"><ComponentChain><Components>{listed}</Components></ComponentChain></VideoComponentChain>')
        # Premiere nao grava valor padrao: clipe no inicio da sequencia vem sem <Start>.
        start_tag = f"<Start>{ticks(start)}</Start>" if start else ""
        self.objects.append(
            f'<VideoClipTrackItem ObjectID="{item}"><ClipTrackItem><ComponentOwner><Components ObjectRef="{chain}"/></ComponentOwner>'
            f"<TrackItem>{start_tag}<End>{ticks(end)}</End></TrackItem></ClipTrackItem></VideoClipTrackItem>"
        )
        return item

    def graphic(self, start: float, end: float, text: str, digest: str | None = None, empty: bool = False) -> str:
        return self._clip(start, end, [self._text_component(text, digest or f"h{self._next()}", empty)])

    def video(self, start: float, end: float) -> str:
        return self._clip(start, end, [])

    def caption(self, start: float, end: float, text: str) -> str:
        block, item = self._next(), self._next()
        self.objects.append(
            f'<Block ObjectID="{block}"><FormattedTextData Encoding="base64" BinaryHash="c{block}">'
            f'{blob("LucidaConsole", text)}</FormattedTextData></Block>'
        )
        self.objects.append(
            f'<CaptionDataClipTrackItem ObjectID="{item}"><DataClipTrackItem><ClipTrackItem><TrackItem>'
            f"<Start>{ticks(start)}</Start><End>{ticks(end)}</End></TrackItem></ClipTrackItem></DataClipTrackItem>"
            f'<BlockVector><BlockVectorItem Index="0" ObjectRef="{block}"/></BlockVector></CaptionDataClipTrackItem>'
        )
        return item

    def _track(self, tag: str, items: list[str], wrapper: str = "") -> str:
        uid = f"track-{self._next()}"
        listed = "".join(f'<TrackItem Index="{i}" ObjectRef="{ref}"/>' for i, ref in enumerate(items))
        body = f"<ClipTrack><ClipItems><TrackItems>{listed}</TrackItems></ClipItems></ClipTrack>"
        if wrapper:
            body = f"<{wrapper}>{body}</{wrapper}>"
        self.objects.append(f'<{tag} ObjectUID="{uid}">{body}</{tag}>')
        return uid

    def sequence(self, name: str, video_tracks: list[list[str]], caption_tracks: list[list[str]] = (), export: dict | None = None):
        groups = []
        for tag, track_tag, tracks, wrapper in (
            ("VideoTrackGroup", "VideoClipTrack", video_tracks, ""),
            ("DataTrackGroup", "CaptionDataClipTrack", caption_tracks, "DataClipTrack"),
        ):
            uids = [self._track(track_tag, items, wrapper) for items in tracks]
            group = self._next()
            listed = "".join(f'<Track Index="{i}" ObjectURef="{uid}"/>' for i, uid in enumerate(uids))
            self.objects.append(f'<{tag} ObjectID="{group}"><TrackGroup><Tracks>{listed}</Tracks></TrackGroup></{tag}>')
            groups.append(group)
        export_tag = ""
        if export:
            export_tag = f"<Node><Properties><ExportSettings.Info.SaveAsFile>{json.dumps(export)}</ExportSettings.Info.SaveAsFile></Properties></Node>"
        listed = "".join(f'<TrackGroup Index="{i}"><First>x</First><Second ObjectRef="{g}"/></TrackGroup>' for i, g in enumerate(groups))
        self.objects.append(f'<Sequence ObjectUID="seq-{self._next()}">{export_tag}<Name>{name}</Name><TrackGroups>{listed}</TrackGroups></Sequence>')

    def imported_file(self, path: Path):
        self.objects.append(f'<Media ObjectUID="media-{self._next()}"><FilePath>{path}</FilePath></Media>')

    def write(self, path: Path) -> Path:
        xml = '<?xml version="1.0" encoding="UTF-8"?><PremiereData Version="3">' + "".join(self.objects) + "</PremiereData>"
        path.write_bytes(gzip.compress(xml.encode("utf-8")))
        return path


def export_settings(out_path: Path, start: float, end: float) -> dict:
    return {"OutPath": str(out_path), "InPoint": ticks(start), "OutPoint": ticks(end), "Range": 1}


class ReadSequencesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_graphic_subtitles_come_from_the_subtitle_track_and_its_continuation(self):
        project = FakeProject()
        # Blob com hash repetido vem vazio: o texto esta no primeiro objeto com o mesmo hash.
        subtitles = [
            project.graphic(0.0, 0.5, "eu fui la", digest="repetido"),
            project.graphic(0.5, 1.0, "ignorado", digest="repetido", empty=True),
            project.graphic(1.0, 1.6, "tava\rcheio"),
        ]
        extra = [project.graphic(0.2, 1.4, "MEU TITULO"), project.graphic(1.6, 2.0, "demais")]
        project.sequence("Sequência 42", [[project.video(0.0, 2.0)], subtitles, extra])

        (sequence,) = premiere_project.read_sequences(project.write(self.tmp / "p.prproj"))

        self.assertEqual(sequence.name, "Sequência 42")
        self.assertEqual(
            sequence.cards,
            [Card(0.0, 0.5, "eu fui la"), Card(0.5, 1.0, "eu fui la"), Card(1.0, 1.6, "tava cheio"), Card(1.6, 2.0, "demais")],
        )
        self.assertEqual(sequence.tracks, [2, 3])

    def test_times_follow_the_exported_range_and_files_are_found_next_to_the_imported_srt(self):
        final = self.tmp / "tentando adivinhar.mp4"
        final.write_bytes(b"fake")
        (self.tmp / "Sequência 42.mp3").write_bytes(b"fake")
        project = FakeProject()
        project.imported_file(self.tmp / "Sequência 42.srt")
        project.sequence(
            "Sequência 42",
            [[project.graphic(0.0, 1.0, "fora"), project.graphic(1.0, 2.0, "dentro"), project.graphic(2.5, 3.5, "cortada no fim")]],
            export=export_settings(final, 1.0, 3.0),
        )

        (sequence,) = premiere_project.read_sequences(project.write(self.tmp / "p.prproj"))

        self.assertEqual(sequence.cards, [Card(0.0, 1.0, "dentro"), Card(1.5, 2.0, "cortada no fim")])
        self.assertEqual(sequence.final_path, str(final))
        self.assertEqual(sequence.original_path, str(self.tmp / "Sequência 42.mp3"))

    def test_missing_files_and_audio_exports_are_left_for_the_user_to_pick(self):
        project = FakeProject()
        project.imported_file(self.tmp / "Sequência 7.srt")
        project.sequence(
            "Sequência 7",
            [[project.graphic(0.0, 1.0, "oi")]],
            export=export_settings(self.tmp / "Sequência 7.mp3", 0.0, 1.0),
        )

        (sequence,) = premiere_project.read_sequences(project.write(self.tmp / "p.prproj"))

        self.assertIsNone(sequence.final_path)
        self.assertIsNone(sequence.original_path)

    def test_old_projects_use_the_caption_track_when_there_are_no_graphics(self):
        project = FakeProject()
        project.sequence("Antiga", [[project.video(0.0, 2.0)]], caption_tracks=[[project.caption(0.0, 0.8, "eu fui la"), project.caption(0.8, 1.5, "ontem")]])
        project.sequence("Sem legenda", [[project.video(0.0, 2.0)]])

        sequences = premiere_project.read_sequences(project.write(self.tmp / "p.prproj"))

        self.assertEqual([sequence.name for sequence in sequences], ["Antiga"])
        self.assertEqual(sequences[0].cards, [Card(0.0, 0.8, "eu fui la"), Card(0.8, 1.5, "ontem")])

    def test_sequence_cards_and_errors(self):
        project = FakeProject()
        project.sequence("Sequência 1", [[project.graphic(0.0, 1.0, "oi gente")]])
        path = project.write(self.tmp / "p.prproj")

        self.assertEqual(premiere_project.sequence_cards(path, "Sequência 1"), [Card(0.0, 1.0, "oi gente")])
        with self.assertRaises(premiere_project.ProjectError):
            premiere_project.sequence_cards(path, "Sequência 2")
        broken = self.tmp / "quebrado.prproj"
        broken.write_bytes(gzip.compress(b"<PremiereData>")[:20])
        with self.assertRaises(premiere_project.ProjectError):
            premiere_project.read_sequences(broken)
        with self.assertRaises(premiere_project.ProjectError):
            premiere_project.read_sequences(self.tmp / "nao-existe.prproj")


if __name__ == "__main__":
    unittest.main()
