import unittest
from pathlib import Path

from cortes.extract import ExtractPaths, build_extract_command, parse_scene_times, parse_silences

PATHS = ExtractPaths(Path("T:/tmp/filme.wav"), Path("T:/tmp/mic.wav"), Path("T:/tmp/planos.txt"))


class BuildExtractCommandTest(unittest.TestCase):
    def test_reads_the_source_once_with_gpu_and_trecho(self):
        command = build_extract_command("ffmpeg", "E:\\Bruto\\react.mp4", PATHS, 0, 1, 144.44, 774.0)
        self.assertEqual(
            command,
            [
                "ffmpeg", "-hide_banner", "-y", "-hwaccel", "cuda", "-ss", "144.440", "-to", "774.000",
                "-i", "E:\\Bruto\\react.mp4",
                "-map", "0:v:0", "-vf",
                "crop=iw/2:ih:0:0,scale=320:-2,select='gt(scene,0.3)',metadata=print:file=planos.txt",
                "-f", "null", "-",
                "-map", "0:a:0", "-ac", "1", "-ar", "16000", str(PATHS.film_wav),
                "-map", "0:a:1", "-ac", "1", "-ar", "16000", str(PATHS.mic_wav),
            ],
        )

    def test_cpu_and_whole_video(self):
        command = build_extract_command("ffmpeg", "a.mp4", PATHS, 2, 0, 0.0, 600.0, hwaccel=False)
        self.assertNotIn("-hwaccel", command)
        self.assertNotIn("-ss", command)
        self.assertIn("0:a:2", command)

    def test_scene_file_is_relative_so_the_path_never_needs_escaping(self):
        odd = ExtractPaths(Path("D:/Vídeos/d'agua/filme.wav"), Path("D:/Vídeos/d'agua/mic.wav"), Path("D:/Vídeos/d'agua/planos.txt"))
        command = build_extract_command("ffmpeg", "a.mp4", odd, 0, 1, 0.0, 10.0)
        video_filter = command[command.index("-vf") + 1]
        self.assertTrue(video_filter.endswith("metadata=print:file=planos.txt"))


class ParseSceneTimesTest(unittest.TestCase):
    def test_adds_trecho_offset(self):
        text = "frame:0    pts:749    pts_time:12.483\nlavfi.scene_score=0.512\nframe:1    pts:901    pts_time:15.017\n"
        self.assertEqual(parse_scene_times(text, 100.0), [112.483, 115.017])


class ParseSilencesTest(unittest.TestCase):
    def test_pairs_start_and_end_and_closes_open_silence_at_end(self):
        text = (
            "[silencedetect @ 0x1] silence_start: -0.0213\n"
            "[silencedetect @ 0x1] silence_end: 1.5 | silence_duration: 1.52\n"
            "[silencedetect @ 0x1] silence_start: 10.25\n"
        )
        self.assertEqual(parse_silences(text, 100.0, 130.0), [(100.0, 101.5), (110.25, 130.0)])
