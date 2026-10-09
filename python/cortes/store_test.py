import json
import tempfile
import unittest
from pathlib import Path

from cortes.candidates import Candidate
from cortes.store import Analysis, Clip, analysis_path, load, save, select_clips

CLIPS = [Clip(1, 0.0, 150.0, "A", 8, 7.1), Clip(2, 150.0, 300.0, "B", 4, 2.8), Clip(3, 300.0, 450.0, "C", 9, 9.5)]


def sample() -> Analysis:
    return Analysis(
        source={"path": "E:\\b.mp4", "duration_sec": 600.0, "fps": 60.0, "width": 3840, "height": 1080, "audio_streams": 4},
        options={"start": 0.0, "end": 450.0},
        transcript={"film": [{"start": 1.0, "end": 2.0, "text": "Oi"}], "mic": []},
        mic_speech=[[10.0, 12.0]],
        shot_cuts=[14.6],
        candidates=[Candidate("C1", 150.0, 10.0, 8.0)],
        clips=list(CLIPS),
        warnings=["aviso"],
        timings={"extract": 12.5},
    )


class SaveLoadTest(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = save(sample(), Path(folder) / "b.cortes.json")
            self.assertEqual(load(path), sample())

    def test_rejects_other_version(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "b.cortes.json"
            path.write_text(json.dumps({"version": 99}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "versao"):
                load(path)

    def test_analysis_lives_next_to_the_source(self):
        self.assertEqual(analysis_path("E:/Bruto/react.mp4"), Path("E:/Bruto/react.cortes.json"))


class SelectClipsTest(unittest.TestCase):
    def test_all_by_default(self):
        self.assertEqual(select_clips(CLIPS), CLIPS)

    def test_by_numbers(self):
        self.assertEqual([c.n for c in select_clips(CLIPS, numbers="3,1")], [1, 3])

    def test_unknown_number_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "9"):
            select_clips(CLIPS, numbers="1,9")

    def test_top_keeps_timeline_order(self):
        self.assertEqual([c.n for c in select_clips(CLIPS, top=2)], [1, 3])

    def test_top_with_clips_without_score(self):
        unscored = [Clip(1, 0.0, 1.0), Clip(2, 1.0, 2.0, score=3.0)]
        self.assertEqual([c.n for c in select_clips(unscored, top=1)], [2])

    def test_top_must_be_positive(self):
        with self.assertRaises(ValueError):
            select_clips(CLIPS, top=0)
