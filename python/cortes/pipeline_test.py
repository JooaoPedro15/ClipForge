import itertools
import unittest
from unittest import mock

from cortes import pipeline
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
