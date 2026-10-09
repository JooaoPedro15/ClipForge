import unittest

from cortes.titles import TitleResponseError, clip_scores, reaction_fraction, title_clip, validate_title


class FakeClient:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []

    def chat_json(self, system, user, temperature=0):
        self.calls.append((user, temperature))
        return self.payloads.pop(0)


class ValidateTitleTest(unittest.TestCase):
    def test_cleans_title_and_reads_hook(self):
        self.assertEqual(validate_title({"titulo": ' "Ele descobriu tudo" ', "gancho": 8.0}), ("Ele descobriu tudo", 8))

    def test_rejects_bad_answers(self):
        for payload in (
            "x",
            {"titulo": "", "gancho": 5},
            {"titulo": "a" * 41, "gancho": 5},
            {"titulo": "ok", "gancho": 11},
            {"titulo": "ok", "gancho": 6.5},
            {"titulo": "ok"},
        ):
            with self.subTest(payload=payload), self.assertRaises(TitleResponseError):
                validate_title(payload)


class TitleClipTest(unittest.TestCase):
    def test_retries_with_the_reason(self):
        client = FakeClient({"titulo": "", "gancho": 5}, {"titulo": "A virada", "gancho": 7})
        self.assertEqual(title_clip(client, ["[00:10] FILME: Oi"]), ("A virada", 7))
        self.assertIn("rejeitada", client.calls[1][0])


class ScoresTest(unittest.TestCase):
    def test_reaction_fraction(self):
        self.assertEqual(reaction_fraction([[10.0, 20.0], [30.0, 35.0], [50.0, 60.0]], 0.0, 40.0), 0.375)

    def test_score_mixes_hook_and_normalized_reaction(self):
        self.assertEqual(clip_scores([8, None, 4], [0.2, 0.4, 0.0]), [7.1, 10.0, 2.8])

    def test_no_reaction_anywhere(self):
        self.assertEqual(clip_scores([None, 6], [0.0, 0.0]), [0.0, 4.2])
