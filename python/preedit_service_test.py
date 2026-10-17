import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import preedit_service
from cortes.media import SourceMedia
from llm_service import LLMUnavailableError
from premiere_project_test import FakeProject, export_settings

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

    def test_edit_without_molde_uses_the_recording_layout(self):
        self.teach(self.project())
        target = self.tmp / "nova.mp4"
        shutil.copy(self.recordings[0], target)
        for suffix in (".words.a0.json", ".loudness.a0.json"):
            shutil.copy(self.tmp / f"gravacao0{suffix}", self.tmp / f"nova{suffix}")
        source = SourceMedia(str(target), 100.0, 60.0, 2560, 1440, 4)

        with mock.patch.object(preedit_service, "probe_source", return_value=source), contextlib.redirect_stdout(io.StringIO()):
            report = preedit_service.edit_recording(str(target), None, str(self.store), 0.8, None, "large-v3", "pt", 5, "cpu", "int8", 0, FakeClient)

        root = ET.parse(report["xmlPath"]).getroot()
        self.assertEqual(root.findtext("sequence/media/video/format/samplecharacteristics/width"), "2560")
        self.assertEqual(len(root.findall("sequence/media/audio/track")), 4)
        self.assertTrue(any("molde" in warning for warning in report["warnings"]))

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


