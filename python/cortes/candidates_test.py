import unittest

from cortes.candidates import Candidate, build_candidates, silent_gaps, speech_intervals


def w(text: str, start: float, end: float) -> dict:
    return {"word": text, "start": start, "end": end}


class SpeechIntervalsTest(unittest.TestCase):
    def test_merges_words_closer_than_the_gap(self):
        words = [w("a", 0.0, 1.0), w("b", 1.5, 2.0), w("c", 3.0, 4.0)]
        self.assertEqual(speech_intervals(words), [(0.0, 2.0), (3.0, 4.0)])


class SilentGapsTest(unittest.TestCase):
    def test_nobody_talking_means_neither_film_nor_mic(self):
        film = [w("a", 0.0, 2.0), w("b", 5.0, 6.0)]
        mic = [w("nossa", 2.5, 3.0)]
        self.assertEqual(silent_gaps(film, mic, 0.0, 10.0), [(3.0, 5.0), (6.0, 10.0)])

    def test_respects_trecho_start(self):
        film = [w("a", 0.0, 2.0), w("b", 5.0, 6.0)]
        mic = [w("nossa", 2.5, 3.0)]
        self.assertEqual(silent_gaps(film, mic, 4.0, 10.0), [(4.0, 5.0), (6.0, 10.0)])


class BuildCandidatesTest(unittest.TestCase):
    def test_snaps_to_shot_cut_and_scores_signals(self):
        film = [w("Acabou.", 10.0, 12.0), w("Ola", 16.0, 17.0)]
        found = build_candidates(film, [], shot_cuts=[14.6], film_silences=[(12.5, 15.5)], start=0.0, end=30.0)
        self.assertEqual(
            found,
            [Candidate("C1", 5.0, 4.0), Candidate("C2", 14.6, 10.0), Candidate("C3", 23.5, 4.0)],
        )

    def test_keeps_the_best_of_candidates_closer_than_3s(self):
        film = [w("a", 0.0, 1.0), w("b", 1.8, 2.0), w("c", 3.0, 8.0)]
        found = build_candidates(film, [], [], [], 0.0, 10.0)
        self.assertEqual(found, [Candidate("C1", 2.5, 1.0), Candidate("C2", 9.0, 2.0)])

    def test_drops_points_glued_to_trecho_edges(self):
        found = build_candidates([w("a", 1.2, 5.0)], [], [], [], 0.0, 10.0)
        self.assertEqual([c.t for c in found], [7.5])

    def test_never_cuts_while_the_user_is_talking(self):
        found = build_candidates([], [w("nossa", 4.0, 6.0)], shot_cuts=[5.0], film_silences=[], start=0.0, end=10.0)
        self.assertEqual([c.t for c in found], [2.0, 8.0])


class CandidateScoreTest(unittest.TestCase):
    def test_rule_only_until_the_judge_answers(self):
        self.assertEqual(Candidate("C1", 1.0, 5.0).score, 5.0)
        self.assertEqual(Candidate("C1", 1.0, 5.0, judge=10.0).score, 8.0)
