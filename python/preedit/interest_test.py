import json
import os
import tempfile
import unittest
from pathlib import Path

from llm_service import LLMUnavailableError

from preedit import interest
from preedit.phrases import Phrase


def phrases(count: int, spacing: float = 5.0) -> list[Phrase]:
    return [Phrase(i, i, i, i * spacing, i * spacing + 2.0, f"frase {i}") for i in range(count)]


class FakeClient:
    model = "qwen-falso"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat_json(self, system, user, temperature=0):
        self.calls.append((system, user, temperature))
        reply = self.replies.pop(0) if self.replies else self.default(user)
        return reply(user) if callable(reply) else reply

    @staticmethod
    def default(user):
        keys = [part.split("]")[0] for part in user.split("[F")[1:]]
        return {"notas": {f"F{key}": 8 for key in keys}}


class ScorePhrasesTest(unittest.TestCase):
    def test_every_phrase_gets_a_score_and_the_prompt_follows_the_format(self):
        client = FakeClient([])

        scores, fallbacks = interest.score_phrases(client, phrases(3), "longo")

        self.assertEqual((scores, fallbacks), ({0: 8.0, 1: 8.0, 2: 8.0}, 0))
        self.assertEqual(client.calls[0][0], interest.PROMPTS["longo"])
        self.assertIn("[F1] 00:05 frase 1", client.calls[0][1])

    def test_bad_reply_is_retried_warmer_and_missing_keys_are_neutral(self):
        client = FakeClient([{"oi": 1}, {"notas": {"F0": 9, "F1": 2, "F2": 4, "F3": 7}}])

        scores, _ = interest.score_phrases(client, phrases(5), "short")

        self.assertEqual([call[2] for call in client.calls], [0, 0.4])
        self.assertEqual(scores[0], 9.0)
        self.assertEqual(scores[4], interest.NEUTRAL)

    def test_long_recordings_go_in_overlapping_windows(self):
        client = FakeClient([])

        scores, _ = interest.score_phrases(client, phrases(150), "longo")  # 750 s em janelas de 5 min

        self.assertEqual(len(client.calls), 3)
        self.assertEqual(len(scores), 150)


class LoadInterestTest(unittest.TestCase):
    def test_cache_is_reused_while_the_transcript_is_the_same(self):
        with tempfile.TemporaryDirectory() as tmp:
            recording = str(Path(tmp) / "gravacao.mp4")
            client = FakeClient([])

            first, warning = interest.load_interest(recording, phrases(2), "longo", lambda: client)
            second, _ = interest.load_interest(recording, phrases(2), "longo", lambda: client)

            self.assertIsNone(warning)
            self.assertEqual(first, second)
            self.assertEqual(len(client.calls), 1)
            cached = json.loads((Path(tmp) / "gravacao.interest.longo.json").read_text(encoding="utf-8"))
            self.assertEqual(cached["model"], "qwen-falso")

    def test_notes_from_another_model_are_scored_again(self):
        # Treino e edicao com notas do mesmo modelo: nota de outro modelo no cache e refeita.
        with tempfile.TemporaryDirectory() as tmp:
            recording = str(Path(tmp) / "gravacao.mp4")
            interest.load_interest(recording, phrases(2), "longo", lambda: FakeClient([]))
            other = FakeClient([])
            other.model = "qwen-outro"

            interest.load_interest(recording, phrases(2), "longo", lambda: other)

            self.assertEqual(len(other.calls), 1)

    def test_preedit_uses_the_7b_model_unless_told_otherwise(self):
        self.assertEqual(interest.INTEREST_MODEL, "qwen2.5:7b-instruct")
        self.assertEqual(interest.create_interest_client().model, os.environ.get("CLIPFORGE_OLLAMA_MODEL", "qwen2.5:7b-instruct"))

    def test_window_the_ai_never_answers_warns_and_is_not_cached(self):
        client = FakeClient([{"oi": 1}] * 3)
        with tempfile.TemporaryDirectory() as tmp:
            recording = str(Path(tmp) / "gravacao.mp4")

            scores, warning = interest.load_interest(recording, phrases(2), "longo", lambda: client)

            self.assertEqual(scores, {0: 5.0, 1: 5.0})
            self.assertIn("nota 5", warning)
            self.assertFalse((Path(tmp) / "gravacao.interest.longo.json").exists())

    def test_ollama_is_started_when_needed(self):
        client = FakeClient([])
        client.started = 0

        def ensure_server_running():
            client.started += 1
            return True

        client.ensure_server_running = ensure_server_running
        with tempfile.TemporaryDirectory() as tmp:
            interest.load_interest(str(Path(tmp) / "gravacao.mp4"), phrases(2), "longo", lambda: client)

        self.assertEqual(client.started, 1)

    def test_without_ollama_everything_is_neutral_and_nothing_is_cached(self):
        def unavailable():
            raise LLMUnavailableError("Ollama fora do ar")

        with tempfile.TemporaryDirectory() as tmp:
            recording = str(Path(tmp) / "gravacao.mp4")

            scores, warning = interest.load_interest(recording, phrases(2), "longo", unavailable)

            self.assertEqual(scores, {0: 5.0, 1: 5.0})
            self.assertIn("nota 5", warning)
            self.assertFalse((Path(tmp) / "gravacao.interest.longo.json").exists())


if __name__ == "__main__":
    unittest.main()
