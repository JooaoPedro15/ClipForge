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

    def _clip(self, start: float, end: float, components: list[str], subclip: str | None = None) -> str:
        chain, item = self._next(), self._next()
        motion = self._next()
        self.objects.append(f'<VideoFilterComponent ObjectID="{motion}"><MatchName>AE.ADBE Motion</MatchName></VideoFilterComponent>')
        listed = "".join(f'<Component Index="{i}" ObjectRef="{ref}"/>' for i, ref in enumerate([motion, *components]))
        self.objects.append(f'<VideoComponentChain ObjectID="{chain}"><ComponentChain><Components>{listed}</Components></ComponentChain></VideoComponentChain>')
        # Premiere nao grava valor padrao: clipe no inicio da sequencia vem sem <Start>.
        start_tag = f"<Start>{ticks(start)}</Start>" if start else ""
        sub_tag = f'<SubClip ObjectRef="{subclip}"/>' if subclip else ""
        self.objects.append(
            f'<VideoClipTrackItem ObjectID="{item}"><ClipTrackItem><ComponentOwner><Components ObjectRef="{chain}"/></ComponentOwner>'
            f"<TrackItem>{start_tag}<End>{ticks(end)}</End></TrackItem>{sub_tag}</ClipTrackItem></VideoClipTrackItem>"
        )
        return item

    def media_clip(self, start: float, end: float, source: str, source_in: float, scale: float | None = 100.0) -> str:
        """Clipe da gravacao: SubClip -> VideoClip (entrada/saida) -> VideoMediaSource -> Media, com Escala do Movimento."""
        media_uid = f"media-{self._next()}"
        media_source, video_clip, subclip = self._next(), self._next(), self._next()
        self.objects.append(f'<Media ObjectUID="{media_uid}"><FilePath>{source}</FilePath><ActualMediaFilePath>{source}</ActualMediaFilePath></Media>')
        self.objects.append(f'<VideoMediaSource ObjectID="{media_source}"><MediaSource><Media ObjectURef="{media_uid}"/></MediaSource></VideoMediaSource>')
        self.objects.append(
            f'<VideoClip ObjectID="{video_clip}"><Clip><Source ObjectRef="{media_source}"/>'
            f"<OutPoint>{ticks(source_in + end - start)}</OutPoint><InPoint>{ticks(source_in)}</InPoint></Clip></VideoClip>"
        )
        self.objects.append(f'<SubClip ObjectID="{subclip}"><Clip ObjectRef="{video_clip}"/></SubClip>')
        components = []
        if scale is not None:
            # Como no Premiere: Escala e o parametro 2 do Movimento; o 4 e a caixinha "escala uniforme" (true).
            param, uniform, motion = self._next(), self._next(), self._next()
            self.objects.append(
                f'<VideoComponentParam ObjectID="{param}"><Name>Escala</Name><ParameterID>2</ParameterID>'
                f"<StartKeyframe>-91445760000000000,{scale},0,0,0,0,0,0</StartKeyframe></VideoComponentParam>"
            )
            self.objects.append(
                f'<VideoComponentParam ObjectID="{uniform}"><Name> </Name><ParameterID>4</ParameterID>'
                f"<StartKeyframe>-91445760000000000,true,0,0,0,0,0,0</StartKeyframe></VideoComponentParam>"
            )
            self.objects.append(
                f'<VideoFilterComponent ObjectID="{motion}"><Component><Params><Param Index="0" ObjectRef="{uniform}"/>'
                f'<Param Index="1" ObjectRef="{param}"/></Params></Component><MatchName>AE.ADBE Motion</MatchName></VideoFilterComponent>'
            )
            components.append(motion)
        return self._clip(start, end, components, subclip)

    def audio(self, start: float, end: float) -> str:
        item = self._next()
        start_tag = f"<Start>{ticks(start)}</Start>" if start else ""
        self.objects.append(
            f'<AudioClipTrackItem ObjectID="{item}"><ClipTrackItem><TrackItem>{start_tag}<End>{ticks(end)}</End>'
            f"</TrackItem></ClipTrackItem></AudioClipTrackItem>"
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

    def sequence(
        self,
        name: str,
        video_tracks: list[list[str]],
        caption_tracks: list[list[str]] = (),
        export: dict | None = None,
        frame: str = "0,0,1920,1080",
        audio_tracks: list[list[str]] = (),
    ):
        groups = []
        for tag, track_tag, tracks, wrapper in (
            ("VideoTrackGroup", "VideoClipTrack", video_tracks, ""),
            ("DataTrackGroup", "CaptionDataClipTrack", caption_tracks, "DataClipTrack"),
            ("AudioTrackGroup", "AudioClipTrack", audio_tracks, ""),
        ):
            uids = [self._track(track_tag, items, wrapper) for items in tracks]
            group = self._next()
            listed = "".join(f'<Track Index="{i}" ObjectURef="{uid}"/>' for i, uid in enumerate(uids))
            extra = f"<FrameRect>{frame}</FrameRect>" if tag == "VideoTrackGroup" else ""
            self.objects.append(f'<{tag} ObjectID="{group}"><TrackGroup><Tracks>{listed}</Tracks></TrackGroup>{extra}</{tag}>')
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

    def test_chosen_folder_matches_the_raw_file_by_sequence_name(self):
        brutos = self.tmp / "audios legendas"
        brutos.mkdir()
        (brutos / "Sequência 43.mp3").write_bytes(b"fake")
        project = FakeProject()
        project.sequence("Sequência 43", [[project.graphic(0.0, 1.0, "oi")]])
        project.sequence("Sequência 44", [[project.graphic(0.0, 1.0, "tchau")]])
        path = project.write(self.tmp / "p.prproj")

        found = {sequence.name: sequence.original_path for sequence in premiere_project.read_sequences(path, brutos)}

        self.assertEqual(found, {"Sequência 43": str(brutos / "Sequência 43.mp3"), "Sequência 44": None})
        self.assertIsNone(premiere_project.read_sequences(path)[0].original_path)
        # Varios mp3 escolhidos a mao: cada um vai pra sequencia com o mesmo nome (maiuscula nao importa).
        (brutos / "sequência 44.MP3").write_bytes(b"fake")
        chosen = [brutos / "Sequência 43.mp3", brutos / "sequência 44.MP3"]
        found = {sequence.name: sequence.original_path for sequence in premiere_project.read_sequences(path, chosen)}
        self.assertEqual(found, {"Sequência 43": str(chosen[0]), "Sequência 44": str(chosen[1])})

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

    def test_corrupted_compressed_project_is_a_clear_error(self):
        data = gzip.compress(b"<PremiereData>" + b"<a>texto qualquer</a>" * 400 + b"</PremiereData>")
        corrupted = self.tmp / "corrompido.prproj"
        corrupted.write_bytes(data[:40] + bytes(byte ^ 0x5A for byte in data[40:80]) + data[80:])

        with self.assertRaises(premiere_project.ProjectError):
            premiere_project.read_video_edits(corrupted)


class ReadVideoEditsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_clips_bring_source_entry_and_motion_scale(self):
        project = FakeProject()
        bruto = r"E:\Bruto\2026-10-05 14-50-31.mp4"
        top = [project.media_clip(0.0, 3.5, bruto, 71.91, scale=62.7)]
        bottom = [project.media_clip(0.0, 3.5, bruto, 71.91), project.media_clip(3.5, 4.5, bruto, 93.93, scale=170.0)]
        legenda = [project.graphic(0.0, 1.0, "oi gente")]
        project.sequence("Sequência 41", [bottom, top, legenda], frame="0,0,1080,1920")
        project.sequence("So legenda", [[project.graphic(0.0, 1.0, "nada")]])

        (edit,) = premiere_project.read_video_edits(project.write(self.tmp / "p.prproj"))

        self.assertEqual((edit.name, edit.vertical), ("Sequência 41", True))
        rows = [(c.track, c.start, c.end, c.source_in, c.source_out, c.scale) for c in edit.clips]
        self.assertEqual(
            rows,
            [(1, 0.0, 3.5, 71.91, 75.41, 100.0), (1, 3.5, 4.5, 93.93, 94.93, 170.0), (2, 0.0, 3.5, 71.91, 75.41, 62.7)],
        )
        self.assertEqual(edit.clips[0].source, bruto)

    def test_sequence_duration_is_the_last_item_of_any_track(self):
        project = FakeProject()
        bruto = r"E:\Bruto\a.mp4"
        video = [project.media_clip(0.0, 10.0, bruto, 0.0)]
        legenda = [project.graphic(9.0, 12.5, "fim")]
        project.sequence("Longo", [video, legenda], audio_tracks=[[project.audio(0.0, 13.25)]])

        (edit,) = premiere_project.read_video_edits(project.write(self.tmp / "p.prproj"))

        self.assertEqual(edit.duration, 13.25)

    def test_last_video_export_gives_the_file_and_the_range(self):
        project = FakeProject()
        bruto = r"E:\Bruto\a.mp4"
        exported = Path(r"D:\Prontos\ela enfiou a mao.mp4")
        project.sequence("Sequência 03", [[project.media_clip(0.0, 30.0, bruto, 0.0)]], export=export_settings(exported, 5.0, 20.5))
        project.sequence("Sem fim", [[project.media_clip(0.0, 8.0, bruto, 0.0)]], export={"OutPath": r"D:\Prontos\todo.mp4"})
        project.sequence("Nunca exportada", [[project.media_clip(0.0, 4.0, bruto, 0.0)]])

        edits = {edit.name: edit for edit in premiere_project.read_video_edits(project.write(self.tmp / "p.prproj"))}

        self.assertEqual(edits["Sequência 03"].export, (str(exported), 5.0, 20.5))
        self.assertEqual(edits["Sem fim"].export, (r"D:\Prontos\todo.mp4", 0.0, 8.0))
        self.assertIsNone(edits["Nunca exportada"].export)

    def test_images_and_clips_without_motion(self):
        project = FakeProject()
        project.sequence("Longo", [[project.media_clip(0.0, 2.0, r"E:\Bruto\a.mp4", 10.0, scale=None), project.media_clip(2.0, 3.0, r"E:\Bruto\capa.png", 0.0)]])

        (edit,) = premiere_project.read_video_edits(project.write(self.tmp / "p.prproj"))

        self.assertFalse(edit.vertical)
        self.assertEqual([(c.source, c.scale) for c in edit.clips], [(r"E:\Bruto\a.mp4", None)])


if __name__ == "__main__":
    unittest.main()
