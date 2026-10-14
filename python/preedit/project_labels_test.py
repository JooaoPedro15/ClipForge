import unittest

from premiere_project import ClipEdit, SequenceEdit

from preedit.project_labels import labels_from_sequences, merge_ranges
from preedit.types import Range, Zoom

BRUTO = r"E:\Bruto\2026-10-05 14-50-31.mp4"


def clip(track, start, end, source_in, scale=100.0, source=BRUTO, speed=1.0):
    return ClipEdit(track, start, end, source, source_in, round(source_in + (end - start) * speed, 3), scale)


class LabelsTest(unittest.TestCase):
    def test_short_keeps_every_track_and_zooms_come_from_the_zoom_track(self):
        # V1: recorte com zooms de corte; V2: a mesma gravacao reduzida no topo, com um trecho so dela em 100%
        # (troca de layout, nao zoom: a trilha do zoom e a que tem mais zooms).
        v1 = [clip(1, 0.0, 3.5, 71.91), clip(1, 3.5, 4.5, 93.93, scale=170.0), clip(1, 4.5, 6.0, 96.4), clip(1, 6.0, 6.8, 97.9, scale=140.0)]
        v2 = [clip(2, 0.0, 3.5, 71.91, 62.7), clip(2, 6.8, 7.8, 130.0, 100.0)]
        (labels,) = labels_from_sequences([SequenceEdit("Sequência 41", True, v1 + v2)])

        self.assertEqual(labels.format, "short")
        self.assertEqual(labels.kept, [Range(71.91, 75.41), Range(93.93, 94.93), Range(96.4, 98.7), Range(130.0, 131.0)])
        self.assertEqual(labels.zooms, [Zoom(93.93, 94.93, 1.7), Zoom(97.9, 98.7, 1.4)])
        self.assertEqual(labels.span, Range(71.91, 131.0))
        self.assertFalse(labels.preedited)

    def test_copies_merge_and_long_videos_have_no_zoom(self):
        first = [clip(1, 0.0, 10.0, 0.0), clip(1, 10.0, 20.0, 30.0)]
        compilation = [clip(1, 0.0, 10.0, 0.0)]  # copia do mesmo trecho
        result = labels_from_sequences([SequenceEdit("Longo", False, first), SequenceEdit("Compilacao", False, compilation)])

        (labels,) = result
        self.assertEqual((labels.format, labels.kept, labels.zooms), ("longo", [Range(0.0, 10.0), Range(30.0, 40.0)], []))
        self.assertEqual(labels.sequences, ["Compilacao", "Longo"])

    def test_speed_changes_are_ignored_and_preedited_sources_are_flagged(self):
        pre = r"E:\Bruto\2026-05-13_16-39-32_preedit.mp4"
        clips = [clip(1, 0.0, 2.0, 5.0, source=pre), clip(1, 2.0, 4.0, 9.0, source=pre, speed=2.0)]
        (labels,) = labels_from_sequences([SequenceEdit("S", False, clips)])

        self.assertEqual(labels.kept, [Range(5.0, 7.0)])
        self.assertTrue(labels.preedited)

    def test_nothing_usable(self):
        self.assertEqual(labels_from_sequences([SequenceEdit("S", False, [clip(1, 0.0, 2.0, 5.0, speed=1.5)])]), [])

    def test_merge_ranges(self):
        merged = merge_ranges([Range(5.0, 6.0), Range(0.0, 2.0), Range(2.03, 3.0)])
        self.assertEqual(merged, [Range(0.0, 3.0), Range(5.0, 6.0)])


if __name__ == "__main__":
    unittest.main()
