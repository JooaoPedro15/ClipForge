import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import style_features
import style_model


def synthetic_video(seed: int, count: int = 300):
    """Video falso em que o 'usuario' quebra exatamente nas pausas maiores que 300ms."""
    rng = random.Random(seed)
    words, start = [], 0.0
    for index in range(count):
        words.append({"word": f" w{index}", "start": start, "end": start + 0.2})
        start += 0.2 + (0.5 if rng.random() < 0.3 else 0.05)

    labels, gaps, sizes, durations = {}, [], [], []
    card_start = 0
    for index in range(count - 1):
        label = int(words[index + 1]["start"] - words[index]["end"] > 0.3)
        labels[index] = label
        gaps.append({"x": style_features.gap_features(words, card_start, index), "y": label})
        if label:
            sizes.append(index - card_start + 1)
            durations.append((words[index]["end"] - words[card_start]["start"]) * 1000)
            card_start = index + 1
    timing = {"lead_in_ms": [100.0], "hold_ms": [200.0], "glue": [], "card_words": sizes, "card_ms": durations}
    return words, labels, {"gaps": gaps, "timing": timing}


class FakeTree:
    """Arvore falsa que sempre devolve a mesma probabilidade de quebra."""

    classes_ = [0, 1]

    def __init__(self, break_probability: float):
        self.break_probability = break_probability

    def predict_proba(self, rows):
        return [[1 - self.break_probability, self.break_probability] for _ in rows]


RAILS = {"min_words": 2, "max_words": 3, "max_card_ms": 1e9}


def sizes(groups: list[tuple[int, int]]) -> list[int]:
    return [end - start for start, end in groups]


class ComputeParamsTest(unittest.TestCase):
    def test_rails_by_percentile_and_timing_by_median(self):
        videos = [
            {
                "gaps": [],
                "timing": {
                    "lead_in_ms": [100, 120, 80],
                    "hold_ms": [200, 250, 150],
                    "glue": [
                        {"raw_gap_ms": 150, "user_gap_ms": 0},
                        {"raw_gap_ms": 250, "user_gap_ms": 10},
                        {"raw_gap_ms": 900, "user_gap_ms": 600},
                    ],
                    "card_words": [2, 3, 3, 4, 5],
                    "card_ms": [600, 900, 1000, 1200, 2000],
                },
            }
        ]

        self.assertEqual(
            style_model.compute_params(videos),
            {
                "min_words": 2,
                "max_words": 5,
                "max_card_ms": 2000.0,
                "lead_in_ms": 100.0,
                "hold_ms": 200.0,
                "glue_ms": 250.0,
                "min_card_ms": 600.0,
            },
        )

    def test_percentile_of_empty_list_is_none(self):
        self.assertIsNone(style_model.percentile([], 50))


