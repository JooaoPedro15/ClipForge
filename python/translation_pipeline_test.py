import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import translation_pipeline  # noqa: E402


class TraduzirVideoTest(unittest.TestCase):
    def test_uppercase_applies_to_translated_text_before_writing(self):
        # O fluxo antigo (card a card) aplicava uppercase/lowercase no texto
        # traduzido antes de gravar o .srt — o pipeline novo precisa manter
        # isso, senao o toggle "uppercase" da UI para de valer so pra
        # legenda traduzida.
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            cards = [{"i": 0, "start": 0.0, "end": 2.0, "text": "ola mundo", "segment_id": 0, "avg_logprob": -0.1}]
            srt_path = tmp_path / "video.srt"
            cards_path = tmp_path / "video.cards.json"
            cards_path.write_text(json.dumps(cards), encoding="utf-8")
            channel_glossary_path = tmp_path / "glossario_canal.json"

            translator = mock.Mock()
            translator.translate_segments.return_value = ["hello world"]

            output_srt = translation_pipeline.traduzir_video(
                cards_path=str(cards_path),
                original_srt_path=str(srt_path),
                translator=translator,
                source_lang="pt",
                target_lang="en",
                channel_glossary_path=str(channel_glossary_path),
                uppercase=True,
            )

            content = Path(output_srt).read_text(encoding="utf-8")
            self.assertIn("HELLO WORLD", content)

    def test_full_pipeline_produces_grouped_srt_and_persists_glossary(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            # Texto em case NATURAL (nao all-caps) — e o que a transcricao grava
            # no sidecar independente da opcao "uppercase" da UI. "Bernardo"
            # mencionado 2x (nome novo, ainda nao no glossario do canal,
            # precisa da frequencia >=2 do heuristico de extracao).
            cards = [
                {"i": 0, "start": 0.0, "end": 0.4, "text": "So que ai", "segment_id": 0, "avg_logprob": -0.1},
                {"i": 1, "start": 0.4, "end": 1.0, "text": "o Bernardo", "segment_id": 0, "avg_logprob": -0.1},
                {"i": 2, "start": 1.0, "end": 1.6, "text": "morre e", "segment_id": 0, "avg_logprob": -0.1},
                {"i": 3, "start": 1.6, "end": 2.2, "text": "Bernardo suspira", "segment_id": 0, "avg_logprob": -0.1},
            ]
            srt_path = tmp_path / "video.srt"
            cards_path = tmp_path / "video.cards.json"
            cards_path.write_text(json.dumps(cards), encoding="utf-8")
            channel_glossary_path = tmp_path / "glossario_canal.json"

            translator = mock.Mock()
            # 1a chamada: nome "Bernardo" isolado (glossario). 2a chamada: a
            # frase inteira do unico grupo (todos os 4 cards sao do mesmo
            # segment_id, entao viram 1 grupo so).
            translator.translate_segments.side_effect = [["伯纳多"], ["结果伯纳多死了"]]

            output_srt = translation_pipeline.traduzir_video(
                cards_path=str(cards_path),
                original_srt_path=str(srt_path),
                translator=translator,
                source_lang="pt",
                target_lang="zh",
                channel_glossary_path=str(channel_glossary_path),
                engine="nllb",
            )

            content = Path(output_srt).read_text(encoding="utf-8")
            self.assertIn("结果伯纳多死了", content)
            self.assertEqual(content.count(" --> "), 1)  # 4 cards viraram 1 grupo

            canal = json.loads(channel_glossary_path.read_text(encoding="utf-8"))
            self.assertEqual(canal["characters"][0]["source_name"], "Bernardo")
            self.assertEqual(canal["characters"][0]["zh"], "伯纳多")

    def test_empty_cards_list_produces_empty_srt_without_calling_translator(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            cards_path = tmp_path / "video.cards.json"
            cards_path.write_text(json.dumps([]), encoding="utf-8")
            srt_path = tmp_path / "video.srt"
            channel_glossary_path = tmp_path / "glossario_canal.json"

            translator = mock.Mock()

            output_srt = translation_pipeline.traduzir_video(
                cards_path=str(cards_path),
                original_srt_path=str(srt_path),
                translator=translator,
                source_lang="pt",
                target_lang="zh",
                channel_glossary_path=str(channel_glossary_path),
                engine="nllb",
            )

            self.assertEqual(Path(output_srt).read_text(encoding="utf-8"), "")
            translator.translate_segments.assert_not_called()


class TraduzirCardsLlmTest(unittest.TestCase):
    """Caminho LLM: estagio 1 + estagio 2, SRT montado dos grupos."""

    CARDS = [
        {"i": 0, "start": 0.0, "end": 0.6, "text": "todo mundo rejeita", "segment_id": 0, "avg_logprob": -0.1},
        {"i": 1, "start": 0.6, "end": 1.9, "text": "o Edgar, o Bernardo,", "segment_id": 0, "avg_logprob": -0.1},
        {"i": 2, "start": 1.9, "end": 3.4, "text": "se casou com a Lenora.", "segment_id": 1, "avg_logprob": -0.1},
    ]

    SHEET = {
        "summary": "s", "register": "r", "terms": [], "unclear": [],
        "characters": [
            {"source_name": "Edgar", "variants": [], "zh": "埃德加", "gender": "male", "relations": "unknown", "note": ""},
            {"source_name": "Bernardo", "variants": [], "zh": "伯纳多", "gender": "male", "relations": "unknown", "note": ""},
            {"source_name": "Lenora", "variants": [], "zh": "莱诺拉", "gender": "female", "relations": "unknown", "note": ""},
        ],
    }

    def _client(self, lines):
        # 1a chamada: estagio 1 (sheet). Depois, uma chamada por frase — os
        # cards acima viram 2 frases ([0,1] fecha na virgula com 5 palavras; [2]).
        client = mock.Mock()
        client.is_available.return_value = True
        client.chat_json.side_effect = [self.SHEET, *lines]
        return client

    def test_srt_is_built_from_llm_groups_and_glossary_is_persisted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            out = tmp_path / "video.zh.srt"
            glossary_path = tmp_path / "glossario_canal.json"
            client = self._client([
                {"id": 0, "zh": "大家都拒绝埃德加", "flag": ""},
                {"id": 1, "zh": "伯纳多和莱诺拉结婚了", "flag": ""},
            ])
            translator = mock.Mock()

            translation_pipeline.traduzir_cards(
                self.CARDS, translator, "pt", "zh", str(out), str(glossary_path), llm_client=client, video_type="corte"
            )

            content = out.read_text(encoding="utf-8")
            self.assertEqual(content.count(" --> "), 2)
            self.assertIn("00:00:00,000 --> 00:00:01,899\n大家都拒绝埃德加", content)
            translator.translate_segments.assert_not_called()
            canal = json.loads(glossary_path.read_text(encoding="utf-8"))
            self.assertEqual({c["source_name"] for c in canal["characters"]}, {"Edgar", "Bernardo", "Lenora"})

    def test_validation_failure_writes_rejected_draft_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            out = tmp_path / "video.zh.srt"
            glossary_path = tmp_path / "glossario_canal.json"
            # Nome em latim sobrou na traducao, em todas as 3 tentativas da
            # frase 0 -> regra "caractere latino" reprova.
            client = self._client([
                {"id": 0, "zh": "大家都拒绝Ze", "flag": ""},
                {"id": 0, "zh": "大家都拒绝Ze", "flag": ""},
                {"id": 0, "zh": "大家都拒绝Ze", "flag": ""},
                {"id": 1, "zh": "伯纳多和莱诺拉结婚了", "flag": ""},
            ])

            with self.assertRaises(translation_pipeline.subtitle_validation.ValidationError) as ctx:
                translation_pipeline.traduzir_cards(
                    self.CARDS, mock.Mock(), "pt", "zh", str(out), str(glossary_path), llm_client=client
                )

            self.assertIn("caractere latino", str(ctx.exception))
            self.assertFalse(out.exists())
            self.assertTrue((tmp_path / "video.zh.REJEITADO.srt").exists())
            self.assertFalse(glossary_path.exists())  # glossario nao e fundido com saida reprovada

    def test_zh_without_ollama_raises_clear_error_instead_of_silent_nllb(self):
        client = mock.Mock()
        client.is_available.return_value = False
        client.base_url = "http://127.0.0.1:11434"
        client.model = "qwen"

        with self.assertRaises(translation_pipeline.llm_service.LLMUnavailableError) as ctx:
            translation_pipeline.traduzir_cards(self.CARDS, mock.Mock(), "pt", "zh", "x.srt", "g.json", llm_client=client)

        self.assertIn("ollama pull qwen", str(ctx.exception))

    def test_engine_nllb_skips_llm_even_for_zh(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            client = mock.Mock()
            translator = mock.Mock()
            # Nomes aparecem 1x cada -> heuristico nao extrai nenhum; so a
            # chamada dos 2 grupos (segment_id 0 e 1).
            translator.translate_segments.side_effect = [["好", "好"]]

            translation_pipeline.traduzir_cards(
                self.CARDS, translator, "pt", "zh", str(tmp_path / "v.zh.srt"), str(tmp_path / "g.json"),
                engine="nllb", llm_client=client,
            )

            client.chat_json.assert_not_called()
            client.is_available.assert_not_called()

    def test_english_always_uses_nllb(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            client = mock.Mock()
            translator = mock.Mock()
            translator.translate_segments.side_effect = [["everyone rejects Edgar, Bernardo", "married Lenora"]]

            translation_pipeline.traduzir_cards(
                self.CARDS, translator, "pt", "en", str(tmp_path / "v.en.srt"), str(tmp_path / "g.json"), llm_client=client
            )

            client.chat_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
