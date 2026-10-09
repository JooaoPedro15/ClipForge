import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from cortes.media import SourceMedia
from cortes.timebase import Rate
from cortes.xmeml_template import load_template
from cortes.xmeml_writer import ClipSpec, build_xml, to_pathurl, write_xml

FIXTURE = Path(__file__).parent / "fixtures" / "molde_exemplo.xml"
SOURCE = SourceMedia("E:\\Bruto\\novo bruto.mp4", 7298.0, 60.0, 3840, 1080, 4)
CLIPS = [ClipSpec(100.0, 175.0, "Abertura", 7.5), ClipSpec(175.0, 300.0)]
NTSC = Rate(30, True)
GAP = 600  # espaco entre clipes no molde de exemplo
FIRST_LENGTH = 5245 - 2997  # 100s..175s em quadros
SECOND_LENGTH = 8991 - 5245  # 175s..300s


def tracks(root: ET.Element) -> list[ET.Element]:
    sequence = root.find("sequence")
    return sequence.findall("media/video/track") + sequence.findall("media/audio/track")


def top_level_items(root: ET.Element) -> list[ET.Element]:
    return [clip for track in tracks(root) for clip in track.findall("clipitem")]


class BuildXmlTest(unittest.TestCase):
    def setUp(self):
        self.root = build_xml(load_template(FIXTURE), SOURCE, CLIPS, "novo bruto - Cortes")

    def test_one_item_per_track_per_clip(self):
        self.assertEqual([len(track.findall("clipitem")) for track in tracks(self.root)], [2, 2, 2, 2, 2, 2])

    def test_items_come_before_enabled_and_locked(self):
        v1 = tracks(self.root)[0]
        self.assertEqual([child.tag for child in v1], ["clipitem", "clipitem", "enabled", "locked"])

    def test_first_clip_times_and_ticks(self):
        first = tracks(self.root)[0].find("clipitem")
        self.assertEqual([first.findtext(t) for t in ("start", "end", "in", "out")], ["0", str(FIRST_LENGTH), "2997", "5245"])
        self.assertEqual(first.findtext("pproTicksIn"), str(NTSC.to_ticks(2997)))
        self.assertEqual(first.findtext("pproTicksOut"), str(NTSC.to_ticks(5245)))

    def test_second_clip_starts_after_template_gap(self):
        second = tracks(self.root)[0].findall("clipitem")[1]
        self.assertEqual(second.findtext("start"), str(FIRST_LENGTH + GAP))
        self.assertEqual(second.findtext("in"), "5245")

    def test_source_items_follow_new_source_name_and_length(self):
        first = tracks(self.root)[0].find("clipitem")
        self.assertEqual(first.findtext("name"), "novo bruto.mp4")
        self.assertEqual(first.findtext("duration"), str(NTSC.to_frames(7298.0)))

    def test_loop_keeps_template_in_and_follows_clip_length(self):
        loops = tracks(self.root)[2].findall("clipitem")
        self.assertEqual(
            [(c.findtext("in"), c.findtext("out")) for c in loops], [("0", str(FIRST_LENGTH)), ("0", str(SECOND_LENGTH))]
        )
        self.assertEqual(loops[0].findtext("pproTicksOut"), str(NTSC.to_ticks(FIRST_LENGTH)))

    def test_ids_are_unique_and_links_point_to_items_of_the_same_clip(self):
        ids = [clip.get("id") for clip in self.root.iter("clipitem")]
        self.assertEqual(len(ids), len(set(ids)))
        top_ids = {clip.get("id") for clip in top_level_items(self.root)}
        for track in tracks(self.root):
            for number, item in enumerate(track.findall("clipitem"), 1):
                for link in item.findall("link"):
                    self.assertIn(link.findtext("linkclipref"), top_ids)
                    self.assertEqual(link.findtext("clipindex"), str(number))
        v1_second = tracks(self.root)[0].findall("clipitem")[1]
        a1_second = tracks(self.root)[3].findall("clipitem")[1]
        refs = {(link.findtext("mediatype"), link.findtext("trackindex")): link.findtext("linkclipref") for link in v1_second.findall("link")}
        self.assertEqual(refs[("audio", "1")], a1_second.get("id"))
        self.assertEqual(refs[("video", "1")], v1_second.get("id"))

    def test_source_file_defined_once_with_new_path_and_rate(self):
        full = [f for f in self.root.iter("file") if f.get("id") == "file-1" and len(f)]
        self.assertEqual(len(full), 1)
        self.assertEqual(full[0].findtext("pathurl"), "file://localhost/E%3a/Bruto/novo%20bruto.mp4")
        self.assertEqual(full[0].findtext("name"), "novo bruto.mp4")
        self.assertEqual(full[0].findtext("duration"), "437880")
        self.assertEqual(full[0].findtext("rate/timebase"), "60")
        self.assertIs(tracks(self.root)[0].find("clipitem").find("file"), full[0])

    def test_loop_nest_and_lowthird_defined_once(self):
        nests = [s for s in self.root.iter("sequence") if s.get("id") == "sequence-2" and len(s)]
        lowthirds = [f for f in self.root.iter("file") if f.get("id") == "file-2" and len(f)]
        self.assertEqual((len(nests), len(lowthirds)), (1, 1))

    def test_markers_name_each_clip(self):
        markers = self.root.find("sequence").findall("marker")
        self.assertEqual(
            [(m.findtext("name"), m.findtext("comment"), m.findtext("in"), m.findtext("out")) for m in markers],
            [("01 - Abertura", "nota 7.5/10", "0", "-1"), ("02", "", str(FIRST_LENGTH + GAP), "-1")],
        )

    def test_sequence_name_duration_and_new_uuid(self):
        sequence = self.root.find("sequence")
        self.assertEqual(sequence.findtext("name"), "novo bruto - Cortes")
        self.assertEqual(sequence.findtext("duration"), str(FIRST_LENGTH + GAP + SECOND_LENGTH))
        self.assertNotEqual(sequence.findtext("uuid"), "00000000-0000-0000-0000-000000000001")


