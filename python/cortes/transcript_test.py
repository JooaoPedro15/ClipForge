import unittest

from cortes.candidates import Candidate
from cortes.transcript import clock, transcript_lines


class TranscriptLinesTest(unittest.TestCase):
    def test_mixes_film_mic_and_markers_in_time_order(self):
        film = [{"start": 10.0, "end": 12.0, "text": "Acabou."}, {"start": 200.0, "end": 201.0, "text": "Fora"}]
        mic = [{"start": 11.0, "end": 12.0, "text": "nossa"}]
        lines = transcript_lines(film, mic, 0.0, 100.0, [Candidate("C1", 13.0, 5.0)])
        self.assertEqual(lines, ["[00:10] FILME: Acabou.", "[00:11] VOCE: nossa", "[00:13] [C1]"])

    def test_clock_with_hours(self):
        self.assertEqual(clock(3725.4), "1:02:05")
