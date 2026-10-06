import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def load_clip_splitter_service():
    module_path = Path(__file__).with_name("clip_splitter_service.py")
    spec = importlib.util.spec_from_file_location("clip_splitter_service_for_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ClipSplitterPreEditDecisionTest(unittest.TestCase):
    def setUp(self):
        self.service = load_clip_splitter_service()

    def test_mid_idea_pause_is_compressed_without_dry_cut(self):
        pauses = [{"start": 1.0, "end": 2.2, "duration": 1.2, "source": "audio"}]
        segments = [
            {"start": 0.0, "end": 1.0, "text": "eu tenho que"},
            {"start": 2.2, "end": 3.0, "text": "pegar aquilo"},
        ]

        decisions = self.service.build_pause_edit_decisions(pauses, segments, mode="balanced")

        self.assertEqual(decisions[0]["type"], "mid_idea_pause")
        self.assertEqual(decisions[0]["action"], "compress")
        self.assertGreaterEqual(decisions[0]["keep_duration"], 0.45)

    def test_long_dead_silence_is_compressed_hard_in_balanced_mode(self):
        pauses = [{"start": 10.0, "end": 13.0, "duration": 3.0, "source": "audio"}]
        segments = [
            {"start": 0.0, "end": 1.0, "text": "beleza"},
            {"start": 13.0, "end": 14.0, "text": "voltamos"},
        ]

        decisions = self.service.build_pause_edit_decisions(pauses, segments, mode="balanced")

        self.assertEqual(decisions[0]["type"], "dead_silence")
        self.assertEqual(decisions[0]["action"], "compress")
        self.assertLessEqual(decisions[0]["keep_duration"], 0.3)

    def test_aggressive_mode_can_remove_very_long_dead_silence(self):
        pauses = [{"start": 10.0, "end": 15.0, "duration": 5.0, "source": "audio"}]
        segments = [{"start": 0.0, "end": 1.0, "text": "beleza"}]

        decisions = self.service.build_pause_edit_decisions(pauses, segments, mode="aggressive")

        self.assertEqual(decisions[0]["type"], "dead_silence")
        self.assertEqual(decisions[0]["action"], "remove")
        self.assertEqual(decisions[0]["keep_duration"], 0.0)

    def test_edit_ranges_keep_one_ordered_timeline(self):
        decisions = [
            {"start": 1.0, "end": 2.2, "duration": 1.2, "action": "compress", "keep_duration": 0.5},
            {"start": 5.0, "end": 8.0, "duration": 3.0, "action": "compress", "keep_duration": 0.25},
        ]

        ranges = self.service.build_preedit_keep_ranges(10.0, decisions)

        self.assertEqual(ranges[0]["start"], 0.0)
        self.assertEqual(ranges[-1]["end"], 10.0)
        self.assertTrue(all(ranges[index]["end"] <= ranges[index + 1]["start"] for index in range(len(ranges) - 1)))
        self.assertLess(sum(item["end"] - item["start"] for item in ranges), 10.0)

    def test_preedit_clip_export_represents_single_clean_video(self):
        export = self.service.build_preedit_export_payload(
            source_path="D:/Videos/bruto.mp4",
            output_file="D:/Videos/bruto_preedit/bruto_preedit.mp4",
            source_duration_sec=3600.0,
            edited_duration_sec=2400.0,
            decisions_count=42,
        )

        self.assertEqual(export["index"], 1)
        self.assertEqual(export["fileName"], "bruto_preedit.mp4")
        self.assertEqual(export["durationSec"], 2400.0)
        self.assertIn("42", export["reason"])

    def test_debug_json_is_optional_file_with_decision_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "nested" / "bruto_preedit.mp4"
            decisions = [
                {
                    "start": 12.4,
                    "end": 13.8,
                    "duration": 1.4,
                    "type": "dead_silence",
                    "action": "compress",
                    "keep_duration": 0.25,
                    "reason": "long silence with no useful context",
                }
            ]

            debug_path = Path(self.service.write_debug_decisions(output_file, decisions))
            payload = json.loads(debug_path.read_text(encoding="utf-8"))

            self.assertEqual(debug_path.name, "bruto_preedit.debug.json")
            self.assertEqual(payload, decisions)

    def test_mic_track_name_resolves_to_matching_audio_stream(self):
        streams = [
            {"index": 1, "audio_index": 0, "title": "Game"},
            {"index": 2, "audio_index": 1, "title": "Mic"},
        ]

        selected = self.service.resolve_analysis_audio_track("mic", streams)

        self.assertEqual(selected["audio_index"], 1)
        self.assertEqual(selected["stream_index"], 2)
        self.assertIn("mic", selected["reason"].lower())

    def test_default_analysis_track_prefers_second_audio_stream_for_voice(self):
        streams = [
            {"index": 1, "audio_index": 0, "title": "Game"},
            {"index": 2, "audio_index": 1, "title": "Voice"},
        ]

        selected = self.service.resolve_analysis_audio_track(None, streams)

        self.assertEqual(selected["audio_index"], 1)
        self.assertEqual(selected["stream_index"], 2)
        self.assertIn("default voice", selected["reason"].lower())

    def test_parse_args_defaults_to_second_ffmpeg_audio_track(self):
        with patch.object(sys, "argv", ["clip_splitter_service.py", "input.mp4"]):
            args = self.service.parse_args()

        self.assertEqual(args.analysis_audio_track, "1")

    def test_default_analysis_track_falls_back_when_second_audio_stream_is_missing(self):
        streams = [
            {"index": 1, "audio_index": 0, "title": "Mixed"},
        ]

        selected = self.service.resolve_analysis_audio_track(None, streams)

        self.assertEqual(selected["audio_index"], 0)
        self.assertIn("fallback", selected["reason"].lower())

    def test_unknown_mic_track_falls_back_to_first_audio_stream(self):
        streams = [
            {"index": 1, "audio_index": 0, "title": "Game"},
            {"index": 2, "audio_index": 1, "title": "Discord"},
        ]

        selected = self.service.resolve_analysis_audio_track("mic", streams)

        self.assertEqual(selected["audio_index"], 0)
        self.assertIn("fallback", selected["reason"].lower())

    def test_preedit_ffmpeg_command_preserves_each_audio_track_separately(self):
        module = SimpleNamespace(FFMPEG="ffmpeg")
        keep_ranges = [{"start": 0.0, "end": 1.0}, {"start": 2.0, "end": 3.0}]

        command = self.service.build_preedit_ffmpeg_command(
            module,
            "input.mp4",
            Path("output.mp4"),
            keep_ranges,
            audio_stream_count=3,
        )
        command_text = " ".join(command)

        self.assertIn("[0:a:0]", command_text)
        self.assertIn("[0:a:1]", command_text)
        self.assertIn("[0:a:2]", command_text)
        self.assertIn("[outa0]", command)
        self.assertIn("[outa1]", command)
        self.assertIn("[outa2]", command)
        self.assertNotIn("[0:a]atrim", command_text)
        self.assertNotIn("[outa]", command)


if __name__ == "__main__":
    unittest.main()
