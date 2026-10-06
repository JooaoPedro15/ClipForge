import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import review_store


def _group(cards, start, end, zh, sentence_id, text="frase", back="", note=""):
    return {
        "cards": cards, "start": start, "end": end, "zh": zh, "flag": "",
        "sentence_id": sentence_id, "sentence_text": text, "back_pt": back, "review_note": note,
    }


class BuildReviewTest(unittest.TestCase):
    def test_one_row_per_sentence_even_when_split_in_two_subtitles(self):
        groups = [
            _group([0], 0.0, 2.0, "所有人都拒绝埃德加", 0, "todo mundo rejeita o Edgar, o Bernardo casou", "todos recusam Edgar, Bernardo casou"),
            _group([1], 2.0, 4.0, "伯纳多娶了莱诺拉", 0, "todo mundo rejeita o Edgar, o Bernardo casou", "todos recusam Edgar, Bernardo casou"),
            _group([2], 4.0, 6.0, "伯纳多死了", 1, "o Bernardo morre", "Bernardo morreu", ""),
        ]

        review = review_store.build_review(groups, "zh")

        self.assertEqual(len(review["rows"]), 2)
        first = review["rows"][0]
        self.assertEqual([p["zh"] for p in first["parts"]], ["所有人都拒绝埃德加", "伯纳多娶了莱诺拉"])
        self.assertEqual(first["cards"], [0, 1])
        self.assertEqual((first["start"], first["end"]), (0.0, 4.0))
        self.assertEqual(first["back_pt"], "todos recusam Edgar, Bernardo casou")
        self.assertFalse(first["edited"])

    def test_note_is_kept_for_the_review_screen(self):
        groups = [_group([0], 0.0, 2.0, "伯纳多拒绝了埃德加", 0, "faltou o Bernardo rejeitar", "Bernardo recusou", "a fala tem negação ('faltou') e a legenda não")]

        review = review_store.build_review(groups, "zh")

        self.assertIn("faltou", review["rows"][0]["note"])

    def test_groups_without_sentence_id_have_no_review(self):
        # Caminho NLLB: nao ha frase/retraducao pra revisar.
        self.assertIsNone(review_store.build_review([{"cards": [0], "start": 0, "end": 1, "zh": "好", "flag": ""}], "zh"))

    def test_round_trip_to_groups_and_disk(self):
        groups = [_group([0], 0.0, 2.0, "好", 0, "bom"), _group([1], 2.0, 4.0, "坏", 1, "ruim")]
        review = review_store.build_review(groups, "zh")

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = review_store.review_path_for(str(Path(tmp_dir) / "video.zh.srt"))
            self.assertTrue(path.endswith("video.zh.review.json"))
            review_store.save_review(review, path)
            loaded = review_store.load_review(path)

        back = review_store.review_to_groups(loaded)
        self.assertEqual([(g["cards"], g["zh"], g["text"]) for g in back], [([0], "好", "bom"), ([1], "坏", "ruim")])


if __name__ == "__main__":
    unittest.main()
