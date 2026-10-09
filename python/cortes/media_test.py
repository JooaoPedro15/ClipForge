import unittest

from cortes.media import SourceMedia, parse_probe

PROBE = {
    "streams": [{"codec_type": "video", "width": 3840, "height": 1080, "r_frame_rate": "60/1"}]
    + [{"codec_type": "audio"}] * 4,
    "format": {"duration": "7298.100000"},
}


class ParseProbeTest(unittest.TestCase):
    def test_reads_duration_fps_size_and_audio_count(self):
        self.assertEqual(parse_probe("E:\\b.mp4", PROBE), SourceMedia("E:\\b.mp4", 7298.1, 60.0, 3840, 1080, 4))

    def test_ntsc_fraction(self):
        data = {**PROBE, "streams": [{**PROBE["streams"][0], "r_frame_rate": "30000/1001"}]}
        self.assertEqual(parse_probe("x.mp4", data).fps, 29.97)

    def test_file_without_video_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "video"):
            parse_probe("x.wav", {"streams": [{"codec_type": "audio"}], "format": {"duration": "10"}})