class TrainAndSegmentTest(unittest.TestCase):
    def test_tree_learns_the_pause_rule_and_generalizes_to_a_new_video(self):
        _, _, training = synthetic_video(seed=1)
        tree, params = style_model.train_profile([training])

        words, labels, _ = synthetic_video(seed=2)
        groups = style_model.segment_with_model(words, tree, params)

        self.assertGreater(style_model.break_f1(groups, labels), 0.9)
        self.assertEqual(params["videos"], 1)
        self.assertEqual(params["gap_examples"], 299)

    def test_manual_tree_walk_matches_sklearn_predict_proba(self):
        _, _, training = synthetic_video(seed=1)
        tree, _ = style_model.train_profile([training])
        _, _, other = synthetic_video(seed=3)

        for gap in other["gaps"]:
            expected = float(tree.predict_proba([gap["x"]])[0][list(tree.classes_).index(1)])
            self.assertAlmostEqual(style_model.break_probability(tree, gap["x"]), expected)

    def test_training_needs_breaks_and_non_breaks(self):
        _, _, video = synthetic_video(seed=1)
        video["gaps"] = [{**gap, "y": 0} for gap in video["gaps"]]

        with self.assertRaises(ValueError):
            style_model.train_profile([video])

    def test_rails_hold_against_a_tree_that_always_breaks(self):
        words = [{"word": " w", "start": i * 0.3, "end": i * 0.3 + 0.2} for i in range(7)]

        self.assertEqual(sizes(style_model.segment_with_model(words, FakeTree(1.0), RAILS)), [2, 2, 2, 1])

    def test_rails_hold_against_a_tree_that_never_breaks(self):
        words = [{"word": " w", "start": i * 0.3, "end": i * 0.3 + 0.2} for i in range(7)]

        self.assertEqual(sizes(style_model.segment_with_model(words, FakeTree(0.0), RAILS)), [3, 3, 1])

    def test_break_f1(self):
        groups = [(0, 3), (3, 5), (5, 6)]  # quebras depois das palavras 2 e 4
        labels = {0: 0, 1: 0, 2: 1, 3: 1, 4: 0}

        self.assertAlmostEqual(style_model.break_f1(groups, labels), 0.5)
        self.assertEqual(style_model.break_f1([(0, 6)], {0: 0}), 0.0)


class ApplyTimingTest(unittest.TestCase):
    def times(self, cards):
        return [(round(card["start"], 3), round(card["end"], 3)) for card in cards]

    def params(self, **values):
        return {"lead_in_ms": 0.0, "hold_ms": 0.0, "glue_ms": 0.0, "min_card_ms": 0.0, **values}

    def test_lead_in_hold_and_glue_small_gaps(self):
        cards = [{"start": 1.0, "end": 1.5, "text": "a"}, {"start": 1.7, "end": 2.0, "text": "b"}, {"start": 3.0, "end": 3.2, "text": "c"}]

        adjusted = style_model.apply_timing(cards, self.params(lead_in_ms=100, hold_ms=200, glue_ms=300))

        self.assertEqual(self.times(adjusted), [(0.9, 1.6), (1.6, 2.2), (2.9, 3.4)])
        self.assertEqual([card["text"] for card in adjusted], ["a", "b", "c"])

    def test_short_subtitles_are_stretched_to_the_minimum(self):
        cards = [{"start": 0.0, "end": 0.3}, {"start": 2.0, "end": 2.2}]

        adjusted = style_model.apply_timing(cards, self.params(min_card_ms=800))

        self.assertEqual(self.times(adjusted), [(0.0, 0.8), (2.0, 2.8)])

    def test_never_overlaps_the_next_subtitle_and_never_starts_before_zero(self):
        cards = [{"start": 0.05, "end": 1.0}, {"start": 1.2, "end": 2.0}]

        adjusted = style_model.apply_timing(cards, self.params(lead_in_ms=100, hold_ms=500))

        self.assertEqual(self.times(adjusted), [(0.0, 1.1), (1.1, 2.5)])


class SaveLoadTest(unittest.TestCase):
    def test_round_trip_and_minimum_videos(self):
        _, _, training = synthetic_video(seed=1)
        tree, params = style_model.train_profile([training])
        words, _, _ = synthetic_video(seed=2)

        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "profiles" / "horizontal"
            style_model.save_profile(profile_dir, tree, params)

            self.assertIsNone(style_model.load_profile(profile_dir))  # 1 video < minimo de 3
            loaded = style_model.load_profile(profile_dir, min_videos=1)
            self.assertIsNotNone(loaded)
            loaded_tree, loaded_params = loaded
            self.assertEqual(style_model.segment_with_model(words, loaded_tree, loaded_params), style_model.segment_with_model(words, tree, params))
            self.assertIn("pausa_ms", (profile_dir / "tree.txt").read_text(encoding="utf-8"))

            style_model.delete_profile(profile_dir)
            self.assertIsNone(style_model.load_profile(profile_dir, min_videos=1))


if __name__ == "__main__":
    unittest.main()