class ProjectPathsTest(unittest.TestCase):
    def test_projects_dir_adds_every_project_of_the_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name in ("b.prproj", "a.prproj", "notas.txt"):
                (folder / name).write_bytes(b"x")
            extra = str(folder / "outra" / "c.prproj")

            self.assertEqual(preedit_service.project_paths([extra], tmp), [extra, str(folder / "a.prproj"), str(folder / "b.prproj")])
            # O mesmo projeto pela lista e pela pasta entra uma vez so.
            self.assertEqual(preedit_service.project_paths([str(folder / "A.prproj")], tmp), [str(folder / "A.prproj"), str(folder / "b.prproj")])

    def test_teach_without_projects_is_a_clear_error(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = preedit_service.main(["teach-final", "--videos", "X", "--store", "Y"])

        event = json.loads(output.getvalue().strip().splitlines()[-1])
        self.assertEqual(code, 1)
        self.assertIn("pelo menos um projeto", event["message"])


class TeachFinalsTest(unittest.TestCase):
    """Videos finais com caches prontos; a duracao vem de um probe falso."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.store = self.tmp / "store"
        self.videos = self.tmp / "Finais"
        self.videos.mkdir()
        self.durations = {}
        for number in range(4):
            video = self.videos / f"pronto{number}.mp4"
            video.write_bytes(b"fake")
            (self.videos / f"pronto{number}.words.a0.json").write_text(json.dumps(recording_words(20)), encoding="utf-8")
            (self.videos / f"pronto{number}.loudness.a0.json").write_text(json.dumps({"window": 0.1, "db": [-30.0] * 1000}), encoding="utf-8")
            self.durations[str(video)] = 100.0 + number * 10

    def tearDown(self):
        self._tmp.cleanup()

    def project(self, zoom_scale: float = 160.0, name: str = "projeto.prproj") -> Path:
        project = FakeProject()
        for number in range(4):
            duration = 100.0 + number * 10
            bruto = str(self.tmp / f"sumiu{number}.mp4")  # bruto offline: so o caminho
            clips = [
                project.media_clip(0.0, 10.0, bruto, 0.0),
                project.media_clip(10.0, 12.0, bruto, 50.0, scale=zoom_scale),
                project.media_clip(12.0, duration, bruto, 52.0),
            ]
            exported = Path(r"C:\Users\Joao\Desktop") / f"pronto{number}.mp4"
            project.sequence(f"Longo {number}", [clips], export=export_settings(exported, 0.0, duration))
        return project.write(self.tmp / name)

    def teach(self, project: Path) -> dict:
        def probe(path):
            return SourceMedia(path, self.durations[path], 30.0, 1920, 1080, 1)

        with mock.patch.object(preedit_service, "probe_source", side_effect=probe), contextlib.redirect_stdout(io.StringIO()):
            return preedit_service.teach_finals([str(project)], str(self.videos), str(self.store), "large-v3", "pt", 5, "cpu", "int8", 0, FakeClient)

    def test_pairs_by_export_and_teaches_only_zoom(self):
        report = self.teach(self.project())

        self.assertEqual(len(report["pairs"]), 4)
        self.assertEqual((len(report["taught"]), report["skipped"], report["failed"]), (4, [], []))
        library = json.loads((self.store / "library.json").read_text(encoding="utf-8"))
        self.assertEqual({source["kind"] for source in library["sources"]}, {"final"})
        self.assertEqual(report["taught"][0]["phrases"], 0)
        # So videos finais: o editor nao treina (precisa de bruto), mas o zoom deles e medido.
        self.assertIn("zoom_f1_finais", report["models"]["longo"])
        self.assertIn("bruto", report["models"]["longo"]["aviso"])

    def test_already_taught_videos_are_skipped(self):
        self.teach(self.project())

        again = self.teach(self.project())

        self.assertEqual([item["reason"] for item in again["skipped"]], ["ja ensinada"] * 4)

    def test_changed_zooms_teach_the_video_again(self):
        self.teach(self.project())

        report = self.teach(self.project(zoom_scale=200.0, name="autosave.prproj"))

        self.assertEqual(len(report["taught"]), 4)

    def test_sequence_without_zoom_is_skipped_with_the_reason(self):
        report = self.teach(self.project(zoom_scale=100.0))

        self.assertEqual(report["taught"], [])
        self.assertEqual({item["reason"] for item in report["skipped"]}, {f"sem zoom (Longo {n})" for n in range(4)})

    def test_video_whose_recording_exists_or_was_taught_is_left_to_teach_project(self):
        # Sem isso a mesma edicao entraria duas vezes (pelo bruto e pelo video final).
        (self.tmp / "sumiu0.mp4").write_bytes(b"bruto ainda no disco")
        taught_raw = {"id": "bruto1", "kind": "projeto", "format": "longo", "recording": str(self.tmp / "sumiu1.mp4")}
        preedit_service.store.save_source(self.store, taught_raw, {"phrase": [], "zoom": []})

        report = self.teach(self.project())

        self.assertEqual(len(report["taught"]), 2)
        reasons = {item["recording"]: item["reason"] for item in report["skipped"]}
        self.assertEqual(reasons[str(self.videos / "pronto0.mp4")], "bruto disponivel (sumiu0.mp4): ensine com teach-project")
        self.assertEqual(reasons[str(self.videos / "pronto1.mp4")], "bruto disponivel (sumiu1.mp4): ensine com teach-project")

    def test_folder_without_videos_is_a_clear_error(self):
        with self.assertRaises(preedit_service.PreeditError):
            preedit_service.teach_finals([str(self.project())], str(self.tmp / "nao-existe"), str(self.store), "large-v3", "pt", 5, "cpu", "int8", 0, FakeClient)

    def test_one_broken_project_among_many_is_reported_and_the_others_are_taught(self):
        # Achado da validacao real: um Auto-Save truncado (desenho_1.prproj) derrubava o lote de 438 projetos.
        broken = self.tmp / "truncado.prproj"
        broken.write_bytes(b"isso nao e um projeto")

        def probe(path):
            return SourceMedia(path, self.durations[path], 30.0, 1920, 1080, 1)

        with mock.patch.object(preedit_service, "probe_source", side_effect=probe), contextlib.redirect_stdout(io.StringIO()):
            report = preedit_service.teach_finals(
                [str(broken), str(self.project())], str(self.videos), str(self.store), "large-v3", "pt", 5, "cpu", "int8", 0, FakeClient
            )

        self.assertEqual(len(report["taught"]), 4)
        (failure,) = report["failed"]
        self.assertEqual(failure["recording"], str(broken))

    def test_bad_project_is_a_clear_error(self):
        broken = self.tmp / "quebrado.prproj"
        broken.write_bytes(b"isso nao e um projeto")

        with self.assertRaises(preedit_service.PreeditError):
            self.teach(broken)


if __name__ == "__main__":
    unittest.main()
