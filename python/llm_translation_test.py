import json
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


def _client(answers):
    """Mock que responde uma frase por chamada, na ordem de `answers`
    (lista de zh, ou de dicts completos)."""
    client = mock.Mock()
    responses = []
    for answer in answers:
        responses.append(answer if isinstance(answer, dict) else {"zh": answer, "flag": ""})
    client.chat_json.side_effect = responses
    return client


def _target_id(call):
    user = call.kwargs["user"]
    return json.loads(user.split("## Translate now")[1])["id"]


class ProposeSentencesTest(unittest.TestCase):
    def test_comma_closes_sentence_only_after_enough_words(self):
        # "e aí o Edgar," (4 palavras) nao vira frase sozinha — junta com o resto.
        cards = [
            _card(0, 0.0, 0.5, "e aí"),
            _card(1, 0.5, 1.0, "o Edgar,"),
            _card(2, 1.0, 2.0, "ele tentou casar"),
            _card(3, 2.0, 3.0, "com a Lenora,"),
            _card(4, 3.0, 4.5, "só que ela já tá"),
            _card(5, 4.5, 5.5, "com o Bernardo,"),
        ]

        sentences = llm_translation.propose_sentences(cards)

        self.assertEqual([s["cards"] for s in sentences], [[0, 1, 2, 3], [4, 5]])
        self.assertEqual(sentences[0]["text"], "e aí o Edgar, ele tentou casar com a Lenora,")

    def test_period_always_closes(self):
        cards = [_card(0, 0.0, 1.5, "acabou."), _card(1, 1.5, 3.0, "sou o melhor.")]

        sentences = llm_translation.propose_sentences(cards)

        self.assertEqual([s["cards"] for s in sentences], [[0], [1]])

    def test_overflow_cuts_at_last_comma_not_mid_clause(self):
        cards = [
            _card(0, 0.0, 1.0, "todo mundo rejeita"),
            _card(1, 1.0, 2.0, "o Edgar,"),
            _card(2, 2.0, 3.0, "o Bernardo se casou"),
            _card(3, 3.0, 4.0, "com a Lenora e"),
            _card(4, 4.0, 5.0, "foi morar longe"),
            _card(5, 5.0, 6.0, "de todo mundo que"),
            _card(6, 6.0, 7.0, "conhecia antes."),
        ]

        sentences = llm_translation.propose_sentences(cards, max_words=12)

        self.assertEqual(sentences[0]["cards"], [0, 1])
        self.assertEqual(sentences[1]["cards"], [2, 3, 4, 5, 6])

    def test_never_closes_before_a_continuation_word(self):
        # "vai ver o túmulo" + "do Bernardo," — fechar antes de "do" deixa um
        # pedaco sem sentido ("do Bernardo, não tô entendendo") que o modelo
        # traduziu como "伯纳多死了" (inventado).
        cards = [
            _card(0, 0.0, 1.0, "e aí o Edgar"),
            _card(1, 1.0, 2.0, "morre triste, e aí"),
            _card(2, 2.0, 3.0, "o Edgar vai"),
            _card(3, 3.0, 4.0, "ver o túmulo"),
            _card(4, 4.0, 5.0, "do Bernardo, não"),
            _card(5, 5.0, 6.0, "tô entendendo, todo"),
            _card(6, 6.0, 7.0, "mundo rejeita o Edgar,"),
        ]

        sentences = llm_translation.propose_sentences(cards, max_words=12)

        # 4 termina em "não" (dangling) e 5 em "todo" (dangling): so fecha no 6.
        self.assertEqual([s["cards"] for s in sentences], [[0, 1, 2, 3, 4, 5, 6]])

    def test_short_sentence_is_merged_with_neighbour(self):
        # Erro 1 (fragmentacao): frase de 0.6s nao fica sozinha na tela.
        cards = [
            _card(0, 0.0, 2.0, "o Bernardo se casou com a Lenora,"),
            _card(1, 2.0, 2.6, "só que aí,"),
            _card(2, 2.6, 4.0, "o Bernardo morre e some,"),
        ]

        sentences = llm_translation.propose_sentences(cards, min_words=1)

        self.assertEqual([s["cards"] for s in sentences], [[0], [1, 2]])
        self.assertGreaterEqual(sentences[1]["end"] - sentences[1]["start"], 1.2)

    def test_low_confidence_is_min_of_cards(self):
        cards = [_card(0, 0.0, 1.0, "a", logprob=-0.1), _card(1, 1.0, 2.0, "b.", logprob=-0.9)]

        sentences = llm_translation.propose_sentences(cards)

        self.assertEqual(sentences[0]["avg_logprob"], -0.9)


