import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import events  # noqa: E402


class EmitTest(unittest.TestCase):
    def test_prints_one_json_line_with_extra_fields_and_accents(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            events.emit("status", "processing", "transcribing", "Transcrevendo áudio...", progress=42)

        line = buffer.getvalue()
        self.assertEqual(line.count("\n"), 1)
        self.assertTrue(line.endswith("\n"))
        self.assertIn("áudio", line)  # ensure_ascii=False: acento nao vira á
        self.assertEqual(
            json.loads(line),
            {
                "event": "status",
                "status": "processing",
                "stage": "transcribing",
                "message": "Transcrevendo áudio...",
                "progress": 42,
            },
        )


if __name__ == "__main__":
    unittest.main()
