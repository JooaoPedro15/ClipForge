import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import translation_postprocess as pp  # noqa: E402


class NormalizeNamesTest(unittest.TestCase):
    def test_replaces_latin_name_left_untranslated(self):
        glossary = {"characters": [{"source_name": "Edgar", "zh": "埃德加", "variants": []}]}

        result = pp.normalize_names("在Edgar那里", glossary)

        self.assertEqual(result, "在埃德加那里")
        self.assertNotIn("Edgar", result)

    def test_replaces_known_variant_with_canonical(self):
        glossary = {"characters": [{"source_name": "Bernardo", "zh": "伯纳多", "variants": ["伯纳德"]}]}

        result = pp.normalize_names("伯纳德死了", glossary)

        self.assertEqual(result, "伯纳多死了")


class FixGenderAndMarriageVerbTest(unittest.TestCase):
    def test_fixes_she_to_he_for_single_known_male_character(self):
        glossary = {"characters": [{"source_name": "Bernardo", "zh": "伯纳多", "gender": "male"}]}

        result = pp.fix_gender_and_marriage_verb("她死了", source_text="o Bernardo morre", glossary=glossary)

        self.assertEqual(result, "他死了")

    def test_replaces_directional_marriage_verb_with_neutral_when_unsure(self):
        glossary = {"characters": [{"source_name": "Bernardo", "zh": "伯纳多", "gender": "male"}]}

        result = pp.fix_gender_and_marriage_verb("他试图嫁给伯纳多", source_text="o Bernardo se casou", glossary=glossary)

        self.assertNotIn("嫁给", result)

    def test_leaves_sentence_with_multiple_known_characters_untouched(self):
        glossary = {
            "characters": [
                {"source_name": "Bernardo", "zh": "伯纳多", "gender": "male"},
                {"source_name": "Lenora", "zh": "莱诺拉", "gender": "female"},
            ]
        }

        result = pp.fix_gender_and_marriage_verb(
            "她嫁给了他", source_text="a Lenora se casou com o Bernardo", glossary=glossary
        )

        self.assertEqual(result, "她嫁给了他")

    def test_short_name_substring_of_another_name_does_not_trigger_fix(self):
        # "Ana" (conhecida) nao pode "aparecer" so por ser substring de
        # "Anacleto" (personagem diferente, nao mencionado de verdade) —
        # senao corrigiria genero errado numa frase que nem fala da Ana.
        glossary = {"characters": [{"source_name": "Ana", "zh": "安娜", "gender": "female"}]}

        result = pp.fix_gender_and_marriage_verb("他死了", source_text="o Anacleto morreu", glossary=glossary)

        self.assertEqual(result, "他死了")


class LowConfidenceFlagTest(unittest.TestCase):
    def test_flags_group_below_threshold(self):
        flag = pp.confidence_flag(avg_logprob=-1.2, threshold=-0.6)

        self.assertTrue(flag)

    def test_no_flag_above_threshold(self):
        flag = pp.confidence_flag(avg_logprob=-0.2, threshold=-0.6)

        self.assertEqual(flag, "")


if __name__ == "__main__":
    unittest.main()
