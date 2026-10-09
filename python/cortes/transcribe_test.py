import unittest
from types import SimpleNamespace

from cortes.transcribe import transcribe_track


def segment(start, end, text, words):
    return SimpleNamespace(
        start=start,
        end=end,
        text=text,
        words=[SimpleNamespace(word=w, start=a, end=b, probability=0.9) for w, a, b in words],
    )


class FakeModel:
    def __init__(self, segments):
        self.segments = segments
        self.calls = []

    def transcribe(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return iter(self.segments), SimpleNamespace(language="en")


class TranscribeTrackTest(unittest.TestCase):
    def test_shifts_times_to_the_source_and_lets_whisper_detect_language(self):
        model = FakeModel([segment(0.0, 1.0, " Hello there.", [(" Hello", 0.0, 0.5), (" there.", 0.5, 1.0)])])
        progress = []
        words, segments = transcribe_track(model, "filme.wav", None, offset=100.0, on_progress=progress.append)
        self.assertEqual(
            words,
            [{"word": "Hello", "start": 100.0, "end": 100.5}, {"word": "there.", "start": 100.5, "end": 101.0}],
        )
        self.assertEqual(segments, [{"start": 100.0, "end": 101.0, "text": "Hello there."}])
        self.assertIsNone(model.calls[0][1]["language"])
        self.assertEqual(progress, [1.0])
