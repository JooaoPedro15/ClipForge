import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import whisper_words


class FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, media_path, **kwargs):
        self.calls.append(media_path)
        word = types.SimpleNamespace(word=" oi", start=0.0, end=0.4, probability=0.9)
        segment = types.SimpleNamespace(start=0.0, end=0.4, text=" oi", words=[word])
        return [segment], types.SimpleNamespace(language="pt", duration=0.4)


class LoadWordsTest(unittest.TestCase):
    def test_transcribes_once_and_reuses_the_cache(self):
        model = FakeModel()
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "gravacao.wav"
            media.write_bytes(b"fake")
            cache = Path(tmp) / "gravacao.words.a0.json"

            first = whisper_words.load_words(media, lambda: model, "pt", 5, cache=cache)
            second = whisper_words.load_words(media, lambda: model, "pt", 5, cache=cache)

            self.assertEqual([w["word"] for w in first], [" oi"])
            self.assertEqual(first, second)
            self.assertEqual(len(model.calls), 1)
            self.assertEqual(json.loads(cache.read_text(encoding="utf-8"))[0]["end"], 0.4)

    def test_default_cache_sits_next_to_the_media(self):
        model = FakeModel()
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "bruto.mp3"
            media.write_bytes(b"fake")

            whisper_words.load_words(media, lambda: model, "pt", 5)

            self.assertTrue((Path(tmp) / "bruto.words.json").exists())

    def test_empty_transcription_is_not_cached(self):
        model = FakeModel()
        model.transcribe = lambda media_path, **kwargs: ([], None)
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "jogo.wav"
            media.write_bytes(b"fake")

            self.assertEqual(whisper_words.load_words(media, lambda: model, "pt", 5), [])
            self.assertFalse((Path(tmp) / "jogo.words.json").exists())

    def test_model_loader_loads_once(self):
        loaded = []
        original = whisper_words.subtitle_service.load_whisper_model
        whisper_words.subtitle_service.load_whisper_model = lambda *args: loaded.append(args) or object()
        whisper_words._LOADED_MODELS.clear()
        try:
            get_model = whisper_words.model_loader("tiny", "cpu", "int8")
            self.assertIs(get_model(), get_model())
        finally:
            whisper_words.subtitle_service.load_whisper_model = original
            whisper_words._LOADED_MODELS.clear()
        self.assertEqual(len(loaded), 1)


if __name__ == "__main__":
    unittest.main()
