import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import subtitle_validation as v


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

    def test_long_line_is_fine_for_english_target(self):
        # O teto de 20 caracteres modela "cabe numa linha de video vertical"
        # pro chines (hanzi denso). Ingles precisa de bem mais caracteres pra
        # dizer a mesma coisa — aplicar o mesmo teto rejeitaria quase toda
        # frase em ingles (ex.: quebraria o modo "Chines + ingles" da queima
        # inteiro por causa so da perna em ingles).
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "frase bem mais longa do que o normal"}]
        groups = [
            {
                "cards": [0],
                "start": 0.0,
                "end": 2.0,
                "zh": "this is a much longer sentence than usual, well over twenty characters",
                "flag": "",
            }
        ]

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


GLOSSARIO = {
    "characters": [
        {"source_name": "Edgar", "variants": [], "zh": "埃德加", "gender": "male"},
        {"source_name": "Bernardo", "variants": [], "zh": "伯纳多", "gender": "male"},
        {"source_name": "Lenora", "variants": [], "zh": "莱诺拉", "gender": "female"},
    ]
}


def _erros(groups, cards, glossary=GLOSSARIO):
    try:
        v.validate_translation_output(groups, cards, glossary=glossary, target_lang="zh")
    except v.ValidationError as error:
        return str(error)
    return ""


