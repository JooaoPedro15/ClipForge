import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import cortes_service
from cortes import store
from cortes.candidates import Candidate
from cortes.media import SourceMedia

FIXTURE = Path(__file__).parent / "cortes" / "fixtures" / "molde_exemplo.xml"
SOURCE = SourceMedia("E:\\Bruto\\react.mp4", 7298.0, 60.0, 3840, 1080, 4)


def run_cli(argv: list[str]) -> tuple[int, list[dict]]:
    stdout = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
        code = cortes_service.main(argv)
    events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.startswith("{")]
    return code, events


class XmlCommandTest(unittest.TestCase):
    def test_writes_xml_from_manual_ranges(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(cortes_service, "probe_source", return_value=SOURCE):
            out = Path(folder) / "teste.xml"
            code, events = run_cli(
                ["xml", "--template", str(FIXTURE), "--source", SOURCE.path, "--ranges", "2:24.44-3:39.72,3:39.72-5:28.56", "--out", str(out)]
            )
            self.assertEqual(code, 0)
            self.assertTrue(out.exists())
            self.assertEqual(events[-1]["event"], "done")
            self.assertEqual(events[-1]["clips"], 2)

    def test_missing_ranges_is_an_error_event(self):
        code, events = run_cli(["xml", "--template", str(FIXTURE), "--source", SOURCE.path])
        self.assertEqual(code, 1)
        self.assertEqual(events[-1]["event"], "error")
        self.assertIn("--ranges", events[-1]["error"])

    def test_bad_template_is_an_error_event(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "molde.xml"
            bad.write_text("<projeto/>", encoding="utf-8")
            code, events = run_cli(["xml", "--template", str(bad), "--source", SOURCE.path, "--ranges", "0-10"])
        self.assertEqual(code, 1)
        self.assertIn("xmeml", events[-1]["error"])


class XmlFromAnalysisTest(unittest.TestCase):
    def write_analysis(self, folder: Path) -> Path:
        analysis = store.Analysis(
            source={"path": SOURCE.path, "duration_sec": 7298.0, "fps": 60.0, "width": 3840, "height": 1080, "audio_streams": 4},
            options={"start": 0.0, "end": 450.0},
            transcript={"film": [], "mic": []},
            mic_speech=[],
            shot_cuts=[],
            candidates=[Candidate("C1", 150.0, 10.0)],
            clips=[
                store.Clip(1, 0.0, 150.0, "A", 8, 7.1),
                store.Clip(2, 150.0, 300.0, "B", 4, 2.8),
                store.Clip(3, 300.0, 450.0, "C", 9, 9.5),
            ],
        )
        return store.save(analysis, folder / "react.cortes.json")

    def test_writes_selected_clips_next_to_the_analysis(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write_analysis(Path(folder))
            code, events = run_cli(["xml", "--template", str(FIXTURE), "--analysis", str(path), "--top", "2"])
            self.assertEqual(code, 0)
            self.assertEqual(events[-1]["clips"], 2)
            self.assertEqual(Path(events[-1]["outputPath"]), Path(folder) / "react.cortes.xml")

    def test_neither_analysis_nor_ranges_is_an_error(self):
        code, events = run_cli(["xml", "--template", str(FIXTURE)])
        self.assertEqual(code, 1)
        self.assertIn("--analysis", events[-1]["error"])


    def test_evaluate_prints_the_report(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write_analysis(Path(folder))
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = cortes_service.main(["evaluate", "--reference", str(FIXTURE), "--analysis", str(path)])
            self.assertEqual(code, 0)
            self.assertIn("Gabarito: 1 fronteiras", stdout.getvalue())

    def test_resegment_rewrites_the_analysis_with_new_durations(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write_analysis(Path(folder))
            code, events = run_cli(["resegment", str(path), "--min", "70", "--target", "150", "--max", "240"])
            self.assertEqual(code, 0)
            self.assertEqual(events[-1]["event"], "done")
            self.assertEqual(store.load(path).options["target_sec"], 150.0)

class AnalyzeArgsTest(unittest.TestCase):
    def test_tracks_are_one_based_on_the_cli(self):
        args = cortes_service.parse_args(["analyze", "E:\\b.mp4", "--film-track", "2", "--mic-track", "1", "--start", "2:24.44"])
        options = cortes_service.analyze_options(args)
        self.assertEqual((options.film_track, options.mic_track, options.start, options.end), (1, 0, 144.44, None))
        self.assertIsNone(options.judge_model)

    def test_titles_are_independent_from_the_judge(self):
        args = cortes_service.parse_args(["analyze", "E:\\b.mp4", "--titles", "qwen2.5:7b-instruct"])
        options = cortes_service.analyze_options(args)
        self.assertEqual((options.judge_model, options.title_model), (None, "qwen2.5:7b-instruct"))
        default = cortes_service.analyze_options(cortes_service.parse_args(["analyze", "E:\\b.mp4"]))
        self.assertIsNone(default.title_model)

    def test_resegment_takes_the_titles_model(self):
        args = cortes_service.parse_args(["resegment", "E:\\b.cortes.json", "--titles", "none"])
        self.assertEqual(args.titles, "none")
