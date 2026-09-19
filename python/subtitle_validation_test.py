import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import subtitle_validation as v  # noqa: E402


class ValidateTranslationOutputTest(unittest.TestCase):
    def test_passes_on_clean_output(self):
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "ola"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "你好", "flag": ""}]

        v.validate_translation_output(groups, cards, glossary={"characters": []}, target_lang="zh")  # nao deve levantar

    def test_missing_card_index_raises(self):
        cards = [{"i": 0, "start": 0.0, "end": 1.0, "text": "a"}, {"i": 1, "start": 1.0, "end": 2.0, "text": "b"}]
        groups = [{"cards": [0], "start": 0.0, "end": 1.0, "zh": "你好", "flag": ""}]

        with self.assertRaises(v.ValidationError) as ctx:
            v.validate_translation_output(groups, cards, glossary={"characters": []}, target_lang="zh")
        self.assertIn("cobertura", str(ctx.exception).lower())

    def test_latin_character_left_in_translation_raises_for_chinese_target(self):
        # Caso real: nome nao transliterado sobrou em letra latina.
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "o Edgar chegou"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "在Edgar那里", "flag": ""}]

        with self.assertRaises(v.ValidationError) as ctx:
            v.validate_translation_output(groups, cards, glossary={"characters": []}, target_lang="zh")
        self.assertIn("latino", str(ctx.exception).lower())

    def test_latin_characters_are_fine_for_english_target(self):
        # A checagem de "caractere latino" existe pro chines (script diferente
        # do portugues denuncia nome nao traduzido) — pra ingles, que USA o
        # alfabeto latino normalmente, essa regra nao pode se aplicar, senao
        # toda traducao pro ingles falharia.
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "ola mundo"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "hello world", "flag": ""}]

        v.validate_translation_output(groups, cards, glossary={"characters": []}, target_lang="en")  # nao deve levantar

    def test_line_over_20_chars_raises(self):
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "frase longa"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "这" * 21, "flag": ""}]

        with self.assertRaises(v.ValidationError) as ctx:
            v.validate_translation_output(groups, cards, glossary={"characters": []}, target_lang="zh")
        self.assertIn("20", str(ctx.exception))

    def test_group_shorter_than_1_2s_raises(self):
        cards = [{"i": 0, "start": 0.0, "end": 0.5, "text": "a"}]
        groups = [{"cards": [0], "start": 0.0, "end": 0.5, "zh": "你好", "flag": ""}]

        with self.assertRaises(v.ValidationError) as ctx:
            v.validate_translation_output(groups, cards, glossary={"characters": []}, target_lang="zh")
        self.assertIn("1.2", str(ctx.exception))

    def test_flagged_group_raises(self):
        # Caso real: alucinacao em trecho de baixa confianca deve ser sinalizada.
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "??? incompreensivel"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "我也是最好的", "flag": "transcricao de baixa confianca"}]

        with self.assertRaises(v.ValidationError) as ctx:
            v.validate_translation_output(groups, cards, glossary={"characters": []}, target_lang="zh")
        self.assertIn("flag", str(ctx.exception).lower())

    def test_name_variant_diverging_from_canonical_raises(self):
        # Caso real: mesmo nome com duas grafias diferentes no mesmo video.
        cards = [
            {"i": 0, "start": 0.0, "end": 2.0, "text": "o Bernardo chegou"},
            {"i": 1, "start": 2.0, "end": 4.0, "text": "o Bernardo saiu"},
        ]
        groups = [
            {"cards": [0], "start": 0.0, "end": 2.0, "zh": "伯纳多来了", "flag": ""},
            {"cards": [1], "start": 2.0, "end": 4.0, "zh": "伯纳德走了", "flag": ""},
        ]
        glossary = {"characters": [{"source_name": "Bernardo", "zh": "伯纳多", "variants": ["伯纳德"]}]}

        with self.assertRaises(v.ValidationError) as ctx:
            v.validate_translation_output(groups, cards, glossary=glossary, target_lang="zh")
        self.assertIn("bernardo", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
