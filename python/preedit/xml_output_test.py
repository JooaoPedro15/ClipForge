import copy
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from cortes.media import SourceMedia
from cortes.xmeml_template import TemplateError

from preedit.editor import EditPlan, Segment
from preedit.molde import load_molde, motion_scale, parse_molde
from preedit.xml_output import build_xml, write_xml

FIXTURE = Path(__file__).parent / "fixtures" / "molde_preedit.xml"
SOURCE = SourceMedia(path=r"E:\Bruto\2026-10-14 15-00-00.mp4", duration_sec=900.0, fps=30.0, width=1920, height=1080, audio_streams=2)
PLAN = EditPlan(
    segments=[Segment(10.0, 12.0), Segment(12.0, 13.0, 1.5), Segment(20.0, 25.0)],
    markers=[(3.0, "sem graca")],
    duration=8.0,
    zooms=1,
)


def clipitems(root: ET.Element, kind: str) -> list[ET.Element]:
    return root.findall(f"sequence/media/{kind}/track/clipitem")


def with_intro(root: ET.Element) -> ET.Element:
    """Molde com uma vinheta de 3 s (video e audio) antes da gravacao."""
    root = copy.deepcopy(root)
    for clip in root.iter("clipitem"):
        for tag in ("start", "end"):
            clip.find(tag).text = str(int(clip.findtext(tag)) + 90)
    for kind, number in (("video", 9), ("audio", 10)):
        intro = ET.fromstring(
            f"<clipitem id='clipitem-{number}'><name>vinheta.mp4</name><duration>90</duration>"
            "<rate><timebase>30</timebase></rate><start>0</start><end>90</end><in>0</in><out>90</out>"
            "<file id='file-9'><name>vinheta.mp4</name><pathurl>file://localhost/E%3a/vinheta.mp4</pathurl></file></clipitem>"
        )
        root.find(f"sequence/media/{kind}/track").insert(0, intro)
    return root


class MoldeTest(unittest.TestCase):
    def test_finds_the_zoom_track_center_and_normal_scale(self):
        molde = load_molde(FIXTURE)

        self.assertEqual((molde.zoom.track, molde.zoom.base_scale, molde.zoom.center), (1, 100.0, (0.12, -0.21)))
        self.assertEqual(molde.template.gap_frames, 0)
        self.assertEqual([(p.kind, p.track, p.from_source) for p in molde.template.prototypes], [("video", 1, True), ("audio", 1, True)])

    def test_molde_without_zoom_and_without_source(self):
        root = ET.parse(FIXTURE).getroot()
        no_zoom = copy.deepcopy(root)
        track = no_zoom.find("sequence/media/video/track")
        track.remove(track.findall("clipitem")[1])
        self.assertIsNone(parse_molde(no_zoom).zoom)

        with self.assertRaises(TemplateError):
            parse_molde(ET.fromstring("<xmeml version='4'><sequence><rate><timebase>30</timebase></rate><media/></sequence></xmeml>"))

    def test_intro_before_the_recording_is_not_the_source(self):
        molde = parse_molde(with_intro(ET.parse(FIXTURE).getroot()))

        self.assertEqual(molde.template.source_file_id, "file-1")
        self.assertEqual([(p.kind, p.track, p.from_source) for p in molde.template.prototypes], [("video", 1, True), ("audio", 1, True)])
        self.assertEqual(molde.zoom.track, 1)

    def test_track_with_the_recording_not_lined_up_is_a_clear_error(self):
        root = ET.parse(FIXTURE).getroot()
        audio = root.find("sequence/media/audio/track/clipitem")
        audio.find("start").text = "10"

        with self.assertRaisesRegex(TemplateError, "audio 1"):
            parse_molde(root)


class BuildXmlTest(unittest.TestCase):
    def test_segments_are_glued_and_the_zoom_goes_on_the_zoom_track(self):
        root = build_xml(load_molde(FIXTURE), SOURCE, PLAN, "gravacao pre-edicao")

        video = clipitems(root, "video")
        audio = clipitems(root, "audio")
        self.assertEqual(len(video), 3)
        self.assertEqual(len(audio), 3)
        self.assertEqual([(int(c.findtext("start")), int(c.findtext("end"))) for c in video], [(0, 60), (60, 90), (90, 240)])
        self.assertEqual([(int(c.findtext("in")), int(c.findtext("out"))) for c in video], [(300, 360), (360, 390), (600, 750)])
        self.assertEqual([motion_scale(c) for c in video], [100.0, 150.0, 100.0])
        center = video[1].find("filter/effect/parameter[parameterid='center']/value")
        self.assertEqual((center.findtext("horiz"), center.findtext("vert")), ("0.12", "-0.21"))
        self.assertEqual(root.findtext("sequence/name"), "gravacao pre-edicao")
        self.assertEqual(root.findtext("sequence/duration"), "240")
        self.assertEqual([(m.findtext("name"), m.findtext("in")) for m in root.findall("sequence/marker")], [("sem graca", "90")])
        definition = root.find(".//file[pathurl]")
        self.assertEqual(definition.findtext("name"), "2026-10-14 15-00-00.mp4")

    def test_write_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_xml(load_molde(FIXTURE), SOURCE, PLAN, Path(tmp) / "saida.xml", "teste")
            self.assertTrue(out.read_text(encoding="utf-8").startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>'))


if __name__ == "__main__":
    unittest.main()
