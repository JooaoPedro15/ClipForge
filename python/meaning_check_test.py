import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import meaning_check

SHEET = {
    "characters": [
        {"source_name": "Edgar", "zh": "埃德加", "gender": "male"},
        {"source_name": "Bernardo", "zh": "伯纳多", "gender": "male"},
        {"source_name": "Lenora", "zh": "莱诺拉", "gender": "female"},
    ]
}


class NegationMismatchTest(unittest.TestCase):
    """Casos reais do video auditado, com a retraducao literal que o 14B
    devolveu para cada legenda."""

    def test_faltou_means_not_yet_and_is_lost(self):
        problem = meaning_check.negation_mismatch(
            "rejeitado, rejeitado, faltou o Bernardo rejeitar o Edgar,",
            "Ser recusado, ser recusado, Bernardo ainda recusou Edgar",
        )
        self.assertIn("faltou", problem)

    def test_lost_twist_com_x_nao(self):
        problem = meaning_check.negation_mismatch(
            "e ela fica triste, e aí ela casa novamente, com o Edgar não, com a Isabel,",
            "Ela está triste de se casar novamente com Isabel",
        )
        self.assertIn("não", problem)

    def test_negation_added_by_the_subtitle(self):
        problem = meaning_check.negation_mismatch("o Bernardo rejeitou o Edgar", "Bernardo não rejeitou Edgar")
        self.assertTrue(problem)

    def test_equivalent_negations_pass(self):
        self.assertEqual(meaning_check.negation_mismatch("então não tem como, só que aí o Bernardo morre,", "Então não deu em nada, Bernardo morreu"), "")
        self.assertEqual(meaning_check.negation_mismatch("e aí o Edgar não sabendo disso,", "Edgar não sabe desta coisa"), "")
        self.assertEqual(meaning_check.negation_mismatch("faltou o Bernardo rejeitar o Edgar", "só o Bernardo ainda não rejeitou Edgar"), "")

    def test_no_negation_on_either_side_passes(self):
        self.assertEqual(meaning_check.negation_mismatch("tenta casar com a Isabel,", "Vai atrás de novo da Isabel"), "")

    def test_negation_word_inside_another_word_is_ignored(self):
        # "nada" em "nadar", "nem" em "nemesis" nao sao negacao.
        self.assertEqual(meaning_check.negation_mismatch("ele vai nadar", "Ele vai nadar"), "")


class BackTranslateTest(unittest.TestCase):
    def test_sends_only_the_chinese_and_the_name_mapping_never_the_source(self):
        # Retraducao "as cegas": se o modelo visse a fala original, ele
        # "corrigiria" a retraducao e o erro sumiria.
        client = mock.Mock()
        client.chat_json.return_value = {"pt": "Bernardo ainda recusou Edgar"}

        back = meaning_check.back_translate("伯纳多还拒绝了埃德加", SHEET, client)

        self.assertEqual(back, "Bernardo ainda recusou Edgar")
        payload = json.loads(client.chat_json.call_args.kwargs["user"])
        self.assertEqual(payload["zh"], "伯纳多还拒绝了埃德加")
        self.assertEqual(payload["names"]["伯纳多"], "Bernardo")
        self.assertEqual(set(payload), {"zh", "names"})
        self.assertEqual(client.chat_json.call_args.kwargs["temperature"], 0)

    def test_returns_empty_string_when_model_answers_garbage(self):
        client = mock.Mock()
        client.chat_json.return_value = ["nao e objeto"]

        self.assertEqual(meaning_check.back_translate("好", SHEET, client), "")

    def test_returns_empty_string_when_model_call_fails(self):
        # A conferencia e um extra: falha nela nao pode derrubar a traducao.
        client = mock.Mock()
        client.chat_json.side_effect = RuntimeError("json quebrado")

        self.assertEqual(meaning_check.back_translate("好", SHEET, client), "")


if __name__ == "__main__":
    unittest.main()
