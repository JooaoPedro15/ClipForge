import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import style_service


@dataclass
class FakeWord:
    word: str
    start: float
    end: float


@dataclass
class FakeSegment:
    start: float
    end: float
    text: str
    words: list


def segment(items: list[tuple[str, float, float]]) -> FakeSegment:
    words = [FakeWord(f" {text}", start, end) for text, start, end in items]
    return FakeSegment(words[0].start, words[-1].end, " ".join(text for text, _, _ in items), words)


# Video cru: silencio de 1s depois de "la" e de 0,5s depois de "gente".
ORIGINAL = [
    segment([("eu", 0.0, 0.2), ("fui", 0.25, 0.45), ("la", 0.5, 0.7), ("ontem", 1.7, 1.9), ("e", 1.95, 2.05), ("tava", 2.1, 2.4)]),
    segment([("cheio", 3.0, 3.2), ("de", 3.25, 3.35), ("gente", 3.4, 3.7), ("demais", 4.2, 4.4)]),
]
# Video final: o usuario cortou 0,8s do primeiro silencio e 0,3s do segundo.
FINAL = [
    segment([("eu", 0.0, 0.2), ("fui", 0.25, 0.45), ("la", 0.5, 0.7), ("ontem", 0.9, 1.1), ("e", 1.15, 1.25), ("tava", 1.3, 1.6)]),
    segment([("cheio", 2.2, 2.4), ("de", 2.45, 2.55), ("gente", 2.6, 2.9), ("demais", 3.1, 3.3)]),
]
CORRECTED_SRT = (
    "1\n00:00:00,000 --> 00:00:00,900\neu fui la\n\n"
    "2\n00:00:00,900 --> 00:00:01,800\nontem e tava\n\n"
    "3\n00:00:02,100 --> 00:00:03,000\ncheio de gente\n\n"
    "4\n00:00:03,000 --> 00:00:03,500\ndemais\n"
)


class FakeWhisperModel:
    transcribed: list[str] = []

    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, media_path, **kwargs):
        FakeWhisperModel.transcribed.append(Path(media_path).name)
        segments = FINAL if "final" in Path(media_path).name else ORIGINAL
        return segments, types.SimpleNamespace(language="pt", duration=segments[-1].end)


class StyleServiceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.original = self.tmp / "original.mp4"
        self.final = self.tmp / "final.mp4"
        self.srt = self.tmp / "corrigido.srt"
        self.store = self.tmp / "store"
        self.original.write_bytes(b"fake")
        self.final.write_bytes(b"fake")
        self.srt.write_text(CORRECTED_SRT, encoding="utf-8")
        FakeWhisperModel.transcribed = []
        patcher = mock.patch.object(style_service.subtitle_service, "WhisperModel", FakeWhisperModel)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def learn(self, srt: Path | None = None) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            return style_service.learn(
                str(self.original), str(srt or self.srt), str(self.final), str(self.store), "large-v3", "pt", 5, "cpu", "int8"
            )

    def library(self) -> dict:
        return json.loads((self.store / "library.json").read_text(encoding="utf-8"))

    def test_learn_saves_the_video_and_trains_the_profile(self):
        report = self.learn()

        self.assertEqual(report["profile"], "horizontal")
        self.assertIsNone(report["f1Before"])
        self.assertGreaterEqual(report["f1Formula"], 0.0)
        self.assertEqual(report["gapExamples"], 9)
        self.assertEqual(report["timingSamples"], 4)
        self.assertEqual(FakeWhisperModel.transcribed, ["original.mp4", "final.mp4"])
        self.assertTrue(self.original.with_suffix(".words.json").exists())
        self.assertEqual([video["name"] for video in self.library()["videos"]], ["original.mp4"])
        self.assertTrue((self.store / "profiles" / "horizontal" / "model.joblib").exists())

    def test_teaching_again_reuses_words_json_and_measures_the_current_profile(self):
        self.learn()
        FakeWhisperModel.transcribed = []

        report = self.learn()

        self.assertEqual(FakeWhisperModel.transcribed, ["final.mp4"])
        self.assertIsNotNone(report["f1Before"])
        self.assertEqual(len(self.library()["videos"]), 1)

    def test_srt_from_another_video_is_rejected_without_saving_anything(self):
        other = self.tmp / "outro.srt"
        other.write_text("1\n00:00:00,000 --> 00:00:01,000\nnada a ver com isso aqui\n", encoding="utf-8")

        with self.assertRaises(style_service.StyleError):
            self.learn(other)

        self.assertFalse((self.store / "library.json").exists())

    def test_forget_removes_the_video_and_the_now_empty_profile(self):
        report = self.learn()

        with contextlib.redirect_stdout(io.StringIO()):
            result = style_service.forget(report["videoId"], str(self.store))

        self.assertEqual(result, {"videoId": report["videoId"], "profile": "horizontal"})
        self.assertEqual(self.library()["videos"], [])
        self.assertFalse((self.store / "profiles" / "horizontal").exists())

    def test_main_reports_unknown_video_as_error_event(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = style_service.main(["forget", "--id", "nao-existe", "--store", str(self.store)])

        event = json.loads(output.getvalue().strip().splitlines()[-1])
        self.assertEqual(code, 1)
        self.assertEqual((event["event"], event["stage"]), ("error", "style"))

    def test_formula_groups_follow_the_current_segmentation(self):
        words = []
        for index, item in enumerate(ORIGINAL):
            words.extend(style_service.subtitle_service.whisper_word_dicts(item, index, len(words)))

        self.assertEqual(style_service.formula_groups(words, "horizontal"), [(0, 6), (6, 10)])
        self.assertEqual(sum(end - start for start, end in style_service.formula_groups(words, "vertical")), 10)


if __name__ == "__main__":
    unittest.main()
