import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import style_alignment
import style_features
from style_alignment import Card


def rounded(values: list[float]) -> list[float]:
    return [round(value, 3) for value in values]


def uniform_words(text: str) -> list[dict]:
    return [{"word": f" {word}", "start": index * 0.3, "end": index * 0.3 + 0.25} for index, word in enumerate(text.split())]


class GapFeaturesTest(unittest.TestCase):
    WORDS = [
        {"word": " Eu", "start": 0.0, "end": 0.2, "segment_end": False},
        {"word": " fui,", "start": 0.25, "end": 0.5},
        {"word": " e", "start": 0.9, "end": 1.0, "segment_end": True},
        {"word": " ai", "start": 1.0, "end": 1.2},
    ]

    def test_features_of_a_gap_after_a_comma_before_an_opener(self):
        features = style_features.gap_features(self.WORDS, card_start=0, index=1)

        # pausa, palavras, duracao, caracteres, fraca, pontuacao, abre frase, fim de segmento, palavras/s
        self.assertEqual(rounded(features), [400.0, 2.0, 500.0, 7.0, 0.0, 1.0, 1.0, 0.0, 4.0])

    def test_weak_word_at_segment_end(self):
        features = style_features.gap_features(self.WORDS, card_start=2, index=2)

        self.assertEqual(rounded(features), [0.0, 1.0, 100.0, 1.0, 1.0, 0.0, 1.0, 1.0, 3.0])

    def test_one_name_per_feature(self):
        self.assertEqual(len(style_features.FEATURE_NAMES), len(style_features.gap_features(self.WORDS, 0, 0)))


class BuildGapExamplesTest(unittest.TestCase):
    def test_state_follows_the_users_breaks(self):
        words = uniform_words("eu fui la ontem e tava")
        alignment = style_alignment.align_breaks(words, [Card(0, 1, "eu fui la"), Card(1, 2, "ontem e tava")])

        examples = style_features.build_gap_examples(words, alignment)

        self.assertEqual([example["y"] for example in examples], [0, 0, 1, 0, 0])
        self.assertEqual([example["x"][1] for example in examples], [1, 2, 3, 1, 2])  # palavras na legenda atual

    def test_unlabeled_gaps_are_skipped_but_still_track_the_current_subtitle(self):
        words = uniform_words("eu fui kareka ontem e tava")
        alignment = style_alignment.align_breaks(words, [Card(0, 1, "eu fui Careca"), Card(1, 2, "ontem e tava")])

        examples = style_features.build_gap_examples(words, alignment)

        self.assertEqual([example["y"] for example in examples], [0, 0, 0])
        self.assertEqual([example["x"][1] for example in examples], [1, 1, 2])


class BuildTimingSamplesTest(unittest.TestCase):
    def test_lead_in_hold_glue_and_sizes_from_a_cut_video(self):
        raw = [
            {"word": " eu", "start": 1.0, "end": 1.2},
            {"word": " fui", "start": 1.25, "end": 1.45},
            {"word": " la", "start": 1.5, "end": 1.7},
            {"word": " ontem", "start": 2.7, "end": 2.9},
            {"word": " e", "start": 2.95, "end": 3.05},
            {"word": " tava", "start": 3.1, "end": 3.4},
        ]
        final = [dict(word) for word in raw[:3]] + [
            {"word": " ontem", "start": 1.9, "end": 2.1},
            {"word": " e", "start": 2.15, "end": 2.25},
            {"word": " tava", "start": 2.3, "end": 2.6},
        ]
        cards = [Card(0.9, 1.9, "eu fui la"), Card(1.9, 2.8, "ontem e tava")]

        samples = style_features.build_timing_samples(
            raw, cards, style_alignment.align_breaks(raw, cards), style_alignment.align_speech(cards, final)
        )

        self.assertEqual(rounded(samples["lead_in_ms"]), [100.0, 0.0])
        self.assertEqual(rounded(samples["hold_ms"]), [200.0, 200.0])
        self.assertEqual([{key: round(value, 3) for key, value in gap.items()} for gap in samples["glue"]], [{"raw_gap_ms": 1000.0, "user_gap_ms": 0.0}])
        self.assertEqual(samples["card_words"], [3, 3])
        self.assertEqual(rounded(samples["card_ms"]), [1000.0, 900.0])


if __name__ == "__main__":
    unittest.main()
