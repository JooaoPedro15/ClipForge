import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from cortes.evaluation import (
    compare,
    format_report,
    predicted_boundaries,
    reference_boundaries,
    reference_boundaries_from_root,
)

FIXTURE = Path(__file__).parent / "fixtures" / "molde_exemplo.xml"

PIECES = """<xmeml version="4"><sequence><rate><timebase>30</timebase><ntsc>TRUE</ntsc></rate>
<media><video><track>
<clipitem id="a"><start>0</start><end>100</end><in>0</in><out>100</out></clipitem>
<clipitem id="b"><start>100</start><end>200</end><in>150</in><out>250</out></clipitem>
<clipitem id="c"><start>300</start><end>400</end><in>250</in><out>350</out></clipitem>
</track></video></media></sequence></xmeml>"""


class ReferenceBoundariesTest(unittest.TestCase):
    def test_a_new_clip_starts_where_the_timeline_has_a_gap(self):
        self.assertEqual(reference_boundaries(FIXTURE, 0.0, 1000.0), [160.16])

    def test_glued_pieces_belong_to_the_same_clip(self):
        # a e b estao grudados na linha do tempo (corte interno); c vem depois de um espaco.
        self.assertEqual(reference_boundaries_from_root(ET.fromstring(PIECES), 0.0, 100.0), [8.34])

    def test_only_inside_the_evaluated_trecho(self):
        self.assertEqual(reference_boundaries(FIXTURE, 0.0, 100.0), [])


class CompareTest(unittest.TestCase):
    def test_matches_within_tolerance(self):
        report = compare([222.0, 330.0, 480.0, 700.0], [219.72, 328.56, 525.79, 620.45], 10.0)
        self.assertEqual(report.matches, [(219.72, 222.0), (328.56, 330.0)])
        self.assertEqual((report.precision, report.recall, report.f1), (0.5, 0.5, 0.5))
        self.assertAlmostEqual(report.mean_error, 1.86)

    def test_one_cut_cannot_match_two_reference_boundaries(self):
        self.assertEqual(len(compare([102.0], [100.0, 105.0], 10.0).matches), 1)

    def test_empty_inputs(self):
        report = compare([], [], 10.0)
        self.assertEqual((report.precision, report.recall, report.f1, report.mean_error), (0.0, 0.0, 0.0, None))

    def test_predicted_skips_the_first_clip_start(self):
        self.assertEqual(predicted_boundaries([144.44, 220.0, 330.0], 144.44, 774.0), [220.0, 330.0])

    def test_report_text_lists_each_reference_boundary(self):
        text = format_report(compare([222.0], [219.72, 525.79], 10.0))
        self.assertIn("3:39.72 -> 3:42.00 (+2.3s)", text)
        self.assertIn("8:45.79 -> sem corte perto", text)
