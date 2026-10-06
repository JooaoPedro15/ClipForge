"""Teste de caracterizacao da transcricao (golden test).

Trava a saida EXATA (.srt e .cards.json) pra refatorar o pipeline sem
mudar comportamento sem querer. Se este teste mudar, o commit tem que dizer por que.
"""

import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
sys.modules.setdefault("faster_whisper", types.SimpleNamespace(WhisperModel=object))
import subtitle_service  # noqa: E402


@dataclass
class GoldenWord:
    word: str
    start: float
    end: float


@dataclass
class GoldenSegment:
    start: float
    end: float
    text: str
    words: list
    avg_logprob: float


def timed_words(text: str, start: float, step: float, duration: float) -> list[GoldenWord]:
    return [
        GoldenWord(word=f" {token}", start=round(start + index * step, 3), end=round(start + index * step + duration, 3))
        for index, token in enumerate(text.split())
    ]


SHORT_TEXT = "Então, ela falou que não ia voltar pra casa hoje de jeito nenhum."
LONG_TEXT = "aí o cara chegou correndo e gritou que a casa tava pegando fogo de verdade mano"
SHORT_WORDS = timed_words(SHORT_TEXT, 0.0, 0.35, 0.3)
LONG_WORDS = timed_words(LONG_TEXT, 5.0, 0.6, 0.5)
SEGMENTS = [
    GoldenSegment(0.0, SHORT_WORDS[-1].end, f" {SHORT_TEXT}", SHORT_WORDS, -0.1),  # natural curto
    GoldenSegment(5.0, LONG_WORDS[-1].end, f" {LONG_TEXT}", LONG_WORDS, -0.3),  # natural > 7s, refatiado
    GoldenSegment(15.0, 16.2, " Valeu, galera!", [], -0.5),  # sem timestamps por palavra
]

NATURAL_SRT = (
    "1\n00:00:00,000 --> 00:00:04,500\nEntão, ela falou que não ia voltar pra\ncasa hoje de jeito nenhum.\n\n"
    "2\n00:00:05,000 --> 00:00:09,100\naí o cara chegou correndo e gritou\n\n"
    "3\n00:00:09,200 --> 00:00:14,500\nque a casa tava pegando fogo de verdade mano\n\n"
    "4\n00:00:15,000 --> 00:00:16,200\nValeu, galera!\n"
)
NATURAL_CARDS = [
    {"i": 0, "start": 0.0, "end": 4.5, "text": SHORT_TEXT, "segment_id": 0, "avg_logprob": -0.1},
    {"i": 1, "start": 5.0, "end": 9.1, "text": "aí o cara chegou correndo e gritou", "segment_id": 1, "avg_logprob": -0.3},
    {"i": 2, "start": 9.2, "end": 14.5, "text": "que a casa tava pegando fogo de verdade mano", "segment_id": 1, "avg_logprob": -0.3},
    {"i": 3, "start": 15.0, "end": 16.2, "text": "Valeu, galera!", "segment_id": 2, "avg_logprob": -0.5},
]
WORD_GROUP_SRT = (
    "1\n00:00:00,000 --> 00:00:01,000\nENTAO, ELA FALOU\n\n"
    "2\n00:00:01,050 --> 00:00:02,050\nQUE NAO IA\n\n"
    "3\n00:00:02,100 --> 00:00:03,100\nVOLTAR PRA CASA\n\n"
    "4\n00:00:03,150 --> 00:00:04,500\nHOJE DE JEITO NENHUM.\n\n"
    "5\n00:00:05,000 --> 00:00:06,700\nAI O CARA\n\n"
    "6\n00:00:06,800 --> 00:00:07,900\nCHEGOU CORRENDO\n\n"
    "7\n00:00:08,000 --> 00:00:09,100\nE GRITOU\n\n"
    "8\n00:00:09,200 --> 00:00:10,900\nQUE A CASA\n\n"
    "9\n00:00:11,000 --> 00:00:12,700\nTAVA PEGANDO FOGO\n\n"
    "10\n00:00:12,800 --> 00:00:14,500\nDE VERDADE MANO\n"
)
WORD_GROUP_CARDS = [
    {"i": 0, "start": 0.0, "end": 1.0, "text": "Então, ela falou", "segment_id": 0, "avg_logprob": -0.1},
    {"i": 1, "start": 1.05, "end": 2.05, "text": "que não ia", "segment_id": 0, "avg_logprob": -0.1},
    {"i": 2, "start": 2.1, "end": 3.1, "text": "voltar pra casa", "segment_id": 0, "avg_logprob": -0.1},
    {"i": 3, "start": 3.15, "end": 4.5, "text": "hoje de jeito nenhum.", "segment_id": 0, "avg_logprob": -0.1},
    {"i": 4, "start": 5.0, "end": 6.7, "text": "aí o cara", "segment_id": 1, "avg_logprob": -0.3},
    {"i": 5, "start": 6.8, "end": 7.9, "text": "chegou correndo", "segment_id": 1, "avg_logprob": -0.3},
    {"i": 6, "start": 8.0, "end": 9.1, "text": "e gritou", "segment_id": 1, "avg_logprob": -0.3},
    {"i": 7, "start": 9.2, "end": 10.9, "text": "que a casa", "segment_id": 1, "avg_logprob": -0.3},
    {"i": 8, "start": 11.0, "end": 12.7, "text": "tava pegando fogo", "segment_id": 1, "avg_logprob": -0.3},
    {"i": 9, "start": 12.8, "end": 14.5, "text": "de verdade mano", "segment_id": 1, "avg_logprob": -0.3},
]


class TranscriptionGoldenTest(unittest.TestCase):
    def transcribe(self, segments: list[GoldenSegment], **options) -> tuple[str, list[dict]]:
        info = types.SimpleNamespace(language="pt", language_probability=0.99, duration=segments[-1].end)

        class FakeWhisperModel:
            def __init__(self, *args, **kwargs):
                pass

            def transcribe(self, *args, **kwargs):
                return segments, info

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / "video.mp4"
            input_path.write_bytes(b"fake")
            with mock.patch.object(subtitle_service, "WhisperModel", FakeWhisperModel), contextlib.redirect_stdout(io.StringIO()):
                output_path = Path(subtitle_service.transcribe_video(input_path=str(input_path), **options))
            srt = output_path.read_text(encoding="utf-8")
            cards = json.loads(output_path.with_suffix(".cards.json").read_text(encoding="utf-8"))
        return srt, cards

    def test_natural_mode_matches_golden_output(self):
        srt, cards = self.transcribe(SEGMENTS, max_words=0)

        self.assertEqual(srt, NATURAL_SRT)
        self.assertEqual(cards, NATURAL_CARDS)

    def test_word_group_mode_with_uppercase_and_no_accents_matches_golden_output(self):
        srt, cards = self.transcribe(SEGMENTS[:2], max_words=3, uppercase=True, no_accents=True)

        self.assertEqual(srt, WORD_GROUP_SRT)
        self.assertEqual(cards, WORD_GROUP_CARDS)


if __name__ == "__main__":
    unittest.main()
