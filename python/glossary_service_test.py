import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import glossary_service  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
