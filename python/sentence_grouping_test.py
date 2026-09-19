import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sentence_grouping  # noqa: E402


class GroupCardsIntoSentencesTest(unittest.TestCase):
    def test_cards_from_same_segment_merge_into_one_group(self):
        cards = [
            {"i": 0, "start": 0.0, "end": 0.5, "text": "SO QUE AI", "segment_id": 0, "avg_logprob": -0.1},
            {"i": 1, "start": 0.5, "end": 1.2, "text": "O BERNARDO", "segment_id": 0, "avg_logprob": -0.1},
            {"i": 2, "start": 1.2, "end": 1.8, "text": "MORRE", "segment_id": 0, "avg_logprob": -0.1},
        ]

        groups = sentence_grouping.group_cards_into_sentences(cards)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["cards"], [0, 1, 2])
        self.assertEqual(groups[0]["start"], 0.0)
        self.assertEqual(groups[0]["end"], 1.8)
        self.assertEqual(groups[0]["text"], "SO QUE AI O BERNARDO MORRE")

    def test_cards_from_different_segments_stay_separate(self):
        cards = [
            {"i": 0, "start": 0.0, "end": 0.5, "text": "PRIMEIRA", "segment_id": 0, "avg_logprob": -0.1},
            {"i": 1, "start": 2.0, "end": 2.5, "text": "SEGUNDA", "segment_id": 1, "avg_logprob": -0.1},
        ]

        groups = sentence_grouping.group_cards_into_sentences(cards)

        self.assertEqual([g["cards"] for g in groups], [[0], [1]])

    def test_very_long_segment_is_still_capped_by_duration(self):
        # 20 cards de 1s cada, todos do mesmo segment_id -> sem teto viraria 1 grupo de 20s.
        cards = [
            {"i": i, "start": float(i), "end": float(i) + 1.0, "text": f"palavra{i}", "segment_id": 0, "avg_logprob": -0.1}
            for i in range(20)
        ]

        groups = sentence_grouping.group_cards_into_sentences(cards, max_group_duration=7.0)

        self.assertGreater(len(groups), 1)
        for group in groups:
            self.assertLessEqual(group["end"] - group["start"], 7.0 + 1e-6)

    def test_group_confidence_is_the_minimum_avg_logprob_of_its_cards(self):
        cards = [
            {"i": 0, "start": 0.0, "end": 0.5, "text": "A", "segment_id": 0, "avg_logprob": -0.1},
            {"i": 1, "start": 0.5, "end": 1.0, "text": "B", "segment_id": 0, "avg_logprob": -0.9},
        ]

        groups = sentence_grouping.group_cards_into_sentences(cards)

        self.assertAlmostEqual(groups[0]["avg_logprob"], -0.9)

    def test_group_with_all_avg_logprob_none_does_not_raise(self):
        # cards.json de video transcrito antes do sidecar existir (fallback de
        # uma task futura) nao tem avg_logprob — nao pode estourar ValueError.
        cards = [
            {"i": 0, "start": 0.0, "end": 0.5, "text": "A", "segment_id": 0, "avg_logprob": None},
            {"i": 1, "start": 0.5, "end": 1.0, "text": "B", "segment_id": 0, "avg_logprob": None},
        ]

        groups = sentence_grouping.group_cards_into_sentences(cards)

        self.assertIsNone(groups[0]["avg_logprob"])

    def test_empty_cards_list_returns_empty_groups(self):
        self.assertEqual(sentence_grouping.group_cards_into_sentences([]), [])


if __name__ == "__main__":
    unittest.main()
