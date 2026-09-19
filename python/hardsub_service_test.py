import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import hardsub_service  # noqa: E402


FAKE_VIDEO_INFO = types.SimpleNamespace(duration_sec=10.0, width=1920, height=1080)


class ResolveModeLangsTest(unittest.TestCase):
    def test_zh_mode_is_single_language(self):
        self.assertEqual(hardsub_service.resolve_mode_langs("zh"), ["zh"])

    def test_zh_en_mode_stacks_zh_on_top(self):
        self.assertEqual(hardsub_service.resolve_mode_langs("zh-en"), ["zh", "en"])

    def test_zh_original_mode_stacks_zh_on_top(self):
        self.assertEqual(hardsub_service.resolve_mode_langs("zh-original"), ["zh", "original"])

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            hardsub_service.resolve_mode_langs("xx")


class EnsureSrtForLangTest(unittest.TestCase):
    def test_original_lang_returns_original_path_unchanged(self):
        result = hardsub_service.ensure_srt_for_lang(
            lang="original",
            original_srt_path="C:/videos/clip.srt",
            source_language="pt",
            translator=None,
        )

        self.assertEqual(result, "C:/videos/clip.srt")

    def test_existing_translated_srt_is_reused_without_translating(self):
        with mock.patch("hardsub_service.Path") as mock_path_cls:
            mock_path_cls.return_value.exists.return_value = True
            mock_path_cls.return_value.with_suffix.return_value = "C:/videos/clip.zh.srt"

            translator = mock.Mock()
            result = hardsub_service.ensure_srt_for_lang(
                lang="zh",
                original_srt_path="C:/videos/clip.srt",
                source_language="pt",
                translator=translator,
            )

            translator.translate_segments.assert_not_called()
            self.assertEqual(result, "C:/videos/clip.zh.srt")

    def test_missing_translated_srt_is_generated_on_demand(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            original_path = Path(tmp_dir) / "clip.srt"
            original_path.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nola mundo\n\n",
                encoding="utf-8",
            )

            translator = mock.Mock()
            translator.translate_segments.return_value = ["hello world"]

            result = hardsub_service.ensure_srt_for_lang(
                lang="en",
                original_srt_path=str(original_path),
                source_language="pt",
                translator=translator,
            )

            expected_path = Path(tmp_dir) / "clip.en.srt"
            self.assertEqual(result, str(expected_path))
            self.assertTrue(expected_path.exists())
            self.assertIn("hello world", expected_path.read_text(encoding="utf-8"))
            translator.translate_segments.assert_called_once_with(
                ["ola mundo"], source_lang="pt", target_lang="en"
            )


class ResolveFormatProfileTest(unittest.TestCase):
    def test_portrait_video_resolves_to_shorts(self):
        self.assertEqual(hardsub_service.resolve_format_profile(video_width=1080, video_height=1920), "shorts")

    def test_landscape_video_resolves_to_long(self):
        self.assertEqual(hardsub_service.resolve_format_profile(video_width=1920, video_height=1080), "long")

    def test_square_video_resolves_to_long(self):
        self.assertEqual(hardsub_service.resolve_format_profile(video_width=1080, video_height=1080), "long")


class ResolveLayerStyleTest(unittest.TestCase):
    def test_shorts_single_layer_uses_base_font_and_margin_minus_fixed_nudge(self):
        fontsize, margin_v = hardsub_service.resolve_layer_style("shorts", video_height=1920, is_top=False)

        self.assertEqual(fontsize, round(1920 * hardsub_service.FONT_SCALE["shorts"]))
        expected_margin = round(1920 * hardsub_service.BASE_MARGIN_SCALE["shorts"]) - hardsub_service.SHORTS_MARGIN_NUDGE_PX
        self.assertEqual(margin_v, expected_margin)

    def test_long_layer_is_not_affected_by_shorts_nudge(self):
        _, margin_v = hardsub_service.resolve_layer_style("long", video_height=1080, is_top=False)

        self.assertEqual(margin_v, round(1080 * hardsub_service.BASE_MARGIN_SCALE["long"]))

    def test_top_layer_gets_extra_margin_to_clear_bottom_layer(self):
        _, bottom_margin = hardsub_service.resolve_layer_style("long", video_height=1080, is_top=False)
        _, top_margin = hardsub_service.resolve_layer_style("long", video_height=1080, is_top=True)

        self.assertGreater(top_margin, bottom_margin)


