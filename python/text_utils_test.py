import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import text_utils


class CleanTextTest(unittest.TestCase):
    def test_collapses_spaces_and_applies_flags(self):
        self.assertEqual(text_utils.clean_text("  Então,   né?  "), "Então, né?")
        self.assertEqual(text_utils.clean_text("Então, né?", no_accents=True), "Entao, ne?")
        self.assertEqual(text_utils.clean_text("Então, né?", no_punctuation=True), "Então né")


class NormalizeTokenTest(unittest.TestCase):
    def test_removes_accents_punctuation_and_case(self):
        self.assertEqual(text_utils.normalize_token(" Né?"), "ne")
        self.assertEqual(text_utils.normalize_token("..."), "")


class SplitTextIntoLinesTest(unittest.TestCase):
    def test_breaks_before_exceeding_width(self):
        self.assertEqual(text_utils.split_text_into_lines("a b c", 3), "a b\nc")
        self.assertEqual(text_utils.split_text_into_lines("curto", 42), "curto")


class FormatTimestampTest(unittest.TestCase):
    def test_formats_hours_minutes_seconds_and_millis(self):
        self.assertEqual(text_utils.format_timestamp(3661.5), "01:01:01,500")
        self.assertEqual(text_utils.format_timestamp(0.0), "00:00:00,000")

    def test_rounds_float_noise_instead_of_truncating(self):
        self.assertEqual(text_utils.format_timestamp(9.1), "00:00:09,100")
        self.assertEqual(text_utils.format_timestamp(16.2), "00:00:16,200")
        self.assertEqual(text_utils.format_timestamp(2.05), "00:00:02,050")
        self.assertEqual(text_utils.format_timestamp(59.9996), "00:01:00,000")
        self.assertEqual(text_utils.format_timestamp(-0.2), "00:00:00,000")


class WeakWordsTest(unittest.TestCase):
    def test_contains_connectives_that_should_not_close_a_subtitle(self):
        self.assertIn("que", text_utils.WEAK_TRAILING_WORDS)
        self.assertIn("pra", text_utils.WEAK_TRAILING_WORDS)


if __name__ == "__main__":
    unittest.main()
