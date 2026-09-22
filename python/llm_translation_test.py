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

    def test_long_line_is_split_in_three_groups(self):
        # Erro 2 (linha longa): 3 cards, linha de 30 chars -> 3 linhas de 10.
        cards = [
            _card(0, 0.0, 2.0, "todo mundo rejeita o pobre Edgar"),
            _card(1, 2.0, 4.0, "o Bernardo se casou com a Lenora"),
            _card(2, 4.0, 6.0, "e aí o Bernardo morreu de repente."),
        ]
        client = _client(["一" * 15 + "，" + "二" * 15 + "，" + "三" * 15])

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertEqual(client.chat_json.call_count, 1)
        self.assertEqual([g["zh"] for g in groups], ["一" * 15, "二" * 15, "三" * 15])
        self.assertEqual([g["cards"] for g in groups], [[0], [1], [2]])
        self.assertEqual(groups[0]["start"], 0.0)
        self.assertEqual(groups[-1]["end"], 6.0)

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


class SplitLineIntoPartsTest(unittest.TestCase):
    """Linha longa vira N linhas (nao so 2): uma frase de ~20 palavras em
    portugues passa de 40 caracteres em chines e precisa de 3 pedacos."""

    def test_short_line_stays_whole(self):
        self.assertEqual(llm_translation.split_line_into_parts("短句", 20), ["短句"])

    def test_splits_into_three_parts_at_punctuation(self):
        # 3 oracoes de 15 caracteres: nao cabem 2 a 2 no limite de 20.
        zh = "一" * 15 + "，" + "二" * 15 + "，" + "三" * 15

        parts = llm_translation.split_line_into_parts(zh, 20)

        self.assertEqual(parts, ["一" * 15, "二" * 15, "三" * 15])

    def test_uses_the_fewest_lines_that_fit(self):
        # 4 oracoes curtas cabem em 2 linhas de <=20 — nao vira 4 linhas.
        zh = "所有人都拒绝埃德加，伯纳多娶了莱诺拉，然后伯纳多死了，莱诺拉很伤心"

        parts = llm_translation.split_line_into_parts(zh, 20)

        self.assertEqual(parts, ["所有人都拒绝埃德加，伯纳多娶了莱诺拉", "然后伯纳多死了，莱诺拉很伤心"])

    def test_packs_greedily_up_to_the_limit(self):
        # Pedacos curtos sao agrupados ate encher a linha, em vez de virar
        # uma linha por virgula.
        zh = "他来了，她走了，我笑了"

        parts = llm_translation.split_line_into_parts(zh, 20)

        self.assertEqual(parts, ["他来了，她走了，我笑了"])

    def test_returns_none_when_a_chunk_alone_exceeds_the_limit(self):
        self.assertIsNone(llm_translation.split_line_into_parts("这" * 25, 20))
        self.assertIsNone(llm_translation.split_line_into_parts("短，" + "这" * 25, 20))

    def test_strips_trailing_punctuation_of_every_part(self):
        parts = llm_translation.split_line_into_parts("第一句话在这里啊，第二句话也在这里。", 12)

        self.assertEqual(parts, ["第一句话在这里啊", "第二句话也在这里"])


class SplitCardsIntoPartsTest(unittest.TestCase):
    def test_splits_cards_into_n_blocks_matching_line_lengths(self):
        bucket = [_card(i, float(i), float(i) + 1.0, "x") for i in range(6)]

        parts = llm_translation.split_cards_into_parts(bucket, [10, 10, 10], min_duration=1.2)

        self.assertEqual([[c["i"] for c in p] for p in parts], [[0, 1], [2, 3], [4, 5]])

    def test_returns_none_when_a_block_would_be_too_short_to_read(self):
        bucket = [_card(0, 0.0, 1.0, "x"), _card(1, 1.0, 5.0, "x")]

        self.assertIsNone(llm_translation.split_cards_into_parts(bucket, [10, 10], min_duration=1.2))

    def test_returns_none_when_there_are_fewer_cards_than_parts(self):
        bucket = [_card(0, 0.0, 5.0, "x")]

        self.assertIsNone(llm_translation.split_cards_into_parts(bucket, [10, 10], min_duration=1.2))


class RepeatedConnectiveTest(unittest.TestCase):
    """O modelo de 7B abre quase toda linha com o mesmo conectivo (结果...,
    结果..., 结果...), o que le muito mal numa sequencia de legendas."""

    def test_same_opening_connective_twice_triggers_a_retry(self):
        cards = [_card(0, 0.0, 2.0, "a."), _card(1, 2.0, 4.0, "b.")]
        client = _client(["结果他来了", "结果她走了", "然后她走了"])

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertEqual(client.chat_json.call_count, 3)
        self.assertIn("connective", client.chat_json.call_args_list[2].kwargs["user"])
        self.assertEqual([g["zh"] for g in groups], ["结果他来了", "然后她走了"])

    def test_connective_is_dropped_when_the_model_insists(self):
        cards = [_card(0, 0.0, 2.0, "a."), _card(1, 2.0, 4.0, "b.")]
        client = _client(["结果他来了", "结果她走了", "结果她走了", "结果她走了"])

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertEqual([g["zh"] for g in groups], ["结果他来了", "她走了"])

    def test_different_connectives_in_a_row_are_fine(self):
        cards = [_card(0, 0.0, 2.0, "a."), _card(1, 2.0, 4.0, "b.")]
        client = _client(["结果他来了", "然后她走了"])

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertEqual(client.chat_json.call_count, 2)
        self.assertEqual([g["zh"] for g in groups], ["结果他来了", "然后她走了"])

    def test_connective_is_kept_when_dropping_it_would_empty_the_line(self):
        cards = [_card(0, 0.0, 2.0, "a."), _card(1, 2.0, 4.0, "b.")]
        client = _client(["结果他来了", "结果", "结果", "结果"])

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertEqual(groups[1]["zh"], "结果")


class NormalizePunctuationTest(unittest.TestCase):
    def test_latin_comma_becomes_full_width(self):
        self.assertEqual(llm_translation.normalize_punctuation("他来了,她走了"), "他来了，她走了")

    def test_quotes_and_parentheses_are_dropped(self):
        self.assertEqual(llm_translation.normalize_punctuation('他说"好"(真的)'), "他说好真的")

    def test_chinese_punctuation_is_untouched(self):
        self.assertEqual(llm_translation.normalize_punctuation("他来了，她走了！"), "他来了，她走了！")


class PunctuationInPipelineTest(unittest.TestCase):
    def test_trailing_latin_comma_is_cleaned_before_grouping(self):
        cards = [_card(0, 0.0, 2.0, "tenta casar com a Isabel.")]
        client = _client(["尝试娶伊莎贝尔,"])

        groups = llm_translation.translate_with_llm(cards, SHEET, client)

        self.assertEqual(groups[0]["zh"], "尝试娶伊莎贝尔")
        self.assertEqual(client.chat_json.call_count, 1)


if __name__ == "__main__":
    unittest.main()
