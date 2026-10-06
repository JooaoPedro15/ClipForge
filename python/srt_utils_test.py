import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import srt_utils  # noqa: E402


class SrtRoundTripTest(unittest.TestCase):
    def test_write_then_parse_preserves_entries(self):
        entries = [
            ("00:00:00,000", "00:00:01,500", "ola mundo"),
            ("00:00:01,500", "00:00:03,000", "linha um\nlinha dois"),
        ]

        with self._temp_srt_path() as path:
            srt_utils.write_srt(entries, path)
            parsed = srt_utils.parse_srt(path)

        self.assertEqual(parsed, entries)

    def test_parse_srt_from_disk_matches_manual_content(self):
        content = (
            "1\n00:00:00,000 --> 00:00:01,000\nprimeira legenda\n\n"
            "2\n00:00:01,000 --> 00:00:02,500\nsegunda legenda\n\n"
        )

        with self._temp_srt_path() as path:
            Path(path).write_text(content, encoding="utf-8")
            parsed = srt_utils.parse_srt(path)

        self.assertEqual(
            parsed,
            [
                ("00:00:00,000", "00:00:01,000", "primeira legenda"),
                ("00:00:01,000", "00:00:02,500", "segunda legenda"),
            ],
        )

    def _temp_srt_path(self):
        import tempfile

        class _Ctx:
            def __enter__(self_inner):
                self_inner.dir = tempfile.TemporaryDirectory()
                return str(Path(self_inner.dir.name) / "test.srt")

            def __exit__(self_inner, *exc):
                self_inner.dir.cleanup()

        return _Ctx()


class RenderSrtTest(unittest.TestCase):
    def test_renders_cards_with_cleaning_case_and_line_wrap(self):
        cards = [
            {"start": 0.0, "end": 1.5, "text": "  Então   ela falou  "},
            {"start": 9.1, "end": 10.0, "text": "que a casa tava pegando fogo de verdade mano"},
        ]

        srt = srt_utils.render_srt(cards, max_line_width=42, uppercase=True, no_accents=True)

        self.assertEqual(
            srt,
            "1\n00:00:00,000 --> 00:00:01,500\nENTAO ELA FALOU\n\n"
            "2\n00:00:09,100 --> 00:00:10,000\nQUE A CASA TAVA PEGANDO FOGO DE VERDADE\nMANO\n",
        )

    def test_lowercase_and_no_punctuation(self):
        srt = srt_utils.render_srt(
            [{"start": 0.0, "end": 1.0, "text": "Valeu, Galera!"}],
            max_line_width=42,
            lowercase=True,
            no_punctuation=True,
        )

        self.assertEqual(srt, "1\n00:00:00,000 --> 00:00:01,000\nvaleu galera\n")

    def test_no_cards_renders_empty_string(self):
        self.assertEqual(srt_utils.render_srt([], max_line_width=42), "")


if __name__ == "__main__":
    unittest.main()
