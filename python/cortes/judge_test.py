import re
import unittest

from llm_service import LLMResponseError

from cortes.candidates import Candidate
from cortes.judge import JudgeResponseError, build_windows, judge_candidates, judge_window, validate_scores


class FakeClient:
    def __init__(self, reply):
        self.reply = reply  # (user, temperature) -> payload ou excecao
        self.calls = []

    def chat_json(self, system, user, temperature=0):
        self.calls.append((user, temperature))
        result = self.reply(user, temperature)
        if isinstance(result, Exception):
            raise result
        return result


def sequence_of(*payloads):
    remaining = list(payloads)
    return lambda _user, _temperature: remaining.pop(0)


def by_markers(table):
    def reply(user, _temperature):
        return table[re.search(r"Marcadores para dar nota: (.*)", user).group(1)]

    return reply


class BuildWindowsTest(unittest.TestCase):
    def test_ten_minute_windows_with_one_minute_overlap(self):
        self.assertEqual(build_windows(0.0, 1000.0), [(0.0, 600.0), (540.0, 1000.0)])
        self.assertEqual(build_windows(0.0, 500.0), [(0.0, 500.0)])
        self.assertEqual(build_windows(100.0, 1300.0), [(100.0, 700.0), (640.0, 1240.0), (1180.0, 1300.0)])


class ValidateScoresTest(unittest.TestCase):
    def test_accepts_integer_scores_for_every_marker(self):
        self.assertEqual(validate_scores({"notas": {"C1": 7, "C2": 0.0}}, ["C1", "C2"]), {"C1": 7, "C2": 0})

    def test_rejects_bad_answers(self):
        cases = {
            "faltou o objeto": ["x", {"scores": {}}],
            "nao existem": [{"notas": {"C1": 1, "C9": 2}}],
            "faltou nota": [{"notas": {}}],
            "inteira de 0 a 10": [{"notas": {"C1": 11}}, {"notas": {"C1": 7.5}}, {"notas": {"C1": True}}, {"notas": {"C1": "7"}}],
        }
        for reason, payloads in cases.items():
            for payload in payloads:
                with self.subTest(payload=payload), self.assertRaisesRegex(JudgeResponseError, reason):
                    validate_scores(payload, ["C1"])


class JudgeWindowTest(unittest.TestCase):
    def test_retries_with_the_reason_and_more_temperature(self):
        client = FakeClient(sequence_of({"notas": {"C1": 11}}, {"notas": {"C1": 6}}))
        self.assertEqual(judge_window(client, ["[00:10] [C1]"], ["C1"]), {"C1": 6})
        self.assertEqual([temperature for _user, temperature in client.calls], [0, 0.4])
        self.assertIn("rejeitada", client.calls[1][0])

    def test_invalid_json_counts_as_an_attempt(self):
        client = FakeClient(sequence_of(LLMResponseError("nao e JSON"), {"notas": {"C1": 3}}))
        self.assertEqual(judge_window(client, [], ["C1"]), {"C1": 3})

    def test_gives_up_after_three_attempts(self):
        client = FakeClient(lambda _u, _t: {"notas": {}})
        with self.assertRaises(JudgeResponseError):
            judge_window(client, [], ["C1"])
        self.assertEqual(len(client.calls), 3)


class JudgeCandidatesTest(unittest.TestCase):
    def setUp(self):
        self.candidates = [Candidate("C1", 30.0, 5.0), Candidate("C2", 570.0, 5.0), Candidate("C3", 900.0, 5.0)]

    def test_averages_overlapping_windows_and_reports_progress(self):
        client = FakeClient(by_markers({"C1, C2": {"notas": {"C1": 8, "C2": 4}}, "C2, C3": {"notas": {"C2": 6, "C3": 2}}}))
        progress = []
        warnings = judge_candidates(client, [], [], self.candidates, 0.0, 1000.0, lambda d, t: progress.append((d, t)))
        self.assertEqual(warnings, [])
        self.assertEqual([c.judge for c in self.candidates], [8.0, 5.0, 2.0])
        self.assertEqual(progress, [(1, 2), (2, 2)])

    def test_failed_window_keeps_rule_only_and_warns(self):
        client = FakeClient(lambda _u, _t: "lixo")
        warnings = judge_candidates(client, [], [], self.candidates, 0.0, 1000.0)
        self.assertEqual(len(warnings), 2)
        self.assertIn("janela 1", warnings[0])
        self.assertEqual([c.judge for c in self.candidates], [None, None, None])
        self.assertEqual(self.candidates[0].score, 5.0)