class ErrosAuditadosTest(unittest.TestCase):
    """Cada teste reproduz um erro real encontrado na auditoria do video de
    42s. A validacao tem que APONTAR o grupo e a regra, nao so falhar."""

    def test_erro_1_fragmento_traduzido_isolado(self):
        # "SÓ QUE AÍ" virou um card sozinho na tela por 0.6s -> tempo minimo.
        cards = [
            {"i": 7, "start": 7.4, "end": 8.0, "text": "só que aí"},
            {"i": 8, "start": 8.0, "end": 9.8, "text": "o Bernardo morre"},
        ]
        groups = [
            {"cards": [7], "start": 7.4, "end": 8.0, "zh": "伯纳德", "flag": ""},
            {"cards": [8], "start": 8.0, "end": 9.8, "zh": "伯纳多死了", "flag": ""},
        ]

        erros = _erros(groups, cards)

        self.assertIn("grupo [7]", erros)
        self.assertIn("min 1.2s", erros)

    def test_erro_3_sujeito_masculino_com_她(self):
        # "o Bernardo morre" -> 她死了: fonte so menciona homem, nada de "ela".
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "só que aí o Bernardo morre"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "结果她死了", "flag": ""}]

        erros = _erros(groups, cards)

        self.assertIn("grupo [0]", erros)
        self.assertIn("她", erros)
        self.assertIn("Bernardo", erros)

    def test_erro_3_她_permitido_quando_fonte_tem_mulher(self):
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "a Lenora fica triste"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "她很难过", "flag": ""}]

        self.assertEqual(_erros(groups, cards), "")

    def test_erro_3_她_permitido_quando_fonte_usa_ela_sem_nome(self):
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "o Bernardo diz que ela já foi"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "伯纳多说她已经走了", "flag": ""}]

        self.assertEqual(_erros(groups, cards), "")

    def test_erro_3_nome_feminino_como_objeto_nao_impede_他(self):
        # "tenta casar com a Isabel": sujeito elidido (Edgar), Isabel e objeto.
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "tenta casar com a Isabel,"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "结果他去娶伊莎贝尔", "flag": ""}]
        glossario = {"characters": GLOSSARIO["characters"] + [{"source_name": "Isabel", "variants": [], "zh": "伊莎贝尔", "gender": "female"}]}

        self.assertEqual(_erros(groups, cards, glossario), "")

    def test_erro_3_nome_masculino_como_objeto_nao_impede_她(self):
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "vai ver o túmulo do Bernardo"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "她去看伯纳多的墓地", "flag": ""}]

        self.assertEqual(_erros(groups, cards), "")

    def test_erro_3_sujeito_feminino_com_他(self):
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "a Lenora fica triste"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "他很难过", "flag": ""}]

        self.assertIn("他", _erros(groups, cards))

    def test_erro_4_他嫁给_homem_casando_como_noiva(self):
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "o Edgar tentou casar com a Lenora"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "他试图嫁给莱诺拉", "flag": ""}]

        erros = _erros(groups, cards)

        self.assertIn("grupo [0]", erros)
        self.assertIn("嫁给", erros)

    def test_erro_4_nome_masculino_antes_de_嫁给(self):
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "o Edgar tentou casar com a Lenora"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "埃德加想嫁给莱诺拉", "flag": ""}]

        self.assertIn("嫁给", _erros(groups, cards))

    def test_erro_4_formas_corretas_passam(self):
        cards = [
            {"i": 0, "start": 0.0, "end": 2.0, "text": "o Edgar tentou casar com a Lenora"},
            {"i": 1, "start": 2.0, "end": 4.0, "text": "o Bernardo se casou com a Lenora"},
            {"i": 2, "start": 4.0, "end": 6.0, "text": "a Lenora se casou com o Bernardo"},
        ]
        groups = [
            {"cards": [0], "start": 0.0, "end": 2.0, "zh": "埃德加想娶莱诺拉", "flag": ""},
            {"cards": [1], "start": 2.0, "end": 4.0, "zh": "伯纳多和莱诺拉结婚了", "flag": ""},
            {"cards": [2], "start": 4.0, "end": 6.0, "zh": "莱诺拉嫁给了伯纳多", "flag": ""},
        ]

        self.assertEqual(_erros(groups, cards), "")

    def test_pontuacao_latina_e_reprovada(self):
        # Legenda chinesa nao usa virgula/ponto latinos — o modelo as vezes
        # devolve "尝试娶伊莎贝尔," com a virgula ASCII.
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "tenta casar com a Isabel"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "尝试娶伊莎贝尔,", "flag": ""}]

        erros = _erros(groups, cards)

        self.assertIn("grupo [0]", erros)
        self.assertIn("pontuacao latina", erros)

    def test_pontuacao_chinesa_passa(self):
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "ele veio, ela foi"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "他来了，她走了！", "flag": ""}]

        self.assertEqual(_erros(groups, cards), "")

    def test_erro_5_nome_em_latim(self):
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "lá no Edgar"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "在Edgar那里", "flag": ""}]

        erros = _erros(groups, cards)

        self.assertIn("latino", erros)

    def test_erro_5_grafia_divergente_com_sufixo_extra(self):
        # 埃德加尔 (Edgar + 尔) no mesmo video que 埃德加 (canonico).
        cards = [
            {"i": 0, "start": 0.0, "end": 2.0, "text": "o Edgar chegou"},
            {"i": 1, "start": 2.0, "end": 4.0, "text": "e o Edgar saiu"},
        ]
        groups = [
            {"cards": [0], "start": 0.0, "end": 2.0, "zh": "埃德加来了", "flag": ""},
            {"cards": [1], "start": 2.0, "end": 4.0, "zh": "然后埃德加尔走了", "flag": ""},
        ]

        erros = _erros(groups, cards)

        self.assertIn("grupo [1]", erros)
        self.assertIn("埃德加尔", erros)
        self.assertIn("埃德加", erros)

    def test_erro_5_grafia_divergente_com_ultimo_caractere_trocado(self):
        # 伯纳德 (Bernard) em vez de 伯纳多 (Bernardo), sem lista de variantes.
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "o Bernardo morre"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "伯纳德死了", "flag": ""}]

        erros = _erros(groups, cards)

        self.assertIn("伯纳德", erros)
        self.assertIn("伯纳多", erros)

    def test_erro_6_alucinacao_em_card_de_baixa_confianca_e_reportada(self):
        # "REJEITADO" (avg_logprob baixo) virou "我也是最好的". O pipeline poe
        # a flag no grupo; a validacao tem que reportar o grupo e a flag.
        cards = [{"i": 3, "start": 3.0, "end": 4.5, "text": "REJEITADO"}]
        groups = [
            {"cards": [3], "start": 3.0, "end": 4.5, "zh": "我也是最好的", "flag": "transcricao de baixa confianca (avg_logprob=-0.95)"}
        ]

        erros = _erros(groups, cards)

        self.assertIn("grupo [3]", erros)
        self.assertIn("FLAG", erros)
        self.assertIn("baixa confianca", erros)

    def test_mensagem_lista_todas_as_regras_violadas(self):
        cards = [{"i": 0, "start": 0.0, "end": 0.5, "text": "o Bernardo morre"}]
        groups = [{"cards": [0], "start": 0.0, "end": 0.5, "zh": "Bernardo她死了" + "啊" * 20, "flag": "x"}]

        erros = _erros(groups, cards)

        for regra in ("latino", "max 20", "min 1.2s", "FLAG", "她"):
            self.assertIn(regra, erros)


