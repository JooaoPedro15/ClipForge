import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import segmentation  # noqa: E402


def make_words(tokens: list[str], step: float = 0.25) -> list[dict]:
    return [{"word": token, "start": index * step, "end": (index + 1) * step} for index, token in enumerate(tokens)]


def texts(groups: list[list[dict]]) -> list[str]:
    return [" ".join(word["word"].strip() for word in group) for group in groups]


class SegmentWordsNaturallyTest(unittest.TestCase):
    def test_pulls_next_word_when_target_would_end_on_weak_word(self):
        words = make_words("eu tenho que pegar aquela chave ali".split())

        groups = segmentation.segment_words_naturally(words, target_words=3)

        self.assertEqual(texts(groups), ["eu tenho que pegar", "aquela chave ali"])

    def test_avoids_lonely_tail_word_when_previous_block_can_absorb_it(self):
        words = make_words("pegar aquela chave ali".split())

        groups = segmentation.segment_words_naturally(words, target_words=3)

        self.assertEqual(texts(groups), ["pegar aquela chave ali"])


class CardsForSegmentTest(unittest.TestCase):
    SEGMENT = {"id": 4, "start": 0.0, "end": 2.0, "text": " eu tenho que pegar aquela chave ali", "avg_logprob": -0.2}

    def test_word_groups_when_max_words_is_set(self):
        words = make_words("eu tenho que pegar aquela chave ali".split())

        cards = segmentation.cards_for_segment(words, self.SEGMENT, max_words=3, first_index=10)

        self.assertEqual(
            cards,
            [
                {"i": 10, "start": 0.0, "end": 1.0, "text": "eu tenho que pegar", "segment_id": 4, "avg_logprob": -0.2},
                {"i": 11, "start": 1.0, "end": 1.75, "text": "aquela chave ali", "segment_id": 4, "avg_logprob": -0.2},
            ],
        )

    def test_whole_segment_when_short_and_no_max_words(self):
        words = make_words("eu tenho que pegar aquela chave ali".split())

        cards = segmentation.cards_for_segment(words, self.SEGMENT, max_words=0, first_index=0)

        self.assertEqual(
            cards,
            [{"i": 0, "start": 0.0, "end": 2.0, "text": "eu tenho que pegar aquela chave ali", "segment_id": 4, "avg_logprob": -0.2}],
        )

    def test_long_segment_without_max_words_is_split_by_duration(self):
        tokens = ("isso e uma fala continua que nao tem pausa detectada pelo vad e dura mais de dez segundos no total").split()
        words = [{"word": token, "start": float(index), "end": float(index) + 0.9} for index, token in enumerate(tokens)]
        segment = {"id": 0, "start": 0.0, "end": words[-1]["end"], "text": " ".join(tokens), "avg_logprob": None}

        cards = segmentation.cards_for_segment(words, segment, max_words=0, first_index=0)

        self.assertGreater(len(cards), 1)
        self.assertEqual({card["segment_id"] for card in cards}, {0})
        self.assertEqual(" ".join(card["text"] for card in cards), " ".join(tokens))

    def test_segment_without_words_becomes_single_card_even_with_max_words(self):
        cards = segmentation.cards_for_segment([], self.SEGMENT, max_words=3, first_index=7)

        self.assertEqual([card["i"] for card in cards], [7])
        self.assertEqual(cards[0]["text"], "eu tenho que pegar aquela chave ali")


if __name__ == "__main__":
    unittest.main()
