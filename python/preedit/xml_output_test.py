import copy
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from cortes.media import SourceMedia
from cortes.xmeml_template import TemplateError

from preedit.editor import EditPlan, Segment
from preedit.molde import default_molde, load_molde, motion_scale, parse_molde
from preedit.xml_output import build_xml, write_xml, zoom_keyframes

FIXTURE = Path(__file__).parent / "fixtures" / "molde_preedit.xml"
SOURCE = SourceMedia(path=r"E:\Bruto\2026-10-14 15-00-00.mp4", duration_sec=900.0, fps=30.0, width=1920, height=1080, audio_streams=2)
# A mesma gravacao depois de uma pausa no OBS: outro arquivo.
SOURCE2 = SourceMedia(path=r"E:\Bruto\2026-10-14 16-00-00.mp4", duration_sec=600.0, fps=30.0, width=1920, height=1080, audio_streams=2)
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

    def test_without_molde_the_sequence_is_the_recording_with_every_audio_track(self):
        molde = default_molde(SOURCE)

        root = build_xml(molde, [(SOURCE, PLAN)], "sem molde")

        self.assertIsNone(molde.zoom)
        self.assertEqual([(p.kind, p.track, p.from_source) for p in molde.template.prototypes], [("video", 1, True), ("audio", 1, True), ("audio", 2, True)])
        self.assertEqual(root.findtext("sequence/media/video/format/samplecharacteristics/width"), "1920")
        self.assertEqual(root.findtext("sequence/media/video/format/samplecharacteristics/height"), "1080")
        self.assertEqual(root.findtext("sequence/rate/timebase"), "30")
        self.assertEqual((len(clipitems(root, "video")), len(clipitems(root, "audio"))), (3, 6))
        self.assertEqual([item.findtext("sourcetrack/trackindex") for item in clipitems(root, "audio")[:4:3]], ["1", "2"])
        self.assertIn("2026-10-14", root.find("sequence/media/video/track/clipitem/file/pathurl").text)

    def test_default_molde_keeps_ntsc_frame_rates(self):
        source = SourceMedia(path=r"E:\Bruto\celular.mp4", duration_sec=60.0, fps=29.97, width=1080, height=1920, audio_streams=1)

        root = build_xml(default_molde(source), [(source, PLAN)], "ntsc")

        self.assertEqual((root.findtext("sequence/rate/timebase"), root.findtext("sequence/rate/ntsc")), ("30", "TRUE"))
        self.assertEqual(len(clipitems(root, "audio")), 3)


class ZoomKeyframesTest(unittest.TestCase):
    def test_zoom_keyframes_enter_and_keep_approaching(self):
        keys = zoom_keyframes((100.0, (0.0, 0.0)), (150.0, (0.12, -0.21)), 90, 30.0)

        self.assertEqual([when for when, _ in keys], [0, 12, 89])
        scale, center = keys[-1][1]
        self.assertAlmostEqual(scale, 165.0)
        self.assertEqual((round(center[0], 3), round(center[1], 3)), (0.156, -0.273))
        # O ponto que nao se mexe entre o normal e o zoom (o rosto) continua parado enquanto aproxima.
        d = ((0.0 - 0.12) / 50, (0.0 + 0.21) / 50)
        fixed = {(round(c[0] + s * d[0], 6), round(c[1] + s * d[1], 6)) for _, (s, c) in keys}
        self.assertEqual(len(fixed), 1)

    def test_short_zoom_stays_still(self):
        self.assertEqual(zoom_keyframes((100.0, (0.0, 0.0)), (150.0, (0.12, -0.21)), 12, 30.0), [])

    def test_xml_with_approaching_zoom_has_keyframes(self):
        plan = EditPlan(segments=[Segment(10.0, 12.0), Segment(12.0, 15.0, 1.5)], markers=[], duration=5.0, zooms=1)

        approaching = clipitems(build_xml(load_molde(FIXTURE), [(SOURCE, plan)], "zoom", zoom_style="aproximando"), "video")[1]
        still = clipitems(build_xml(load_molde(FIXTURE), [(SOURCE, plan)], "zoom", zoom_style="seco"), "video")[1]

        scale_keys = approaching.findall("filter/effect/parameter[parameterid='scale']/keyframe")
        self.assertEqual([key.findtext("when") for key in scale_keys], ["0", "12", "89"])
        self.assertEqual([key.findtext("value") for key in scale_keys], ["100", "150", "165"])
        self.assertEqual(len(approaching.findall("filter/effect/parameter[parameterid='center']/keyframe")), 3)
        self.assertEqual(still.findall(".//keyframe"), [])

    def test_zoom_level_different_from_the_molde_stays_on_the_molde_line(self):
        # Molde: 100% em (0, 0) -> 150% em (0,12, -0,21). Zoom previsto de 1,2x: o centro vai 40% do caminho,
        # e o ponto que o molde mantem parado (o rosto) continua parado em todos os keyframes.
        plan = EditPlan(segments=[Segment(10.0, 12.0), Segment(12.0, 15.0, 1.2)], markers=[], duration=5.0, zooms=1)
        d = ((0.0 - 0.12) / 50, (0.0 + 0.21) / 50)
        face = (round(0.0 + 100 * d[0], 6), round(0.0 + 100 * d[1], 6))

        for style in ("aproximando", "seco"):
            zoomed = clipitems(build_xml(load_molde(FIXTURE), [(SOURCE, plan)], "zoom", zoom_style=style), "video")[1]
            center = zoomed.find("filter/effect/parameter[parameterid='center']/value")
            self.assertEqual((float(center.findtext("horiz")), float(center.findtext("vert"))), (0.048, -0.084), style)

        zoomed = clipitems(build_xml(load_molde(FIXTURE), [(SOURCE, plan)], "zoom", zoom_style="aproximando"), "video")[1]
        scales = [float(key.findtext("value")) for key in zoomed.findall("filter/effect/parameter[parameterid='scale']/keyframe")]
        centers = [
            (float(key.findtext("value/horiz")), float(key.findtext("value/vert")))
            for key in zoomed.findall("filter/effect/parameter[parameterid='center']/keyframe")
        ]
        fixed = {(round(c[0] + s * d[0], 3), round(c[1] + s * d[1], 3)) for s, c in zip(scales, centers, strict=True)}
        self.assertEqual(fixed, {(round(face[0], 3), round(face[1], 3))})


