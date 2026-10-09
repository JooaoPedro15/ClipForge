import itertools
import unittest
from unittest import mock

from llm_service import LLMUnavailableError

from cortes import pipeline, store
from cortes.candidates import Candidate
from cortes.media import SourceMedia
from cortes.pipeline import AnalyzeOptions
from cortes.segmenter import Durations


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


class FakeTitles:
    def __init__(self):
        self.calls = 0

    def chat_json(self, system, user, temperature=0):
        self.calls += 1
        return {"titulo": "Novo", "gancho": 6}


def analysis_with_old_clips() -> store.Analysis:
    return store.Analysis(
        source={"path": "E:\\b.mp4", "duration_sec": 600.0, "fps": 60.0, "width": 3840, "height": 1080, "audio_streams": 4},
        options={"start": 0.0, "end": 450.0, "min_sec": 70.0, "target_sec": 200.0, "max_sec": 300.0},
        transcript={"film": [{"start": 10.0, "end": 12.0, "text": "Oi"}], "mic": []},
        mic_speech=[],
        shot_cuts=[],
        candidates=[Candidate("C1", 150.0, 10.0), Candidate("C2", 300.0, 10.0)],
        clips=[store.Clip(1, 0.0, 150.0, "Comeco", 8, 5.6), store.Clip(2, 150.0, 450.0, "Velho", 5, 3.5)],
    )


class ResegmentTest(unittest.TestCase):
    def test_keeps_titles_of_unchanged_clips_and_titles_new_ones(self):
        client = FakeTitles()
        analysis = pipeline.resegment(analysis_with_old_clips(), Durations(70.0, 150.0, 240.0), client)
        self.assertEqual([(c.start, c.end) for c in analysis.clips], [(0.0, 150.0), (150.0, 300.0), (300.0, 450.0)])
        self.assertEqual([c.title for c in analysis.clips], ["Comeco", "Novo", "Novo"])
        self.assertEqual([c.hook for c in analysis.clips], [8, 6, 6])
        self.assertEqual([c.score for c in analysis.clips], [5.6, 4.2, 4.2])
        self.assertEqual(client.calls, 2)
        self.assertEqual(analysis.options["target_sec"], 150.0)

    def test_without_llm_new_clips_get_a_numbered_title(self):
        analysis = pipeline.resegment(analysis_with_old_clips(), Durations(70.0, 150.0, 240.0), None)
        self.assertEqual([c.title for c in analysis.clips], ["Comeco", "Clipe 02", "Clipe 03"])
        self.assertEqual([c.hook for c in analysis.clips], [8, None, None])
