import unittest

from preedit import features
from preedit.audio import Loudness
from preedit.phrases import build_phrases, phrase_of_words

WORDS = [
    {"word": " entao", "start": 0.0, "end": 0.3},
    {"word": " eu", "start": 0.35, "end": 0.5},
    {"word": " fui", "start": 0.55, "end": 1.0},
    {"word": " e", "start": 2.0, "end": 2.2},
    {"word": " gritei!", "start": 2.3, "end": 3.0},
]
# 30 janelas de 100 ms: -30 dB, com um pico de -10 dB em 2,5-2,7 s.
LOUD = Loudness(0.1, [-30.0] * 25 + [-10.0, -10.0] + [-30.0] * 3)
INTEREST = {0: 4.0, 1: 9.0}


class FeaturesTest(unittest.TestCase):
    def setUp(self):
        self.phrases = build_phrases(WORDS)

    def test_phrase_features(self):
        row = features.phrase_features(self.phrases, 1, LOUD, INTEREST, total=3.0)

        self.assertEqual(len(row), len(features.PHRASE_FEATURES))
        values = dict(zip(features.PHRASE_FEATURES, row, strict=True))
        self.assertAlmostEqual(values["duracao"], 1.0)
        self.assertEqual(values["nota_ia"], 9.0)
        self.assertEqual(values["nota_ia_vizinhas"], 4.0)
        self.assertAlmostEqual(values["volume_pico"], 20.0)
        self.assertEqual(values["exclamacao"], 1.0)
        self.assertAlmostEqual(values["posicao"], 2.0 / 3.0)

    def test_pause_retake_and_zoom_features(self):
        mapping = phrase_of_words(self.phrases)

        pause = dict(zip(features.PAUSE_FEATURES, features.pause_features(WORDS, 2, mapping, LOUD, INTEREST), strict=True))
        self.assertAlmostEqual(pause["pausa_ms"], 1000.0)
        self.assertEqual(pause["nota_ia_seguinte"], 9.0)

        retake = features.retake_features(self.phrases, 0, 1, INTEREST)
        self.assertEqual(len(retake), len(features.RETAKE_FEATURES))

        zoom = dict(zip(features.ZOOM_FEATURES, features.zoom_features(self.phrases[1], LOUD, INTEREST, 300.0, 0.5), strict=True))
        self.assertEqual(zoom["desde_ultimo_zoom_s"], 120.0)
        self.assertAlmostEqual(zoom["volume_pico"], 20.0)


if __name__ == "__main__":
    unittest.main()
