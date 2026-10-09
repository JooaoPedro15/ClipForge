import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from cortes.timebase import Rate
from cortes.xmeml_template import TemplateError, load_template, parse_template

FIXTURE = Path(__file__).parent / "fixtures" / "molde_exemplo.xml"


def fixture_root() -> ET.Element:
    return ET.parse(FIXTURE).getroot()


def main_tracks(root: ET.Element) -> list[ET.Element]:
    sequence = root.find("sequence")
    return sequence.findall("media/video/track") + sequence.findall("media/audio/track")


class LoadTemplateTest(unittest.TestCase):
    def setUp(self):
        self.template = load_template(FIXTURE)

    def test_reads_sequence_rate_and_source(self):
        self.assertEqual(self.template.rate, Rate(30, True))
        self.assertEqual(self.template.source_file_id, "file-1")
        self.assertEqual(self.template.version, "4")

    def test_prototypes_are_the_first_clip_of_each_track(self):
        found = [(p.kind, p.track, p.element.get("id"), p.from_source) for p in self.template.prototypes]
        self.assertEqual(
            found,
            [
                ("video", 1, "clipitem-1", True),
                ("video", 2, "clipitem-3", True),
                ("video", 3, "clipitem-5", False),
                ("audio", 1, "clipitem-7", True),
                ("audio", 2, "clipitem-9", True),
                ("audio", 3, "clipitem-11", False),
            ],
        )

    def test_prototypes_keep_filters_but_only_reference_files_and_nests(self):
        webcam = self.template.prototypes[1].element
        self.assertEqual([f.findtext("effect/effectid") for f in webcam.findall("filter")], ["basic", "Lumetri"])
        for proto in self.template.prototypes:
            for tag in ("file", "sequence"):
                child = proto.element.find(tag)
                if child is not None:
                    self.assertEqual(len(child), 0, f"{proto.element.get('id')} tem <{tag}> completo")

    def test_collects_full_definitions(self):
        self.assertEqual(set(self.template.definitions), {"file:file-1", "sequence:sequence-2", "file:file-2"})
        self.assertEqual(
            self.template.definitions["file:file-1"].findtext("pathurl"),
            "file://localhost/X%3a/Bruto/bruto%20antigo.mp4",
        )

    def test_gap_and_next_id(self):
        self.assertEqual(self.template.gap_frames, 600)
        self.assertEqual(self.template.next_id, 101)


class TemplateErrorsTest(unittest.TestCase):
    def test_rejects_file_that_is_not_xmeml(self):
        with self.assertRaisesRegex(TemplateError, "xmeml"):
            parse_template(ET.fromstring("<projeto/>"))

    def test_rejects_template_without_loop_in_v3(self):
        root = fixture_root()
        loop_track = main_tracks(root)[2]
        for clip in loop_track.findall("clipitem"):
            loop_track.remove(clip)
        with self.assertRaisesRegex(TemplateError, "V3"):
            parse_template(root)

    def test_rejects_loop_that_does_not_start_with_the_first_clip(self):
        root = fixture_root()
        main_tracks(root)[2].find("clipitem").find("start").text = "30"
        with self.assertRaisesRegex(TemplateError, "comecar junto"):
            parse_template(root)

    def test_rejects_v2_pointing_to_another_file(self):
        root = fixture_root()
        main_tracks(root)[1].find("clipitem").find("file").set("id", "file-99")
        with self.assertRaisesRegex(TemplateError, "mesmo bruto"):
            parse_template(root)

    def test_default_gap_when_template_has_one_clip(self):
        root = fixture_root()
        for track in main_tracks(root):
            for clip in track.findall("clipitem"):
                if clip.findtext("start") == "2400":
                    track.remove(clip)
        self.assertEqual(parse_template(root).gap_frames, 300)  # 10s em 29,97
