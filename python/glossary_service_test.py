import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import glossary_service


class ExtractCandidateNamesTest(unittest.TestCase):
    def test_finds_capitalized_word_repeated_and_not_sentence_initial(self):
        cards_text = [
            "isso e uma historia",
            "sobre o Bernardo e a Lenora",
            "so que ai o Bernardo morre",
            "e a Lenora fica triste",
        ]

        names = glossary_service.extract_candidate_names(cards_text)

        self.assertIn("Bernardo", names)
        self.assertIn("Lenora", names)

    def test_ignores_sentence_initial_capital_seen_only_once(self):
        cards_text = ["Isso e uma historia unica"]

        names = glossary_service.extract_candidate_names(cards_text)

        self.assertEqual(names, set())


class InferGenderTest(unittest.TestCase):
    def test_male_article_and_participle_agreement(self):
        cards_text = ["o Bernardo foi rejeitado", "ele morreu sozinho"]

        gender = glossary_service.infer_gender("Bernardo", cards_text)

        self.assertEqual(gender, "male")

    def test_female_article_and_participle_agreement(self):
        cards_text = ["a Lenora foi rejeitada", "ela ficou triste"]

        gender = glossary_service.infer_gender("Lenora", cards_text)

        self.assertEqual(gender, "female")

    def test_unknown_when_no_signal(self):
        cards_text = ["Bernardo apareceu no video"]

        gender = glossary_service.infer_gender("Bernardo", cards_text)

        self.assertEqual(gender, "unknown")


