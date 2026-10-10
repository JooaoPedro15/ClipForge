import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import style_alignment
from style_alignment import Card


def timed_words(items: list[tuple[str, float, float]]) -> list[dict]:
    return [{"word": f" {word}", "start": start, "end": end} for word, start, end in items]


# Video cru: 1s de silencio entre "la" e "ontem".
RAW_WORDS = timed_words(
    [("eu", 1.0, 1.2), ("fui", 1.25, 1.45), ("la", 1.5, 1.7), ("ontem", 2.7, 2.9), ("e", 2.95, 3.05), ("tava", 3.1, 3.4)]
)
# Video final: o usuario cortou 0,8s desse silencio no Premiere.
FINAL_WORDS = timed_words(
    [("eu", 1.0, 1.2), ("fui", 1.25, 1.45), ("la", 1.5, 1.7), ("ontem", 1.9, 2.1), ("e", 2.15, 2.25), ("tava", 2.3, 2.6)]
)
# SRT corrigido, na linha do tempo do video final.
CARDS = [Card(0.9, 1.9, "eu fui la"), Card(1.9, 2.8, "ontem e tava")]


class ParseSrtTextTest(unittest.TestCase):
    def test_parses_premiere_export_with_bom_crlf_and_tags(self):
        content = (
            "﻿1\r\n00:00:01,000 --> 00:00:02,500\r\n<i>eu fui</i>\r\nla\r\n\r\n"
            "2\r\n00:00:02,500 --> 00:00:03,000\r\nontem\r\n"
        )

        cards = style_alignment.parse_srt_text(content)

        self.assertEqual(cards, [Card(1.0, 2.5, "eu fui la"), Card(2.5, 3.0, "ontem")])

    def test_skips_blocks_without_text(self):
        content = "1\n00:00:01,000 --> 00:00:02,000\n\n2\n00:00:02,000 --> 00:00:03,000\noi\n"

        self.assertEqual([card.text for card in style_alignment.parse_srt_text(content)], ["oi"])


class AlignBreaksTest(unittest.TestCase):
    def test_labels_each_gap_with_the_users_breaks_even_after_cuts(self):
        alignment = style_alignment.align_breaks(RAW_WORDS, CARDS)

        self.assertEqual(alignment.labels, {0: 0, 1: 0, 2: 1, 3: 0, 4: 0})
        self.assertEqual(alignment.word_card, {0: 0, 1: 0, 2: 0, 3: 1, 4: 1, 5: 1})
        self.assertEqual(alignment.match_ratio, 1.0)

    def test_swapped_word_only_drops_its_neighbouring_gaps_and_is_recorded(self):
        words = timed_words([(w, i, i + 0.5) for i, w in enumerate("eu fui kareka ontem e tava".split())])
        cards = [Card(0, 3, "eu fui Careca"), Card(3, 6, "ontem e tava")]

        alignment = style_alignment.align_breaks(words, cards)

        self.assertEqual(alignment.labels, {0: 0, 3: 0, 4: 0})
        self.assertEqual(alignment.word_fixes, [("kareka", "Careca")])

    def test_frequent_words_are_not_ignored_in_long_lists(self):
        # Com autojunk (padrao do difflib) "que"/"de" viram lixo em listas > 200 e nada casa.
        words, cards = [], []
        for index in range(60):
            words += timed_words([(f"alfa{index}", 0, 0), ("que", 0, 0), ("de", 0, 0), (f"beta{index}", 0, 0)])
            cards.append(Card(0, 0, f"alfaz{index} que de betaz{index}"))

        alignment = style_alignment.align_breaks(words, cards)

        self.assertEqual(len(alignment.labels), 60)


class CutSectionsTest(unittest.TestCase):
    """O usuario corta trechos com fala no Premiere DEPOIS de legendar: isso nao e legenda errada."""

    RAW = timed_words(
        [
            ("eu", 0, 0.2), ("fui", 0.25, 0.45), ("la", 0.5, 0.7),
            ("isso", 1.0, 1.2), ("aqui", 1.25, 1.45), ("nao", 1.5, 1.7), ("presta", 1.75, 2.0),
            ("ontem", 2.3, 2.5), ("tava", 2.55, 2.8), ("cheio", 2.85, 3.1),
        ]
    )

    def test_cut_words_are_told_apart_from_corrected_words(self):
        cards = [Card(0, 0.75, "eu Fuy la"), Card(0.75, 1.6, "ontem tava cheio")]

        alignment = style_alignment.align_breaks(self.RAW, cards)

        self.assertEqual(alignment.cut_words, {3, 4, 5, 6})
        self.assertEqual(alignment.word_fixes, [("fui", "Fuy")])

    def test_correction_glued_to_a_cut_has_no_reliable_pair_and_counts_as_cut(self):
        # "la" corrigido pra "Lah" colado na frase cortada: o difflib junta tudo num bloco 5 -> 1.
        cards = [Card(0, 0.75, "eu fui Lah"), Card(0.75, 1.6, "ontem tava cheio")]

        alignment = style_alignment.align_breaks(self.RAW, cards)

        self.assertEqual(alignment.cut_words, {2, 3, 4, 5, 6})
        self.assertEqual(alignment.word_fixes, [])

    def test_heavy_cutting_is_not_mistaken_for_another_video(self):
        cards = [Card(0, 0.75, "eu fui"), Card(0.75, 1.6, "la ontem tava cheio")]

        alignment = style_alignment.align_breaks(self.RAW, cards)

        # Todas as palavras do SRT existem no bruto: e o mesmo video, so com 40% cortado.
        self.assertEqual(alignment.match_ratio, 1.0)
        self.assertAlmostEqual(alignment.cut_share, 0.4)


class AlignSpeechTest(unittest.TestCase):
    def test_finds_speech_times_in_the_final_cut_video(self):
        alignment = style_alignment.align_speech(CARDS, FINAL_WORDS)

        self.assertEqual(alignment.card_speech, {0: (1.0, 1.7), 1: (1.9, 2.6)})
        self.assertEqual(alignment.match_ratio, 1.0)

    def test_card_whose_last_word_did_not_match_is_left_out(self):
        cards = [Card(0.9, 1.9, "eu fui ali"), Card(1.9, 2.8, "ontem e tava")]

        alignment = style_alignment.align_speech(cards, FINAL_WORDS)

        self.assertEqual(list(alignment.card_speech), [1])

    def test_unrelated_srt_has_low_match_ratio(self):
        alignment = style_alignment.align_speech([Card(0, 1, "nada a ver com isso")], FINAL_WORDS)

        self.assertLess(alignment.match_ratio, style_alignment.MIN_MATCH_RATIO)


if __name__ == "__main__":
    unittest.main()