class SrtTimestampToAssTest(unittest.TestCase):
    def test_converts_milliseconds_to_centiseconds(self):
        self.assertEqual(hardsub_service._srt_timestamp_to_ass("00:01:23,456"), "0:01:23.45")

    def test_keeps_multi_digit_hours(self):
        self.assertEqual(hardsub_service._srt_timestamp_to_ass("01:00:00,000"), "1:00:00.00")


class BuildAssContentTest(unittest.TestCase):
    def test_play_res_matches_real_video_dimensions(self):
        content = hardsub_service.build_ass_content(
            entries=[("00:00:00,000", "00:00:01,000", "ola")],
            fontsize=70,
            margin_v=576,
            video_width=1080,
            video_height=1920,
        )

        self.assertIn("PlayResX: 1080", content)
        self.assertIn("PlayResY: 1920", content)
        self.assertIn(",70,", content)
        self.assertIn(",576,1", content)

    def test_escapes_braces_and_converts_newlines(self):
        content = hardsub_service.build_ass_content(
            entries=[("00:00:00,000", "00:00:01,000", "linha 1\nlinha {2}")],
            fontsize=40,
            margin_v=10,
            video_width=100,
            video_height=100,
        )

        self.assertIn("linha 1\\Nlinha \\{2\\}", content)


class RunHardsubAutoDetectFormatTest(unittest.TestCase):
    def test_uses_detected_orientation_instead_of_passed_format_profile(self):
        portrait_info = types.SimpleNamespace(duration_sec=5.0, width=1080, height=1920)

        with mock.patch("hardsub_service.ffmpeg_utils.resolve_ffmpeg_path", return_value="ffmpeg"), \
                mock.patch("hardsub_service.ffmpeg_utils.probe_video", return_value=portrait_info), \
                mock.patch("hardsub_service.ffmpeg_utils.assert_safe_path_length"), \
                mock.patch("hardsub_service.ffmpeg_utils.ensure_short_srt_path", side_effect=lambda p: p), \
                mock.patch("hardsub_service.ffmpeg_utils.run_ffmpeg_with_progress"), \
                mock.patch("hardsub_service.ensure_srt_for_lang", return_value="C:/videos/clip.srt"), \
                mock.patch("hardsub_service.write_ass_for_srt") as mock_write_ass, \
                mock.patch("hardsub_service.build_ffmpeg_burn_command", return_value=["ffmpeg"]), \
                mock.patch.object(Path, "exists", return_value=True):
            hardsub_service.run_hardsub(
                video_path="C:/videos/clip.mp4",
                original_srt_path="C:/videos/clip.srt",
                source_language="pt",
                mode="zh-original",
                format_profile="long",  # simula a UI mandando o preset errado
                output_path="C:/videos/out.mp4",
            )

        # write_ass_for_srt(srt_path, ass_path, fontsize, margin_v, video_width, video_height)
        called_fontsizes = [call.args[2] for call in mock_write_ass.call_args_list]
        expected_fontsize_shorts = round(1920 * hardsub_service.FONT_SCALE["shorts"])
        self.assertTrue(called_fontsizes)
        self.assertTrue(all(fontsize == expected_fontsize_shorts for fontsize in called_fontsizes))


class BuildFfmpegBurnCommandTest(unittest.TestCase):
    def test_single_language_uses_one_subtitles_filter(self):
        args = hardsub_service.build_ffmpeg_burn_command(
            ffmpeg_path="ffmpeg",
            video_path="C:/videos/clip.mp4",
            ass_paths_top_to_bottom=["C:/videos/clip.zh.burn-0.ass"],
            output_path="C:/videos/clip.hardsub.zh.mp4",
        )

        joined = " ".join(args)
        self.assertIn("-vf", args)
        self.assertEqual(joined.count("subtitles="), 1)
        self.assertIn("clip.hardsub.zh.mp4", args[-1])

    def test_dual_language_chains_two_subtitles_filters(self):
        args = hardsub_service.build_ffmpeg_burn_command(
            ffmpeg_path="ffmpeg",
            video_path="C:/videos/clip.mp4",
            ass_paths_top_to_bottom=["C:/videos/clip.zh.burn-0.ass", "C:/videos/clip.en.burn-1.ass"],
            output_path="C:/videos/clip.hardsub.zh-en.mp4",
        )

        vf_index = args.index("-vf")
        filter_value = args[vf_index + 1]

        self.assertEqual(filter_value.count("subtitles="), 2)


if __name__ == "__main__":
    unittest.main()
