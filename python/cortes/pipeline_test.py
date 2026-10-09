import itertools
import unittest
from unittest import mock

from llm_service import LLMUnavailableError

from cortes import pipeline
from cortes.candidates import Candidate
from cortes.media import SourceMedia
from cortes.pipeline import AnalyzeOptions


def ignore(*_args):
    return None


class AnalyzeValidationTest(unittest.TestCase):
    @mock.patch("cortes.pipeline.probe_source")
    def test_rejects_source_without_the_configured_audio_track(self, probe):
        probe.return_value = SourceMedia("E:\\b.mp4", 600.0, 60.0, 3840, 1080, 1)
        with self.assertRaisesRegex(ValueError, "faixa"):
            pipeline.analyze("E:\\b.mp4", AnalyzeOptions(), ignore, ignore)

    @mock.patch("cortes.pipeline.probe_source")
    def test_rejects_trecho_after_the_end_of_the_video(self, probe):
        probe.return_value = SourceMedia("E:\\b.mp4", 600.0, 60.0, 3840, 1080, 4)
        with self.assertRaisesRegex(ValueError, "Trecho vazio"):
            pipeline.analyze("E:\\b.mp4", AnalyzeOptions(start=700.0), ignore, ignore)


class ClipsFromTest(unittest.TestCase):
    def test_numbers_clips_from_boundaries(self):
        clips = pipeline.clips_from([0.0, 150.0, 300.0])
        self.assertEqual([(c.n, c.start, c.end) for c in clips], [(1, 0.0, 150.0), (2, 150.0, 300.0)])
        self.assertTrue(all(a.end == b.start for a, b in itertools.pairwise(clips)))


class FakeOllama:
    def __init__(self, up=True, error=None, payload=None):
        self.up, self.error, self.payload = up, error, payload

    def ensure_server_running(self):
        return self.up

    def chat_json(self, system, user, temperature=0):
        if self.error:
            raise self.error
        return self.payload


class RunJudgeTest(unittest.TestCase):
    def setUp(self):
        self.cands = [Candidate("C1", 30.0, 5.0)]
        self.notes = []

    def run_judge(self):
        return pipeline.run_judge("qwen2.5:14b-instruct", [], [], self.cands, 0.0, 100.0, ignore, self.notes.append)

    @mock.patch("cortes.pipeline.make_client")
    def test_ollama_down_means_rules_only_with_a_warning(self, make_client):
        make_client.return_value = FakeOllama(up=False)
        self.assertIsNone(self.run_judge())
        self.assertIn("Ollama", self.notes[0])

    @mock.patch("cortes.pipeline.make_client")
    def test_missing_model_means_rules_only_with_a_warning(self, make_client):
        make_client.return_value = FakeOllama(error=LLMUnavailableError("Ollama respondeu HTTP 404: model not found"))
        self.assertIsNone(self.run_judge())
        self.assertIn("404", self.notes[0])
        self.assertIsNone(self.cands[0].judge)

    @mock.patch("cortes.pipeline.make_client")
    def test_scores_candidates_and_returns_the_client(self, make_client):
        make_client.return_value = FakeOllama(payload={"notas": {"C1": 9}})
        self.assertIs(self.run_judge(), make_client.return_value)
        self.assertEqual(self.cands[0].judge, 9.0)
