import unittest

from preedit.phrases import build_phrases, ends_sentence, phrase_of_words, retake_pairs, similarity


def words_from(items):
    """[(texto, inicio, fim), ...] -> palavras no formato do Whisper."""
    return [{"word": f" {text}", "start": start, "end": end} for text, start, end in items]


WORDS = words_from(
    [
        ("entao", 0.0, 0.3), ("eu", 0.35, 0.5), ("fui", 0.55, 0.8), ("la", 0.85, 1.0),
        ("entao", 2.0, 2.3), ("eu", 2.35, 2.5), ("fui", 2.55, 2.8), ("la.", 2.85, 3.0),
        ("e", 3.1, 3.2), ("tava", 3.25, 3.5), ("cheio!", 3.55, 3.9),
    ]
)


class PhrasesTest(unittest.TestCase):
    def test_build_phrases_splits_on_pause_and_sentence_end(self):
        phrases = build_phrases(WORDS)

        self.assertEqual([p.text for p in phrases], ["entao eu fui la", "entao eu fui la.", "e tava cheio!"])
        self.assertEqual([(p.first, p.last, p.start, p.end) for p in phrases], [(0, 3, 0.0, 1.0), (4, 7, 2.0, 3.0), (8, 10, 3.1, 3.9)])
        self.assertEqual(phrase_of_words(phrases), [0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2])

    def test_retakes_are_similar_phrases_said_again_soon(self):
        phrases = build_phrases(WORDS)

        self.assertAlmostEqual(similarity(phrases[0], phrases[1]), 1.0)
        self.assertEqual(retake_pairs(phrases), [(0, 1)])

    def test_far_or_different_phrases_are_not_retakes(self):
        far = words_from([("entao", 0.0, 0.3), ("eu", 0.35, 0.6), ("entao", 40.0, 40.3), ("eu", 40.35, 40.6)])

        self.assertEqual(retake_pairs(build_phrases(far)), [])
        self.assertEqual(build_phrases([]), [])

    def test_ends_sentence(self):
        self.assertTrue(ends_sentence("tava cheio!"))
        self.assertFalse(ends_sentence("e ai"))


if __name__ == "__main__":
    unittest.main()
