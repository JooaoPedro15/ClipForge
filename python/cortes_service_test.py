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
