import importlib.util
import json
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock


def load_subtitle_service():
    sys.modules["faster_whisper"] = types.SimpleNamespace(WhisperModel=object)
    module_path = Path(__file__).with_name("subtitle_service.py")
    spec = importlib.util.spec_from_file_location("subtitle_service_for_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@dataclass
class WordInfo:
    word: str
    start: float
    end: float


class NaturalSubtitleSegmentationTest(unittest.TestCase):
    def setUp(self):
        self.service = load_subtitle_service()

    def make_words(self, words: list[str], step: float = 0.25) -> list[WordInfo]:
        return [WordInfo(word=word, start=index * step, end=(index + 1) * step) for index, word in enumerate(words)]

    def segment_text(self, segments) -> list[str]:
        return [" ".join(word.word.strip() for word in segment) for segment in segments]

    def test_pulls_next_word_when_target_would_end_on_weak_word(self):
        words = self.make_words("eu tenho que pegar aquela chave ali".split())

        segments = self.service.segment_words_naturally(words, target_words=3)

        self.assertEqual(
            self.segment_text(segments),
            ["eu tenho que pegar", "aquela chave ali"],
        )

    def test_avoids_lonely_tail_word_when_previous_block_can_absorb_it(self):
        words = self.make_words("pegar aquela chave ali".split())

        segments = self.service.segment_words_naturally(words, target_words=3)

        self.assertEqual(self.segment_text(segments), ["pegar aquela chave ali"])


class ResolveMaxWordsForVideoTest(unittest.TestCase):
    def setUp(self):
        self.service = load_subtitle_service()

    def test_portrait_video_upgrades_zero_to_shorts_default(self):
        portrait_info = types.SimpleNamespace(duration_sec=5.0, width=1080, height=1920)
        with mock.patch.object(self.service.ffmpeg_utils, "probe_video", return_value=portrait_info):
            result = self.service.resolve_max_words_for_video("video.mp4", max_words=0)

        self.assertEqual(result, self.service.DEFAULT_MAX_WORDS_SHORTS)

    def test_landscape_video_keeps_zero(self):
        landscape_info = types.SimpleNamespace(duration_sec=5.0, width=1920, height=1080)
        with mock.patch.object(self.service.ffmpeg_utils, "probe_video", return_value=landscape_info):
            result = self.service.resolve_max_words_for_video("video.mp4", max_words=0)

        self.assertEqual(result, 0)

    def test_explicit_max_words_is_never_overridden(self):
        portrait_info = types.SimpleNamespace(duration_sec=5.0, width=1080, height=1920)
        with mock.patch.object(self.service.ffmpeg_utils, "probe_video", return_value=portrait_info):
            result = self.service.resolve_max_words_for_video("video.mp4", max_words=5)

        self.assertEqual(result, 5)

    def test_probe_failure_keeps_max_words_unchanged(self):
        with mock.patch.object(self.service.ffmpeg_utils, "probe_video", side_effect=RuntimeError("sem ffprobe")):
            result = self.service.resolve_max_words_for_video("audio.mp3", max_words=0)

        self.assertEqual(result, 0)


class TranscribeVideoTranslationTest(unittest.TestCase):
    def setUp(self):
        self.service = load_subtitle_service()

    def test_translate_to_writes_extra_srt_files_and_emits_events(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / "video.mp4"
            input_path.write_bytes(b"fake")

            @dataclass
            class FakeSegment:
                start: float
                end: float
                text: str
                words: list

            # duration >= 1.2s (min_duration exigido por subtitle_validation) pra
            # nao cair no branch de erro antes mesmo de checar o texto traduzido.
            fake_segments = [FakeSegment(start=0.0, end=1.5, text="ola mundo", words=[])]
            fake_info = types.SimpleNamespace(language="pt", language_probability=0.99, duration=1.5)

            class FakeWhisperModel:
                def __init__(self, *args, **kwargs):
                    pass

                def transcribe(self, *args, **kwargs):
                    return fake_segments, fake_info

            self.service.WhisperModel = FakeWhisperModel

            captured_calls = []

            class FakeTranslator:
                def __init__(self, device, compute_type):
                    pass

                def translate_segments(self, texts, source_lang, target_lang):
                    captured_calls.append((tuple(texts), source_lang, target_lang))
                    if target_lang == "zh":
                        return ["你好世界" for _ in texts]
                    return [f"[{target_lang}] {text}" for text in texts]

            self.service.translate_service.Translator = FakeTranslator

            # Aponta pra um glossario dentro do tmp_dir — sem isso o pipeline novo
            # gravaria (mesmo vazio) no path padrao real do canal.
            channel_glossary_path = Path(tmp_dir) / "glossario_canal.json"
            output_path = self.service.transcribe_video(
                input_path=str(input_path),
                translate_to=["en", "zh"],
                channel_glossary_path=str(channel_glossary_path),
            )

            en_path = Path(output_path).with_suffix(".en.srt")
            zh_path = Path(output_path).with_suffix(".zh.srt")

            self.assertTrue(en_path.exists())
            self.assertTrue(zh_path.exists())
            self.assertIn("[en] ola mundo", en_path.read_text(encoding="utf-8"))
            self.assertIn("你好世界", zh_path.read_text(encoding="utf-8"))
            self.assertEqual(
                captured_calls,
                [(("ola mundo",), "pt", "en"), (("ola mundo",), "pt", "zh")],
            )

    def test_translation_failure_does_not_break_main_transcription(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / "video.mp4"
            input_path.write_bytes(b"fake")

            @dataclass
            class FakeSegment:
                start: float
                end: float
                text: str
                words: list

            fake_segments = [FakeSegment(start=0.0, end=1.0, text="ola mundo", words=[])]
            fake_info = types.SimpleNamespace(language="pt", language_probability=0.99, duration=1.0)

            class FakeWhisperModel:
                def __init__(self, *args, **kwargs):
                    pass

                def transcribe(self, *args, **kwargs):
                    return fake_segments, fake_info

            self.service.WhisperModel = FakeWhisperModel

            class FailingTranslator:
                def __init__(self, device, compute_type):
                    pass

                def translate_segments(self, texts, source_lang, target_lang):
                    raise RuntimeError("sem internet")

            self.service.translate_service.Translator = FailingTranslator

            output_path = self.service.transcribe_video(
                input_path=str(input_path),
                translate_to=["en"],
            )

            self.assertTrue(Path(output_path).exists())
            en_path = Path(output_path).with_suffix(".en.srt")
            self.assertFalse(en_path.exists())

    def test_translate_to_uses_grouped_pipeline_instead_of_card_by_card(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / "video.mp4"
            input_path.write_bytes(b"fake")

            # "Bernardo" precisa aparecer 2x (nome novo, extract_candidate_names
            # exige frequencia >=2 pra nao dar falso positivo).
            sentence = "so que ai o Bernardo morre e Bernardo desaparece"
            words = [
                WordInfo(word=w, start=float(i) * 0.3, end=float(i) * 0.3 + 0.3)
                for i, w in enumerate(sentence.split())
            ]

            @dataclass
            class FakeSegment:
                start: float
                end: float
                text: str
                words: list
                avg_logprob: float

            fake_segments = [
                FakeSegment(start=0.0, end=words[-1].end, text=sentence, words=words, avg_logprob=-0.1)
            ]
            fake_info = types.SimpleNamespace(language="pt", language_probability=0.99, duration=words[-1].end)

            class FakeWhisperModel:
                def __init__(self, *args, **kwargs):
                    pass

                def transcribe(self, *args, **kwargs):
                    return fake_segments, fake_info

            self.service.WhisperModel = FakeWhisperModel

            class FakeTranslator:
                def __init__(self, device, compute_type):
                    pass

                def translate_segments(self, texts, source_lang, target_lang):
                    # a frase inteira, de uma vez so (pipeline novo agrupa por
                    # segment_id) — nao card a card.
                    if texts == [sentence]:
                        return ["结果伯纳多死了"]
                    return [f"[{target_lang}] {t}" for t in texts]  # nome isolado no glossario

            self.service.translate_service.Translator = FakeTranslator

            channel_glossary_path = Path(tmp_dir) / "glossario_canal.json"
            output_path = self.service.transcribe_video(
                input_path=str(input_path),
                max_words=3,  # gera VARIOS cards de exibicao, todos do mesmo segment_id
                translate_to=["zh"],
                channel_glossary_path=str(channel_glossary_path),
            )

            zh_path = Path(output_path).with_suffix(".zh.srt")
            content = zh_path.read_text(encoding="utf-8")
            self.assertIn("结果伯纳多死了", content)
            self.assertEqual(content.count(" --> "), 1)  # 1 grupo, nao 1 por card

    def test_long_natural_segment_without_max_words_gets_split_by_duration(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / "video.mp4"
            input_path.write_bytes(b"fake")

            sentence = (
                "isso e uma fala continua que nao tem pausa detectada pelo vad "
                "e dura mais de dez segundos no total"
            ).split()
            words = [WordInfo(word=word, start=float(i), end=float(i) + 0.9) for i, word in enumerate(sentence)]

            @dataclass
            class FakeSegment:
                start: float
                end: float
                text: str
                words: list

            fake_segments = [
                FakeSegment(start=0.0, end=words[-1].end, text=" ".join(w.word for w in words), words=words)
            ]
            fake_info = types.SimpleNamespace(language="pt", language_probability=0.99, duration=words[-1].end)

            class FakeWhisperModel:
                def __init__(self, *args, **kwargs):
                    pass

                def transcribe(self, *args, **kwargs):
                    return fake_segments, fake_info

            self.service.WhisperModel = FakeWhisperModel

            output_path = self.service.transcribe_video(input_path=str(input_path), max_words=0)

            srt_content = Path(output_path).read_text(encoding="utf-8")
            # Sem o fallback, isso viraria UMA legenda estatica cobrindo os ~19s inteiros
            # da fala continua. Com o fallback, deve virar varios blocos menores.
            self.assertGreater(srt_content.count(" --> "), 1)

    def test_writes_cards_json_sidecar_with_segment_id_and_confidence(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / "video.mp4"
            input_path.write_bytes(b"fake")

            @dataclass
            class FakeSegment:
                start: float
                end: float
                text: str
                words: list
                avg_logprob: float

            fake_segments = [
                FakeSegment(start=0.0, end=1.0, text="primeira frase", words=[], avg_logprob=-0.1),
                FakeSegment(start=1.5, end=2.5, text="segunda frase", words=[], avg_logprob=-0.9),
            ]
            fake_info = types.SimpleNamespace(language="pt", language_probability=0.99, duration=2.5)

            class FakeWhisperModel:
                def __init__(self, *args, **kwargs):
                    pass

                def transcribe(self, *args, **kwargs):
                    return fake_segments, fake_info

            self.service.WhisperModel = FakeWhisperModel

            output_path = self.service.transcribe_video(input_path=str(input_path), max_words=0)

            cards_path = Path(output_path).with_suffix(".cards.json")
            self.assertTrue(cards_path.exists())
            cards = json.loads(cards_path.read_text(encoding="utf-8"))
            self.assertEqual(len(cards), 2)
            self.assertEqual(cards[0]["segment_id"], 0)
            self.assertEqual(cards[1]["segment_id"], 1)
            self.assertAlmostEqual(cards[0]["avg_logprob"], -0.1)
            self.assertAlmostEqual(cards[1]["avg_logprob"], -0.9)

    def test_cards_from_same_whisper_segment_share_segment_id_and_keep_natural_case(self):
        # Prova a premissa de que a Task 2 depende: cards nascidos do mesmo
        # segmento do Whisper (max_words>0 fatia UM segmento em varios cards)
        # tem que sair com o MESMO segment_id. Tambem prova que o texto do
        # sidecar preserva o case original (nao aplica uppercase/lowercase da
        # config de exibicao) — sem isso, a extracao de nome de uma task
        # posterior nao funciona quando o usuario liga a opcao "uppercase" da
        # legenda.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / "video.mp4"
            input_path.write_bytes(b"fake")

            words = [
                WordInfo(word=w, start=float(i) * 0.3, end=float(i) * 0.3 + 0.3)
                for i, w in enumerate("so que ai o Bernardo morre".split())
            ]

            @dataclass
            class FakeSegment:
                start: float
                end: float
                text: str
                words: list
                avg_logprob: float

            fake_segments = [
                FakeSegment(
                    start=0.0, end=words[-1].end, text="so que ai o Bernardo morre", words=words, avg_logprob=-0.2
                )
            ]
            fake_info = types.SimpleNamespace(language="pt", language_probability=0.99, duration=words[-1].end)

            class FakeWhisperModel:
                def __init__(self, *args, **kwargs):
                    pass

                def transcribe(self, *args, **kwargs):
                    return fake_segments, fake_info

            self.service.WhisperModel = FakeWhisperModel

            output_path = self.service.transcribe_video(input_path=str(input_path), max_words=3, uppercase=True)

            cards = json.loads(Path(output_path).with_suffix(".cards.json").read_text(encoding="utf-8"))
            self.assertGreater(len(cards), 1)  # max_words=3 fatia a frase em mais de 1 card
            self.assertEqual({c["segment_id"] for c in cards}, {0})  # todos do MESMO segmento
            self.assertIn("Bernardo", " ".join(c["text"] for c in cards))  # case original, nao "BERNARDO"


if __name__ == "__main__":
    unittest.main()
