import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import preedit_service
from cortes.media import SourceMedia
from llm_service import LLMUnavailableError
from premiere_project_test import FakeProject

FIXTURE = Path(__file__).parent / "preedit" / "fixtures" / "molde_preedit.xml"


def recording_words(count: int) -> list[dict]:
    """Frases de 4 s com 1 s de pausa; as pares tem a palavra 'top' (a IA falsa da nota 9)."""
    words = []
    for index in range(count):
        start = index * 5.0
        tag = "top" if index % 2 == 0 else "meh"
        words.append({"word": f" {tag}{index}", "start": start, "end": start + 1.9})
        words.append({"word": f" fim{index}.", "start": start + 2.0, "end": start + 4.0})
    return words


class FakeClient:
    model = "qwen-falso"

    def chat_json(self, system, user, temperature=0):
        notes = {}
        for line in user.splitlines():
            key = line.split("]")[0].lstrip("[")
            notes[key] = 9 if " top" in line else 2
        return {"notas": notes}


class PreeditServiceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.store = self.tmp / "store"
        self.recordings = []
        for number in range(3):
            recording = self.tmp / f"gravacao{number}.mp4"
            recording.write_bytes(b"fake")
            # Caches prontos: o teste nao precisa de ffmpeg nem de Whisper.
            (self.tmp / f"gravacao{number}.words.a0.json").write_text(json.dumps(recording_words(20)), encoding="utf-8")
            (self.tmp / f"gravacao{number}.loudness.a0.json").write_text(json.dumps({"window": 0.1, "db": [-30.0] * 1000}), encoding="utf-8")
            self.recordings.append(recording)

    def tearDown(self):
        self._tmp.cleanup()

    def project(self, extra_missing: bool = False) -> Path:
        project = FakeProject()
        for number, recording in enumerate(self.recordings):
            # O usuario manteve as frases pares (as "top"), com zoom na segunda delas.
            clips = []
            timeline = 0.0
            for phrase in range(0, 20, 2):
                start = phrase * 5.0
                scale = 160.0 if phrase == 2 else 100.0
                clips.append(project.media_clip(timeline, timeline + 4.2, str(recording), start, scale=scale))
                timeline += 4.2
            project.sequence(f"Sequência {number}", [clips])
        if extra_missing:
            missing = str(self.tmp / "nao-existe.mp4")
            project.sequence("Sumiu", [[project.media_clip(0.0, 5.0, missing, 0.0), project.media_clip(5.0, 8.0, missing, 20.0)]])
        return project.write(self.tmp / "projeto.prproj")

    def teach(self, project: Path) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            return preedit_service.teach_projects([str(project)], str(self.store), "large-v3", "pt", 5, "cpu", "int8", 0, FakeClient)

    def test_teach_learns_each_recording_once_and_skips_missing_files(self):
        report = self.teach(self.project(extra_missing=True))

        self.assertEqual(len(report["taught"]), 3)
        self.assertEqual(report["skipped"], [{"recording": str(self.tmp / "nao-existe.mp4"), "reason": "gravacao nao encontrada"}])
        self.assertIn("longo", report["models"])
        again = self.teach(self.project())
        self.assertEqual([item["reason"] for item in again["skipped"]], ["ja ensinada"] * 3)

    def test_edit_writes_the_xml_next_to_the_recording(self):
        self.teach(self.project())
        target = self.tmp / "nova.mp4"
        shutil.copy(self.recordings[0], target)
        for suffix in (".words.a0.json", ".loudness.a0.json"):
            shutil.copy(self.tmp / f"gravacao0{suffix}", self.tmp / f"nova{suffix}")
        source = SourceMedia(str(target), 100.0, 30.0, 1920, 1080, 1)

        with mock.patch.object(preedit_service, "probe_source", return_value=source), contextlib.redirect_stdout(io.StringIO()):
            report = preedit_service.edit_recording(str(target), str(FIXTURE), str(self.store), 0.8, None, "large-v3", "pt", 5, "cpu", "int8", 0, FakeClient)

        xml = Path(report["xmlPath"])
        self.assertEqual(xml.name, "nova.preedicao.longo.xml")
        self.assertTrue(xml.exists())
        self.assertLessEqual(report["durationSec"], 0.8 * 60 * 1.05)

    def test_edit_without_enough_teaching_is_a_clear_error(self):
        with self.assertRaises(preedit_service.PreeditError):
            preedit_service.edit_recording(str(self.recordings[0]), str(FIXTURE), str(self.store), 10, None, "large-v3", "pt", 5, "cpu", "int8", 0, FakeClient)

    def test_main_report_and_forget(self):
        self.teach(self.project())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = preedit_service.main(["report", "--store", str(self.store)])
        event = json.loads(output.getvalue().strip().splitlines()[-1])
        self.assertEqual(code, 0)
        self.assertEqual(len(event["report"]["sources"]), 3)

        source_id = event["report"]["sources"][0]["id"]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = preedit_service.main(["forget", "--id", source_id, "--store", str(self.store)])
        self.assertEqual((code, json.loads(output.getvalue().strip().splitlines()[-1])["report"]["format"]), (0, "longo"))

    def test_a_failing_recording_does_not_stop_the_others(self):
        real = preedit_service.prepare_audio

        def flaky(recording, *args):
            if recording.endswith("gravacao1.mp4"):
                raise RuntimeError("CUDA failed with error out of memory")
            return real(recording, *args)

        with mock.patch.object(preedit_service, "prepare_audio", side_effect=flaky):
            report = self.teach(self.project())

        self.assertEqual(len(report["taught"]), 2)
        (failure,) = report["failed"]
        self.assertTrue(failure["recording"].endswith("gravacao1.mp4"))
        self.assertIn("memoria", failure["error"])

    def test_every_transcription_runs_before_the_first_ai_score(self):
        calls = []
        real_audio, real_interest = preedit_service.prepare_audio, preedit_service.load_interest

        def audio(*args):
            calls.append("whisper")
            return real_audio(*args)

        def scores(*args):
            calls.append("ia")
            return real_interest(*args)

        with mock.patch.object(preedit_service, "prepare_audio", side_effect=audio), mock.patch.object(preedit_service, "load_interest", side_effect=scores):
            self.teach(self.project())

        self.assertEqual(calls, ["whisper"] * 3 + ["ia"] * 3)

    def test_recording_without_speech_on_the_track_fails_with_a_hint(self):
        (self.tmp / "gravacao2.words.a0.json").write_text("[]", encoding="utf-8")

        report = self.teach(self.project())

        self.assertEqual(len(report["taught"]), 2)
        (failure,) = report["failed"]
        self.assertIn("faixa 1", failure["error"])
        self.assertIn("--audio-track", failure["error"])

    def test_ignored_sources_show_up_in_the_report(self):
        project = FakeProject()
        main = [project.media_clip(0.0, 4.2, str(self.recordings[0]), 0.0), project.media_clip(4.2, 8.4, str(self.recordings[0]), 10.0)]
        broll = [project.media_clip(1.0, 2.0, str(self.tmp / "meme.mp4"), 0.0)]
        project.sequence("Sequência 1", [main, broll])

        report = self.teach(project.write(self.tmp / "broll.prproj"))

        self.assertIn({"recording": str(self.tmp / "meme.mp4"), "reason": "fora da trilha principal (b-roll)"}, report["skipped"])

    def test_recordings_taught_without_the_ai_are_taught_again(self):
        def offline():
            raise LLMUnavailableError("Ollama fora do ar")

        with contextlib.redirect_stdout(io.StringIO()):
            first = preedit_service.teach_projects([str(self.project())], str(self.store), "large-v3", "pt", 5, "cpu", "int8", 0, offline)
        second = self.teach(self.project())

        self.assertTrue(first["warnings"])
        self.assertEqual((len(second["taught"]), second["skipped"]), (3, []))
        self.assertEqual(self.teach(self.project())["skipped"][0]["reason"], "ja ensinada")

    def test_edit_changed_in_the_project_is_taught_again(self):
        self.teach(self.project())
        project = FakeProject()
        recording = str(self.recordings[0])
        project.sequence("Nova edicao", [[project.media_clip(0.0, 4.2, recording, 0.0), project.media_clip(4.2, 8.4, recording, 30.0)]])

        report = self.teach(project.write(self.tmp / "novo.prproj"))

        self.assertEqual([item["recording"] for item in report["taught"]], [recording])

    def test_project_without_recording_clips(self):
        project = FakeProject()
        project.sequence("So legenda", [[project.graphic(0.0, 1.0, "oi")]])
        with self.assertRaises(preedit_service.PreeditError):
            self.teach(project.write(self.tmp / "vazio.prproj"))


if __name__ == "__main__":
    unittest.main()
