import itertools
import unittest

from cortes.segmenter import Durations, choose_boundaries

DEFAULT = Durations()


def lengths(bounds: list[float]) -> list[float]:
    return [b - a for a, b in itertools.pairwise(bounds)]


class ChooseBoundariesTest(unittest.TestCase):
    def test_prefers_the_strong_candidate_near_the_target(self):
        self.assertEqual(choose_boundaries([(150.0, 10.0), (100.0, 2.0), (200.0, 2.0)], 0.0, 300.0), [0.0, 150.0, 300.0])

    def test_never_makes_a_clip_shorter_than_min(self):
        self.assertEqual(choose_boundaries([(30.0, 10.0), (150.0, 1.0)], 0.0, 300.0), [0.0, 150.0, 300.0])

    def test_uses_emergency_points_when_there_is_no_candidate(self):
        bounds = choose_boundaries([], 0.0, 400.0)
        self.assertEqual(len(bounds), 3)
        for length in lengths(bounds):
            self.assertTrue(DEFAULT.min_sec <= length <= DEFAULT.max_sec, length)

    def test_last_clip_respects_min_when_possible(self):
        durations = Durations(70.0, 150.0, 300.0)
        bounds = choose_boundaries([(290.0, 10.0)], 0.0, 320.0, durations)
        self.assertNotIn(290.0, bounds)
        self.assertTrue(all(length >= 70.0 for length in lengths(bounds)))

    def test_relaxes_last_clip_when_there_is_no_other_way(self):
        bounds = choose_boundaries([], 0.0, 120.0, Durations(70.0, 150.0, 100.0))
        self.assertEqual((bounds[0], bounds[-1], len(bounds)), (0.0, 120.0, 3))
        self.assertTrue(70.0 <= bounds[1] <= 100.0)

    def test_short_trecho_is_one_clip(self):
        self.assertEqual(choose_boundaries([], 0.0, 50.0), [0.0, 50.0])

    def test_respects_trecho_offset(self):
        bounds = choose_boundaries([(294.44, 10.0)], 144.44, 444.44)
        self.assertEqual(bounds, [144.44, 294.44, 444.44])

    def test_many_average_candidates_do_not_multiply_the_clips(self):
        # Candidato a cada 4s com nota media: o numero de clipes tem que vir do alvo (630s / 150s ~ 4),
        # e nao de quantos cortes da pra somar.
        candidates = [(t, 3.0 + (i % 6)) for i, t in enumerate(range(148, 774, 4))]
        bounds = choose_boundaries(candidates, 144.0, 774.0)
        self.assertIn(len(bounds) - 1, (4, 5))

    def test_empty_trecho_is_an_error(self):
        with self.assertRaises(ValueError):
            choose_boundaries([], 10.0, 10.0)