class TrocaDePersonagemTest(unittest.TestCase):
    """Erro real do 7B: 'Lenora não pode casar com o Edgar' saiu
    '伊莎贝尔不能嫁埃德加' — trocou Lenora por Isabel. O nome da fonte
    sumiu E um nome que nao esta na fonte apareceu no lugar."""

    GLOSSARIO = {
        "characters": [
            {"source_name": "Edgar", "variants": [], "zh": "埃德加", "gender": "male"},
            {"source_name": "Bernardo", "variants": [], "zh": "伯纳多", "gender": "male"},
            {"source_name": "Lenora", "variants": [], "zh": "莱诺拉", "gender": "female"},
            {"source_name": "Isabel", "variants": [], "zh": "伊莎贝尔", "gender": "female"},
        ]
    }

    def test_swapped_character_is_reported(self):
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "Lenora não pode casar com o Edgar"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "伊莎贝尔不能嫁埃德加", "flag": ""}]

        erros = _erros(groups, cards, self.GLOSSARIO)

        self.assertIn("grupo [0]", erros)
        self.assertIn("Lenora", erros)
        self.assertIn("伊莎贝尔", erros)

    def test_restored_subject_absent_from_source_is_allowed(self):
        # Regra 3 do prompt: o chines precisa do sujeito que o portugues
        # elide. Nenhum nome da fonte sumiu, entao nao e troca.
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "tenta casar com a Isabel"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "埃德加想娶伊莎贝尔", "flag": ""}]

        self.assertEqual(_erros(groups, cards, self.GLOSSARIO), "")

    def test_name_replaced_by_pronoun_is_allowed(self):
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "só que aí o Bernardo morre"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "结果他死了", "flag": ""}]

        self.assertEqual(_erros(groups, cards, self.GLOSSARIO), "")

    def test_all_source_names_present_is_allowed(self):
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "Lenora não pode casar com o Edgar"}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": "莱诺拉不能嫁给埃德加", "flag": ""}]

        self.assertEqual(_erros(groups, cards, self.GLOSSARIO), "")


class VerboDeCasamentoObjetoTest(unittest.TestCase):
    """嫁给 X = casar com X (X homem); 娶 X = casar com X (X mulher). Com
    duas pessoas do mesmo genero, o natural e 和…结婚. Casos reais:
    '莱诺拉嫁给了伊莎贝尔' e '埃德加想娶伯纳多'."""

    GLOSSARIO = {
        "characters": [
            {"source_name": "Edgar", "variants": [], "zh": "埃德加", "gender": "male"},
            {"source_name": "Bernardo", "variants": [], "zh": "伯纳多", "gender": "male"},
            {"source_name": "Lenora", "variants": [], "zh": "莱诺拉", "gender": "female"},
            {"source_name": "Isabel", "variants": [], "zh": "伊莎贝尔", "gender": "female"},
        ]
    }

    def _erros(self, zh, text):
        cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": text}]
        groups = [{"cards": [0], "start": 0.0, "end": 2.0, "zh": zh, "flag": ""}]
        return _erros(groups, cards, self.GLOSSARIO)

    def test_嫁给_mulher_e_reprovado(self):
        erros = self._erros("莱诺拉嫁给了伊莎贝尔", "Lenora casa com Isabel")

        self.assertIn("grupo [0]", erros)
        self.assertIn("嫁给", erros)
        self.assertIn("伊莎贝尔", erros)

    def test_嫁_sem_给_com_mulher_e_reprovado(self):
        # Caso real do 14b: "她伤心再嫁伊莎贝尔".
        erros = self._erros("她伤心再嫁伊莎贝尔", "ela casa novamente com a Isabel")

        self.assertIn("伊莎贝尔", erros)

    def test_娶_homem_e_reprovado(self):
        erros = self._erros("埃德加想娶伯纳多", "o Edgar tenta casar com o Bernardo")

        self.assertIn("娶", erros)
        self.assertIn("伯纳多", erros)

    def test_嫁给_homem_passa(self):
        self.assertEqual(self._erros("莱诺拉嫁给了伯纳多", "a Lenora casa com o Bernardo"), "")

    def test_娶_mulher_passa(self):
        self.assertEqual(self._erros("埃德加想娶莱诺拉", "o Edgar tenta casar com a Lenora"), "")

    def test_forma_neutra_passa(self):
        self.assertEqual(self._erros("莱诺拉和伊莎贝尔结婚了", "Lenora casa com Isabel"), "")


if __name__ == "__main__":
    unittest.main()
