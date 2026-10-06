import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import ffmpeg_utils


class EscapePathForSubtitlesFilterTest(unittest.TestCase):
    def test_converts_backslashes_and_escapes_colon(self):
        result = ffmpeg_utils.escape_path_for_subtitles_filter("C:\\Users\\joao\\video.en.srt")
        self.assertEqual(result, "C\\:/Users/joao/video.en.srt")

    def test_leaves_forward_slash_paths_mostly_untouched_besides_colon(self):
        result = ffmpeg_utils.escape_path_for_subtitles_filter("D:/videos/clip.srt")
        self.assertEqual(result, "D\\:/videos/clip.srt")


class EscapeForceStyleValueTest(unittest.TestCase):
    def test_leaves_safe_values_untouched(self):
        result = ffmpeg_utils.escape_force_style_value("FontSize=48,Bold=1,MarginV=90")
        self.assertEqual(result, "FontSize=48,Bold=1,MarginV=90")

    def test_escapes_single_quote_that_would_break_out_of_the_quoted_value(self):
        result = ffmpeg_utils.escape_force_style_value("FontName=Arial's Font")
        self.assertNotIn("'", result.replace("\\'", ""))

    def test_escapes_colon_that_would_be_read_as_filter_option_separator(self):
        result = ffmpeg_utils.escape_force_style_value("FontName=Time: New Roman")
        self.assertIn("\\:", result)


class AssertSafePathLengthTest(unittest.TestCase):
    def test_raises_for_long_path(self):
        long_path = "C:\\" + ("a" * 250) + "\\video.srt"
        with self.assertRaises(RuntimeError):
            ffmpeg_utils.assert_safe_path_length(long_path, label="srt")

    def test_does_not_raise_for_short_path(self):
        ffmpeg_utils.assert_safe_path_length("C:\\videos\\clip.srt", label="srt")


class EnsureShortSrtPathTest(unittest.TestCase):
    def test_returns_same_path_when_already_short(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            srt_path = Path(tmp_dir) / "clip.zh.srt"
            srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nola\n\n", encoding="utf-8")

            result = ffmpeg_utils.ensure_short_srt_path(str(srt_path))

            self.assertEqual(result, str(srt_path))

    def test_copies_to_short_temp_dir_when_path_too_long(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            long_dir = Path(tmp_dir) / ("a" * 220)
            long_dir.mkdir(parents=True)
            srt_path = long_dir / "clip.zh.srt"
            srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nola\n\n", encoding="utf-8")

            with mock.patch("ffmpeg_utils.resolve_short_temp_dir", return_value=Path(tmp_dir) / "short"):
                result = ffmpeg_utils.ensure_short_srt_path(str(srt_path))

            self.assertLess(len(result), len(str(srt_path)))
            self.assertTrue(Path(result).exists())
            self.assertEqual(Path(result).read_text(encoding="utf-8"), srt_path.read_text(encoding="utf-8"))


class ProbeVideoTest(unittest.TestCase):
    @mock.patch("ffmpeg_utils.resolve_ffprobe_path", return_value="ffprobe")
    @mock.patch("subprocess.run")
    def test_parses_duration_and_dimensions(self, mock_run, _mock_resolve):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ffprobe"],
            returncode=0,
            stdout='{"format": {"duration": "12.5"}, "streams": [{"width": 1920, "height": 1080}]}',
            stderr="",
        )

        info = ffmpeg_utils.probe_video("video.mp4")

        self.assertEqual(info.duration_sec, 12.5)
        self.assertEqual(info.width, 1920)
        self.assertEqual(info.height, 1080)

    @mock.patch("ffmpeg_utils.resolve_ffprobe_path", return_value="ffprobe")
    @mock.patch("subprocess.run")
    def test_raises_clear_error_when_ffprobe_fails(self, mock_run, _mock_resolve):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ffprobe"], returncode=1, stdout="", stderr="arquivo invalido"
        )

        with self.assertRaises(RuntimeError):
            ffmpeg_utils.probe_video("video.mp4")


class RunFfmpegWithProgressTest(unittest.TestCase):
    def test_calls_on_progress_and_completes_on_success(self):
        progress_values = []

        fake_stdout_lines = [
            "out_time_ms=5000000\n",
            "progress=continue\n",
            "out_time_ms=10000000\n",
            "progress=end\n",
        ]

        class FakeProcess:
            def __init__(self):
                self.stdout = iter(fake_stdout_lines)
                self.stderr = iter([])
                self.returncode = 0

            def wait(self):
                return self.returncode

        with mock.patch("subprocess.Popen", return_value=FakeProcess()):
            ffmpeg_utils.run_ffmpeg_with_progress(
                ["ffmpeg", "-i", "in.mp4", "out.mp4"],
                total_duration_sec=10.0,
                on_progress=progress_values.append,
            )

        self.assertEqual(progress_values, [50, 99, 100])

    def test_raises_on_nonzero_exit_code(self):
        class FakeProcess:
            def __init__(self):
                self.stdout = iter(["progress=end\n"])
                self.stderr = iter(["erro simulado\n"])
                self.returncode = 1

            def wait(self):
                return self.returncode

        with mock.patch("subprocess.Popen", return_value=FakeProcess()), self.assertRaises(RuntimeError):
            ffmpeg_utils.run_ffmpeg_with_progress(
                ["ffmpeg", "-i", "in.mp4", "out.mp4"],
                total_duration_sec=10.0,
                on_progress=lambda _p: None,
            )


if __name__ == "__main__":
    unittest.main()