class TranslateWithLlmTest(unittest.TestCase):
    def test_one_call_per_sentence_with_previous_lines_as_context(self):
        # Erro 1: "só que aí" + "o Bernardo" + "morre" sao UMA frase e uma linha.
        cards = [
            _card(0, 0.0, 1.5, "o Bernardo se casou."),
            _card(1, 7.4, 8.1, "só que aí"),
            _card(2, 8.1, 8.9, "o Bernardo"),
            _card(3, 8.9, 9.8, "morre."),
        ]
        client = _client(["伯纳多结婚了", "结果伯纳多死了"])

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertEqual([g["cards"] for g in groups], [[0], [1, 2, 3]])
        self.assertEqual(groups[1]["zh"], "结果伯纳多死了")
        self.assertEqual(groups[1]["text"], "só que aí o Bernardo morre.")
        self.assertEqual(groups[1]["start"], 7.4)
        self.assertEqual(groups[1]["end"], 9.8)
        calls = client.chat_json.call_args_list
        self.assertEqual([_target_id(c) for c in calls], [0, 1])
        self.assertIn("伯纳多结婚了", calls[1].kwargs["user"])  # linha anterior vai como contexto
        self.assertEqual(calls[0].kwargs["temperature"], 0)

    def test_retries_with_feedback_and_temperature_when_id_mismatches(self):
        cards = [_card(0, 0.0, 2.0, "a."), _card(1, 2.0, 4.0, "b.")]
        client = _client([
            {"id": 0, "zh": "好", "flag": ""},
            {"id": 0, "zh": "好", "flag": ""},  # respondeu a frase errada
            {"id": 1, "zh": "好的", "flag": ""},
        ])

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertEqual(client.chat_json.call_count, 3)
        third = client.chat_json.call_args_list[2]
        self.assertIn("Previous attempt was rejected", third.kwargs["user"])
        self.assertGreater(third.kwargs["temperature"], 0)
        self.assertEqual(groups[1]["zh"], "好的")

    def test_retries_when_latin_script_is_left(self):
        # Erro 5: nome em latim volta pro modelo com o aviso.
        cards = [_card(0, 0.0, 2.0, "o Bernardo chegou.")]
        client = _client(["Bernardo来了", "伯纳多来了"])

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        # normalize_names ja troca a grafia latina pela canonica antes de checar
        self.assertEqual(groups[0]["zh"], "伯纳多来了")

    def test_retries_when_line_is_too_long_and_cannot_be_split(self):
        cards = [_card(0, 0.0, 2.0, "frase longa.")]
        client = _client(["这" * 25, "短句"])

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertEqual(groups[0]["zh"], "短句")
        self.assertIn("at most 20 characters", client.chat_json.call_args_list[1].kwargs["user"])

    def test_gives_up_after_all_attempts_and_keeps_shortest(self):
        cards = [_card(0, 0.0, 2.0, "frase longa.")]
        client = _client(["这" * 25, "这" * 22, "这" * 30])

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertEqual(client.chat_json.call_count, 3)
        self.assertEqual(groups[0]["zh"], "这" * 22)  # a validacao reprova depois

    def test_raises_when_model_never_answers_usable_json(self):
        cards = [_card(0, 0.0, 2.0, "a.")]
        client = _client([[], [], []])

        with self.assertRaises(llm_translation.LLMTranslationError):
            llm_translation.translate_with_llm(cards, SHEET, client)

    def test_long_line_is_split_in_two_groups_at_chinese_comma(self):
        # 4 palavras no 1o card: a virgula nao fecha a frase (min 5), entao os
        # 2 cards viram UMA frase e uma chamada; a linha de 23 chars e dividida.
        cards = [_card(0, 0.0, 2.0, "rejeitam o pobre Edgar,"), _card(1, 2.0, 4.0, "o Bernardo se casou com a Lenora,")]
        client = _client(["所有人都拒绝了可怜的埃德加，然后伯纳多娶了莱诺拉"])

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertEqual(client.chat_json.call_count, 1)
        self.assertEqual([g["zh"] for g in groups], ["所有人都拒绝了可怜的埃德加", "然后伯纳多娶了莱诺拉"])
        self.assertEqual([g["cards"] for g in groups], [[0], [1]])
        self.assertEqual(groups[0]["end"], 2.0)
        self.assertEqual(groups[1]["start"], 2.0)

    def test_trailing_punctuation_is_stripped(self):
        cards = [_card(0, 0.0, 2.0, "a.")]
        client = _client(["好的。"])

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertEqual(groups[0]["zh"], "好的")

    def test_unclear_indices_from_sheet_are_marked_low_confidence(self):
        # Erro 6 (alucinacao): card que o estagio 1 marcou como ilegivel vai
        # pro estagio 2 marcado, nao como texto normal.
        cards = [_card(0, 1.0, 2.0, "REJEITADO."), _card(1, 2.0, 3.5, "o Bernardo.")]
        sheet = dict(SHEET, unclear=[0])
        client = _client([{"zh": "被拒绝", "flag": "source unclear"}, "伯纳多"])

        groups = llm_translation.translate_with_llm(cards, sheet, client)

        user_prompt = client.chat_json.call_args_list[0].kwargs["user"]
        target = json.loads(user_prompt.split("## Translate now")[1])
        self.assertTrue(target["low_confidence"])
        self.assertEqual(groups[0]["flag"], "source unclear")

    def test_group_flag_carries_whisper_low_confidence_when_model_left_it_empty(self):
        cards = [_card(0, 1.0, 2.5, "REJEITADO.", logprob=-0.95)]
        client = _client(["我也是最好的"])

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertIn("baixa confianca", groups[0]["flag"])


if __name__ == "__main__":
    unittest.main()