class BuildXmlTest(unittest.TestCase):
    def test_segments_are_glued_and_the_zoom_goes_on_the_zoom_track(self):
        root = build_xml(load_molde(FIXTURE), [(SOURCE, PLAN)], "gravacao pre-edicao")

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

    def test_two_recordings_make_one_sequence(self):
        root = build_xml(load_molde(FIXTURE), [(SOURCE, PLAN), (SOURCE2, PLAN)], "duas")

        video = clipitems(root, "video")
        self.assertEqual(len(video), 6)
        self.assertEqual([clip.find("file").get("id") for clip in video], ["file-1"] * 3 + ["file-1-2"] * 3)
        self.assertEqual([int(clip.findtext("start")) for clip in video][3:], [240, 300, 330])
        names = {f.get("id"): f.findtext("name") for f in root.iter("file") if f.find("pathurl") is not None}
        self.assertEqual(names, {"file-1": "2026-10-14 15-00-00.mp4", "file-1-2": "2026-10-14 16-00-00.mp4"})
        self.assertEqual(root.findtext("sequence/duration"), "480")
        self.assertEqual([marker.findtext("in") for marker in root.findall("sequence/marker")], ["90", "330"])

    def test_each_recording_has_its_own_master_clip(self):
        # Exportacao real do Premiere traz <masterclipid> em todo clipe: o segundo bruto nao pode dizer que e o primeiro.
        molde = ET.parse(FIXTURE).getroot()
        for clip in molde.iter("clipitem"):
            ET.SubElement(clip, "masterclipid").text = "masterclip-1"

        root = build_xml(parse_molde(molde), [(SOURCE, PLAN), (SOURCE2, PLAN)], "duas")

        for kind in ("video", "audio"):
            self.assertEqual([clip.findtext("masterclipid") for clip in clipitems(root, kind)], ["masterclip-1"] * 3 + ["masterclip-1-2"] * 3)

    def test_source_with_fewer_audio_tracks_is_a_clear_error(self):
        single = SourceMedia(path=r"E:\Bruto\celular.mp4", duration_sec=60.0, fps=30.0, width=1920, height=1080, audio_streams=1)

        with self.assertRaisesRegex(ValueError, "celular.mp4"):
            build_xml(default_molde(SOURCE), [(SOURCE, PLAN), (single, PLAN)], "faixas")

    def test_write_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_xml(load_molde(FIXTURE), [(SOURCE, PLAN)], Path(tmp) / "saida.xml", "teste")
            self.assertTrue(out.read_text(encoding="utf-8").startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>'))


if __name__ == "__main__":
    unittest.main()
