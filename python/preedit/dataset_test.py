import unittest

from preedit.audio import Loudness
from preedit.dataset import build_examples, coverage, overlap
from preedit.types import Range, RecordingLabels, Zoom


def words_from(items):
    return [{"word": f" {text}", "start": start, "end": end} for text, start, end in items]


# Tres frases: [0-1], [3-4] e [6-7.5]. O usuario tirou a do meio e deu zoom no fim da ultima (6,6-7,5).
WORDS = words_from(
    [("eu", 0.0, 0.4), ("fui", 0.55, 1.0), ("hum", 3.0, 3.4), ("tipo", 3.5, 4.0), ("e", 6.0, 6.5), ("gritei!", 6.65, 7.5)]
)
LOUD = Loudness(0.1, [-30.0] * 80)


class DatasetTest(unittest.TestCase):
    def labels(self, preedited=False):
        kept = [Range(0.0, 1.3), Range(5.8, 7.5)]
        return RecordingLabels("gravacao.mp4", "longo", kept, [Zoom(6.6, 7.5, 1.7)], preedited, ["S"])

    def test_phrase_labels_follow_what_was_kept(self):
        examples = build_examples(self.labels(), WORDS, LOUD, {})

        self.assertEqual([row["y"] for row in examples["phrase"]], [1, 0, 1])
        self.assertEqual((examples["recording"], examples["format"]), ("gravacao.mp4", "longo"))

    def test_pause_labels_are_the_pause_that_stayed(self):
        examples = build_examples(self.labels(), WORDS, LOUD, {})

        # So pausas entre palavras que ficaram: 0,4-0,55 (ficou inteira) e 6,5-6,65 (inteira).
        self.assertEqual([round(row["y"]) for row in examples["pause"]], [150, 150])
        self.assertEqual(build_examples(self.labels(preedited=True), WORDS, LOUD, {})["pause"], [])

    def test_zoom_labels_and_stats(self):
        examples = build_examples(self.labels(), WORDS, LOUD, {})

        self.assertEqual([(row["y"], row["level"]) for row in examples["zoom"]], [(0, None), (1, 1.7)])
        stats = examples["stats"]
        self.assertAlmostEqual(stats["final_sec"], 3.0)
        self.assertEqual((stats["zooms"], stats["zoom_levels"]), (1, [1.7]))
        self.assertAlmostEqual(stats["zoom_durations"][0], 0.9)

    def test_overlap_and_coverage(self):
        ranges = [Range(0.0, 1.0), Range(2.0, 3.0)]
        self.assertAlmostEqual(overlap(0.5, 2.5, ranges), 1.0)
        self.assertAlmostEqual(coverage(0.5, 2.5, ranges), 0.5)
        self.assertEqual(coverage(1.0, 1.0, ranges), 0.0)


if __name__ == "__main__":
    unittest.main()
