import unittest

from cortes.timebase import Rate, format_clock, parse_clock, parse_ranges

NTSC_30 = Rate(30, True)


class RateTest(unittest.TestCase):
    def test_ntsc_fps_is_30000_over_1001(self):
        self.assertAlmostEqual(NTSC_30.fps, 29.97002997, places=6)

    def test_seconds_to_frames_rounds_to_nearest(self):
        self.assertEqual(NTSC_30.to_frames(100.0), 2997)
        self.assertEqual(NTSC_30.to_frames(175.0), 5245)

    def test_frames_to_seconds(self):
        self.assertAlmostEqual(NTSC_30.to_seconds(4800), 160.16, places=6)

    def test_ticks_match_premiere_export(self):
        # Valor real exportado pelo Premiere (Seq 17): in=4329 -> pproTicksIn=36691163308800
        self.assertEqual(NTSC_30.to_ticks(4329), 36691163308800)

    def test_ticks_for_integer_rate(self):
        self.assertEqual(Rate(60, False).to_ticks(60), 254016000000)

    def test_from_fps(self):
        self.assertEqual(Rate.from_fps(29.97), Rate(30, True))
        self.assertEqual(Rate.from_fps(30000 / 1001), Rate(30, True))
        self.assertEqual(Rate.from_fps(59.94), Rate(60, True))
        self.assertEqual(Rate.from_fps(60.0), Rate(60, False))
        self.assertEqual(Rate.from_fps(25.0), Rate(25, False))


class ClockTest(unittest.TestCase):
    def test_parse_clock_formats(self):
        self.assertEqual(parse_clock("2:24.44"), 144.44)
        self.assertEqual(parse_clock("1:02:03"), 3723.0)
        self.assertEqual(parse_clock("95.5"), 95.5)

    def test_parse_clock_rejects_garbage(self):
        for text in ("", "1::2", "a:10", "1:2:3:4"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_clock(text)

    def test_format_clock(self):
        self.assertEqual(format_clock(144.44), "2:24.44")
        self.assertEqual(format_clock(3723.0), "1:02:03.00")
        self.assertEqual(format_clock(59.996), "1:00.00")

    def test_parse_ranges(self):
        self.assertEqual(parse_ranges("2:24.44-3:39.72, 3:39.72-5:28.56"), [(144.44, 219.72), (219.72, 328.56)])

    def test_parse_ranges_rejects_inverted_or_missing_dash(self):
        for text in ("3:00-2:00", "3:00"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_ranges(text)