class ChannelGlossaryPersistenceTest(unittest.TestCase):
    def test_locked_entry_is_never_overwritten_on_merge(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "glossario_canal.json"
            path.write_text(
                json.dumps({"characters": [{"source_name": "Bernardo", "zh": "伯纳多", "gender": "male"}], "terms": []}),
                encoding="utf-8",
            )

            video_glossary = {"characters": [{"source_name": "Bernardo", "zh": "伯纳德", "gender": "male"}], "terms": []}
            merged = glossary_service.merge_into_channel_glossary(video_glossary, path)

            self.assertEqual(merged["characters"][0]["zh"], "伯纳多")

    def test_new_entry_is_added(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "glossario_canal.json"

            video_glossary = {"characters": [{"source_name": "Edgar", "zh": "埃德加", "gender": "male"}], "terms": []}
            merged = glossary_service.merge_into_channel_glossary(video_glossary, path)

            self.assertEqual(len(merged["characters"]), 1)
            reloaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(reloaded["characters"][0]["source_name"], "Edgar")


class BuildVideoGlossaryTest(unittest.TestCase):
    def test_reuses_canonical_zh_from_channel_glossary(self):
        translator = mock.Mock()
        translator.translate_segments.return_value = ["NAO DEVERIA SER CHAMADO"]

        channel_glossary = {"characters": [{"source_name": "Bernardo", "zh": "伯纳多", "gender": "male", "variants": []}], "terms": []}
        cards_text = ["o Bernardo morreu"]

        result = glossary_service.build_video_glossary(cards_text, channel_glossary, translator, source_lang="pt", target_lang="zh")

        bernardo = next(c for c in result["characters"] if c["source_name"] == "Bernardo")
        self.assertEqual(bernardo["zh"], "伯纳多")
        translator.translate_segments.assert_not_called()

    def test_translates_new_name_once_and_locks_it(self):
        translator = mock.Mock()
        translator.translate_segments.return_value = ["埃德加"]

        channel_glossary = {"characters": [], "terms": []}
        cards_text = ["o Edgar chegou", "e o Edgar foi embora"]

        result = glossary_service.build_video_glossary(cards_text, channel_glossary, translator, source_lang="pt", target_lang="zh")

        edgar = next(c for c in result["characters"] if c["source_name"] == "Edgar")
        self.assertEqual(edgar["zh"], "埃德加")
        translator.translate_segments.assert_called_once()

    def test_known_short_name_is_not_falsely_reused_as_substring_of_another_name(self):
        # "Ana" (conhecido) nao pode "aparecer" so por ser substring de
        # "Anacleto" (personagem diferente, nao mencionado de verdade).
        translator = mock.Mock()
        translator.translate_segments.return_value = ["安纳克莱托"]
        channel_glossary = {"characters": [{"source_name": "Ana", "zh": "安娜", "gender": "female", "variants": []}], "terms": []}
        cards_text = ["o Anacleto chegou", "e o Anacleto saiu"]

        result = glossary_service.build_video_glossary(cards_text, channel_glossary, translator, source_lang="pt", target_lang="zh")

        self.assertNotIn("Ana", [c["source_name"] for c in result["characters"]])


class BuildVideoGlossaryLlmTest(unittest.TestCase):
    """Estagio 1 via LLM local: a transcricao inteira vai pro modelo, que
    devolve resumo/personagens/termos/registro/ilegiveis. Entradas do
    glossario do canal sao TRAVADAS — grafia existente nunca e reescrita."""

    CARDS = [
        {"i": 0, "start": 0.0, "end": 0.8, "text": "todo mundo rejeita", "segment_id": 0, "avg_logprob": -0.2},
        {"i": 1, "start": 0.8, "end": 1.9, "text": "o Edgar, o Bernardo", "segment_id": 0, "avg_logprob": -0.2},
        {"i": 2, "start": 1.9, "end": 3.4, "text": "REJEITADO", "segment_id": 1, "avg_logprob": -0.9},
    ]

    def _client(self, response):
        client = mock.Mock()
        client.chat_json.return_value = response
        return client

    def test_locked_channel_entry_overrides_llm_rendering(self):
        channel = {"characters": [{"source_name": "Bernardo", "zh": "伯纳多", "gender": "male", "variants": []}], "terms": []}
        client = self._client({
            "summary": "s", "register": "r", "terms": [], "unclear": [],
            "characters": [
                {"source_name": "Bernardo", "variants": [], "zh": "伯纳德", "gender": "female", "relations": "unknown", "note": ""},
                {"source_name": "Edgar", "variants": ["Edgar"], "zh": "埃德加", "gender": "male", "relations": "unknown", "note": ""},
            ],
        })

        sheet = glossary_service.build_video_glossary_llm(self.CARDS, channel, video_type="corte", client=client)

        bernardo = next(c for c in sheet["characters"] if c["source_name"] == "Bernardo")
        self.assertEqual(bernardo["zh"], "伯纳多")
        self.assertEqual(bernardo["gender"], "male")

    def test_channel_entry_mentioned_but_omitted_by_llm_is_added(self):
        channel = {"characters": [{"source_name": "Bernardo", "zh": "伯纳多", "gender": "male", "variants": []}], "terms": []}
        client = self._client({"summary": "s", "register": "r", "terms": [], "unclear": [], "characters": []})

        sheet = glossary_service.build_video_glossary_llm(self.CARDS, channel, video_type="corte", client=client)

        self.assertIn("Bernardo", [c["source_name"] for c in sheet["characters"]])

    def test_channel_entry_not_mentioned_is_not_added(self):
        channel = {"characters": [{"source_name": "Zulmira", "zh": "祖尔米拉", "gender": "female", "variants": []}], "terms": []}
        client = self._client({"summary": "s", "register": "r", "terms": [], "unclear": [], "characters": []})

        sheet = glossary_service.build_video_glossary_llm(self.CARDS, channel, video_type="corte", client=client)

        self.assertNotIn("Zulmira", [c["source_name"] for c in sheet["characters"]])

    def test_locked_term_overrides_llm_rendering(self):
        channel = {"characters": [], "terms": [{"source": "Roberto Careca", "zh": "光头罗伯托", "note": "canal"}]}
        client = self._client({
            "summary": "s", "register": "r", "unclear": [], "characters": [],
            "terms": [{"source": "Roberto Careca", "zh": "秃头罗伯托", "note": ""}],
        })

        sheet = glossary_service.build_video_glossary_llm(self.CARDS, channel, video_type="corte", client=client)

        self.assertEqual(sheet["terms"][0]["zh"], "光头罗伯托")

    def test_low_confidence_cards_are_marked_in_prompt_and_unclear_is_normalized(self):
        channel = {"characters": [], "terms": []}
        client = self._client({"summary": "s", "register": "r", "terms": [], "characters": [], "unclear": ["2"]})

        sheet = glossary_service.build_video_glossary_llm(self.CARDS, channel, video_type="corte", client=client)

        user_prompt = client.chat_json.call_args.kwargs["user"]
        self.assertIn('"low_confidence": true', user_prompt)
        self.assertIn("corte", user_prompt)
        self.assertNotIn("segment_id", user_prompt)
        self.assertEqual(sheet["unclear"], [2])

    def test_missing_keys_get_defaults(self):
        client = self._client({"characters": [{"source_name": "Edgar", "zh": "埃德加"}]})

        sheet = glossary_service.build_video_glossary_llm(self.CARDS, {"characters": [], "terms": []}, video_type="", client=client)

        self.assertEqual(sheet["summary"], "")
        self.assertEqual(sheet["terms"], [])
        self.assertEqual(sheet["unclear"], [])
        self.assertEqual(sheet["characters"][0]["gender"], "unknown")
        self.assertEqual(sheet["characters"][0]["variants"], [])


if __name__ == "__main__":
    unittest.main()