class BuildXmlErrorsTest(unittest.TestCase):
    def setUp(self):
        self.template = load_template(FIXTURE)

    def test_rejects_empty_clip_list(self):
        with self.assertRaisesRegex(ValueError, "Nenhum clipe"):
            build_xml(self.template, SOURCE, [], "x")

    def test_rejects_clip_without_duration(self):
        with self.assertRaisesRegex(ValueError, "sem duracao"):
            build_xml(self.template, SOURCE, [ClipSpec(10.0, 10.0)], "x")

    def test_rejects_source_with_fewer_audio_streams_than_template_uses(self):
        mono = SourceMedia("E:\\a.mp4", 600.0, 60.0, 3840, 1080, 1)
        with self.assertRaisesRegex(ValueError, "faixa de audio 2"):
            build_xml(self.template, mono, CLIPS, "x")

    def test_rejects_clip_longer_than_the_template_loop(self):
        # O loop do molde tem 25506 quadros (~851s); um clipe de 900s passaria do fim e ficaria preto.
        with self.assertRaisesRegex(ValueError, "loop"):
            build_xml(self.template, SOURCE, [ClipSpec(0.0, 900.0)], "x")


class WriteXmlTest(unittest.TestCase):
    def test_writes_declaration_doctype_and_parses_back(self):
        with tempfile.TemporaryDirectory() as folder:
            out = write_xml(load_template(FIXTURE), SOURCE, CLIPS, Path(folder) / "saida.xml", "x")
            text = out.read_text(encoding="utf-8")
            self.assertTrue(text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">'))
            self.assertEqual(ET.parse(out).getroot().tag, "xmeml")


class ToPathurlTest(unittest.TestCase):
    def test_windows_path_with_spaces(self):
        self.assertEqual(
            to_pathurl("E:\\Bruto\\2026-07-28 23-40-19.mp4"), "file://localhost/E%3a/Bruto/2026-07-28%2023-40-19.mp4"
        )

    def test_accents_and_apostrophe_are_percent_encoded(self):
        self.assertEqual(to_pathurl("D:\\Vídeos\\d'agua.mp4"), "file://localhost/D%3a/V%C3%ADdeos/d%27agua.mp4")
