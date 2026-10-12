import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import premiere_project
import style_service
from premiere_project_test import FakeProject, export_settings


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
# Fala que nao tem nada a ver com nenhuma legenda do projeto.
STRANGER = [segment([("bola", 0.0, 0.3), ("azul", 0.4, 0.7), ("grande", 0.8, 1.1), ("voando", 1.2, 1.6)])]
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
        name = Path(media_path).name
        segments = STRANGER if "estranho" in name else FINAL if "final" in name else ORIGINAL
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
        self.assertEqual(report["cutShare"], 0.0)
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

    def premiere_project(self) -> Path:
        # Mesmas legendas do CORRECTED_SRT, mas como graficos de texto numa sequencia do Premiere.
        project = FakeProject()
        cards = style_service.style_alignment.parse_srt_text(CORRECTED_SRT)
        project.sequence("Sequência 9", [[project.graphic(0.0, 0.5, "outra")]])
        project.sequence("Sequência 10", [[project.graphic(card.start, card.end, card.text) for card in cards]])
        return project.write(self.tmp / "projeto.prproj")

    def test_learn_reads_the_corrections_from_a_premiere_project(self):
        project = self.premiere_project()

        with contextlib.redirect_stdout(io.StringIO()):
            report = style_service.learn(
                str(self.original), str(project), str(self.final), str(self.store), "large-v3", "pt", 5, "cpu", "int8", "Sequência 10"
            )

        self.assertEqual((report["gapExamples"], report["timingSamples"]), (9, 4))

    def test_project_needs_a_known_sequence(self):
        project = self.premiere_project()

        with self.assertRaises(style_service.StyleError):
            self.learn(project)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(style_service.StyleError):
            style_service.learn(str(self.original), str(project), str(self.final), str(self.store), "large-v3", "pt", 5, "cpu", "int8", "Sequência 99")

    def test_scan_project_lists_sequences_newest_first(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = style_service.main(["scan-project", "--project", str(self.premiere_project())])

        event = json.loads(output.getvalue().strip().splitlines()[-1])
        self.assertEqual(code, 0)
        self.assertEqual([(item["name"], item["cards"]) for item in event["report"]["sequences"]], [("Sequência 10", 4), ("Sequência 9", 1)])
        self.assertEqual(event["report"]["rawFiles"], 0)

    def shifted(self, offset: float) -> list:
        cards = style_service.style_alignment.parse_srt_text(CORRECTED_SRT)
        return [(card.start + offset, card.end + offset, card.text) for card in cards]

    def learn_project(self, project: Path, originals: list[Path], finals: list[Path] = ()) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            return style_service.learn_project(
                str(project), [str(path) for path in originals], [str(path) for path in finals], str(self.store), "large-v3", "pt", 5, "cpu", "int8"
            )

    def test_each_raw_file_finds_its_short_inside_a_sequence_with_several_shorts(self):
        bruto = self.tmp / "Sequência 28 3.mp3"
        stranger = self.tmp / "estranho.mp3"
        for path in (bruto, stranger):
            path.write_bytes(b"fake")
        project = FakeProject()
        # Mesma sequencia: o Short em 20s, outro Short em 40s e uma copia do primeiro em 60s (a exportada).
        clips = [project.graphic(start, end, text) for start, end, text in self.shifted(20.0)]
        clips += [project.graphic(40.0, 41.0, "outra coisa"), project.graphic(41.0, 42.0, "bem diferente aqui")]
        clips += [project.graphic(start, end, text) for start, end, text in self.shifted(60.0)]
        project.sequence("Sequência 28", [clips], export=export_settings(self.final, 60.0, 64.0))
        path = project.write(self.tmp / "projeto.prproj")

        report = self.learn_project(path, [bruto, stranger])

        taught = [(item["name"], item["sequence"], item["gapExamples"], item["timingSamples"]) for item in report["taught"]]
        self.assertEqual(taught, [("Sequência 28 3", "Sequência 28", 9, 4)])
        self.assertEqual(report["skipped"], [{"name": "estranho", "reason": "legenda nao encontrada no projeto"}])
        self.assertEqual(self.learn_project(path, [bruto])["skipped"], [{"name": "Sequência 28 3", "reason": "ja ensinado"}])

    def test_shorts_exported_in_the_same_video_transcribe_it_once(self):
        brutos = [self.tmp / "Sequência 60.mp3", self.tmp / "Sequência 60 2.mp3"]
        for path in brutos:
            path.write_bytes(b"fake")
        project = FakeProject()
        clips = [project.graphic(start, end, text) for start, end, text in self.shifted(0.0)]
        clips += [project.graphic(start, end, text) for start, end, text in self.shifted(10.0)]
        project.sequence("Sequência 60", [clips], export=export_settings(self.final, 0.0, 14.0))
        path = project.write(self.tmp / "projeto.prproj")
        FakeWhisperModel.transcribed = []

        report = self.learn_project(path, brutos)

        self.assertEqual(len(report["taught"]), 2)
        self.assertEqual(FakeWhisperModel.transcribed.count("final.mp4"), 1)

    def test_candidate_finals_are_tried_closest_in_date_first(self):
        bruto, near, far = self.tmp / "b.mp3", self.tmp / "perto.mp4", self.tmp / "longe.mp4"
        for path, stamp in ((bruto, 1_000_000), (near, 1_000_600), (far, 5_000_000)):
            path.write_bytes(b"fake")
            os.utime(path, (stamp, stamp))

        self.assertEqual(style_service.order_by_date([far, near], [bruto]), [near, far])

    def test_raw_file_that_became_two_shorts_teaches_the_bigger_one(self):
        # Bruto longo: a fala do ORIGINAL + um trecho que virou outro Short (outra sequencia).
        words = [{"word": f" {text}", "start": index * 0.4, "end": index * 0.4 + 0.3} for index, text in enumerate(
            ("eu fui la ontem e tava cheio de gente demais " * 3 + "bola azul grande voando " * 12).split()
        )]
        project = FakeProject()
        project.sequence("Sequência 1", [[project.graphic(index * 2.0, index * 2.0 + 1.5, "eu fui la ontem e tava cheio de gente demais") for index in range(3)]])
        project.sequence("Sequência 2", [[project.graphic(0.0, 1.0, "bola azul grande voando bola azul")]])
        sequences = premiere_project.read_sequences(project.write(self.tmp / "projeto.prproj"))

        window = style_service.locate_short("robo", words, sequences)

        self.assertIsNotNone(window)
        self.assertEqual((window.sequence.name, window.start, window.end), ("Sequência 1", 0, 3))
        self.assertLess(window.score, style_service.style_alignment.MIN_MATCH_RATIO)

    def test_final_videos_with_any_name_are_matched_by_what_is_said_in_them(self):
        bruto = self.tmp / "Sequência 40.mp3"
        bruto.write_bytes(b"fake")
        # O FakeWhisperModel devolve a fala do video final pra todo arquivo com "final" no nome.
        renamed = self.tmp / "o final que eu renomeei.mp4"
        extra = self.tmp / "outro final qualquer.mp4"
        for path in (renamed, extra):
            path.write_bytes(b"fake")
        project = FakeProject()
        project.sequence("Sequência 40", [[project.graphic(start, end, text) for start, end, text in self.shifted(100.0)]])
        path = project.write(self.tmp / "projeto.prproj")

        self.assertEqual(self.learn_project(path, [bruto])["skipped"], [{"name": "Sequência 40", "reason": "video final nao encontrado"}])
        report = self.learn_project(path, [bruto], [renamed, extra])

        (item,) = report["taught"]
        # Sem saber de onde o video saiu, aprende quebras mas nao entrada/saida.
        self.assertEqual((item["gapExamples"], item["timingSamples"]), (9, 0))
        self.assertTrue(any("Entrada e saida" in warning for warning in item["warnings"]))

    def test_without_chosen_raw_files_uses_the_ones_next_to_the_imported_srt(self):
        (self.tmp / "Sequência 50.mp3").write_bytes(b"fake")
        project = FakeProject()
        project.imported_file(self.tmp / "Sequência 50.srt")
        project.sequence("Sequência 50", [[project.graphic(start, end, text) for start, end, text in self.shifted(0.0)]], export=export_settings(self.final, 0.0, 10.0))
        path = project.write(self.tmp / "projeto.prproj")

        self.assertEqual([item["name"] for item in self.learn_project(path, [])["taught"]], ["Sequência 50"])

    def test_formula_groups_follow_the_current_segmentation(self):
        words = []
        for index, item in enumerate(ORIGINAL):
            words.extend(style_service.subtitle_service.whisper_word_dicts(item, index, len(words)))

        self.assertEqual(style_service.formula_groups(words, "horizontal"), [(0, 6), (6, 10)])
        self.assertEqual(sum(end - start for start, end in style_service.formula_groups(words, "vertical")), 10)


if __name__ == "__main__":
    unittest.main()
