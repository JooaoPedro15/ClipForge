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
            )

            self.assertEqual(Path(output_srt).read_text(encoding="utf-8"), "")
            translator.translate_segments.assert_not_called()


if __name__ == "__main__":
    unittest.main()
