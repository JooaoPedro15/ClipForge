import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import llm_translation  # noqa: E402


def _card(i, start, end, text, segment_id=0, logprob=-0.2):
    return {"i": i, "start": start, "end": end, "text": text, "segment_id": segment_id, "avg_logprob": logprob}


SHEET = {
    "summary": "s",
    "characters": [{"source_name": "Bernardo", "variants": [], "zh": "伯纳多", "gender": "male", "relations": "unknown", "note": ""}],
    "terms": [],
    "register": "falado",
    "unclear": [],
}


class TranslateWithLlmTest(unittest.TestCase):
    def test_groups_fragments_into_one_sentence(self):
        # Erro 1 (fragmentacao): "SÓ QUE AÍ" + "O BERNARDO" + "MORRE" tem que
        # sair como UMA linha, nao tres cards traduzidos isolados.
        cards = [_card(0, 7.4, 8.1, "só que aí"), _card(1, 8.1, 8.9, "o Bernardo"), _card(2, 8.9, 9.8, "morre")]
        client = mock.Mock()
        client.chat_json.return_value = {"groups": [{"cards": [0, 1, 2], "start": 7.4, "end": 9.8, "zh": "结果伯纳多死了", "flag": ""}]}

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["cards"], [0, 1, 2])
        self.assertEqual(groups[0]["zh"], "结果伯纳多死了")
        self.assertEqual(groups[0]["text"], "só que aí o Bernardo morre")

    def test_start_end_come_from_cards_not_from_model(self):
        cards = [_card(0, 1.0, 2.0, "a"), _card(1, 2.0, 3.5, "b")]
        client = mock.Mock()
        client.chat_json.return_value = {"groups": [{"cards": [1, 0], "start": 0.0, "end": 99.0, "zh": "好", "flag": ""}]}

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertEqual(groups[0]["cards"], [0, 1])
        self.assertEqual(groups[0]["start"], 1.0)
        self.assertEqual(groups[0]["end"], 3.5)

    def test_accepts_bare_array_output(self):
        cards = [_card(0, 1.0, 2.0, "a")]
        client = mock.Mock()
        client.chat_json.return_value = [{"cards": [0], "zh": "好", "flag": ""}]

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertEqual(groups[0]["zh"], "好")

    def test_retries_once_with_feedback_when_coverage_is_broken(self):
        cards = [_card(0, 1.0, 2.0, "a"), _card(1, 2.0, 3.0, "b")]
        client = mock.Mock()
        client.chat_json.side_effect = [
            {"groups": [{"cards": [0], "zh": "好", "flag": ""}]},  # faltou o card 1
            {"groups": [{"cards": [0, 1], "zh": "好的", "flag": ""}]},
        ]

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertEqual(client.chat_json.call_count, 2)
        self.assertIn("faltando", client.chat_json.call_args_list[1].kwargs["user"])
        self.assertEqual(groups[0]["cards"], [0, 1])

    def test_raises_after_retry_still_broken(self):
        cards = [_card(0, 1.0, 2.0, "a"), _card(1, 2.0, 3.0, "b")]
        client = mock.Mock()
        client.chat_json.return_value = {"groups": [{"cards": [0], "zh": "好", "flag": ""}]}

        with self.assertRaises(llm_translation.LLMTranslationError) as ctx:
            llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertIn("faltando", str(ctx.exception))

    def test_unclear_indices_from_sheet_are_marked_low_confidence(self):
        # Erro 6 (alucinacao): card que o estagio 1 marcou como ilegivel vai
        # pro estagio 2 marcado, nao como texto normal.
        cards = [_card(0, 1.0, 2.0, "REJEITADO"), _card(1, 2.0, 3.0, "o Bernardo")]
        sheet = dict(SHEET, unclear=[0])
        client = mock.Mock()
        client.chat_json.return_value = {"groups": [{"cards": [0, 1], "zh": "伯纳多被拒绝了", "flag": "source unclear"}]}

        groups = llm_translation.translate_with_llm(cards, sheet, client)

        user_prompt = client.chat_json.call_args.kwargs["user"]
        self.assertIn('"i": 0,', user_prompt)
        self.assertIn('"low_confidence": true', user_prompt)
        self.assertEqual(groups[0]["flag"], "source unclear")

    def test_group_flag_carries_whisper_low_confidence_when_model_left_it_empty(self):
        cards = [_card(0, 1.0, 2.5, "REJEITADO", logprob=-0.95)]
        client = mock.Mock()
        client.chat_json.return_value = {"groups": [{"cards": [0], "zh": "我也是最好的", "flag": ""}]}

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertIn("baixa confianca", groups[0]["flag"])

    def test_long_transcript_is_chunked_at_segment_boundaries(self):
        cards = [_card(i, float(i), float(i + 1), f"w{i}", segment_id=i // 3) for i in range(10)]
        client = mock.Mock()

        def answer(system, user):
            import json
            transcript = json.loads(user.split("## Transcript")[1])
            idx = [c["i"] for c in transcript]
            return {"groups": [{"cards": idx, "zh": "好", "flag": ""}]}

        client.chat_json.side_effect = answer

        groups = llm_translation.translate_with_llm(cards, SHEET, client, chunk_size=4)

        # chunks: [0..2] (segmento 1 inteiro nao cabe), [3..5], [6..9] (segmento 3 tem 1 card, cabe)
        self.assertEqual([g["cards"] for g in groups], [[0, 1, 2], [3, 4, 5], [6, 7, 8, 9]])
        self.assertEqual(client.chat_json.call_count, 3)


class SplitIntoChunksTest(unittest.TestCase):
    def test_never_splits_inside_a_segment_when_it_fits(self):
        cards = [_card(i, 0, 1, "x", segment_id=0 if i < 3 else 1) for i in range(5)]

        chunks = llm_translation.split_into_chunks(cards, chunk_size=4)

        self.assertEqual([[c["i"] for c in ch] for ch in chunks], [[0, 1, 2], [3, 4]])

    def test_segment_bigger_than_chunk_is_split_anyway(self):
        cards = [_card(i, 0, 1, "x", segment_id=0) for i in range(6)]

        chunks = llm_translation.split_into_chunks(cards, chunk_size=4)

        self.assertEqual([[c["i"] for c in ch] for ch in chunks], [[0, 1, 2, 3], [4, 5]])


if __name__ == "__main__":
    unittest.main()
