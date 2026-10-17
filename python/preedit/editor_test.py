import itertools
import unittest

from preedit.audio import Loudness
from preedit.editor import plan_long, split_target
from preedit.features import PHRASE_FEATURES, RETAKE_FEATURES, ZOOM_FEATURES
from preedit.models import FormatModels

NOTE = PHRASE_FEATURES.index("nota_ia")
ZOOM_NOTE = ZOOM_FEATURES.index("nota_ia")
RETAKE_SIMILARITY = RETAKE_FEATURES.index("similaridade")


class Stub:
    """Arvore falsa: a chance de classe 1 vem de uma funcao das features."""

    classes_ = [0, 1]

    def __init__(self, chance):
        self.chance = chance

    def predict_proba(self, rows):
        return [[1 - self.chance(row), self.chance(row)] for row in rows]

    def predict(self, rows):
        return [self.chance(row) for row in rows]


def phrase_words(count: int, length: float = 4.0, gap: float = 1.0) -> list[dict]:
    """`count` frases de 2 palavras, cada uma com `length` s e `gap` s de pausa entre elas."""
    words = []
    for index in range(count):
        start = index * (length + gap)
        words.append({"word": f" fala{index}", "start": start, "end": start + length / 2 - 0.1})
        words.append({"word": f" coisa{index}.", "start": start + length / 2, "end": start + length})
    return words


def models(**overrides) -> FormatModels:
    base = {
        "trecho": Stub(lambda row: row[NOTE] / 10),
        "regravada": None,
        "pausa": Stub(lambda row: 200.0),  # deixa 200 ms de pausa
        "zoom": None,
        "nivel": None,
        "params": {"zooms_per_min": 0.0, "zoom_min_gap_s": 3.0, "zoom_duration_p10": 0.6, "zoom_duration_p90": 1.3, "zoom_level_median": 1.5},
    }
    return FormatModels(**{**base, **overrides})


LOUD = Loudness(0.1, [-30.0] * 2000)


class PlanLongTest(unittest.TestCase):
    def test_removes_the_weakest_phrases_until_the_target(self):
        words = phrase_words(10)  # 10 frases de 4 s
        interest = {i: (9.0 if i % 2 == 0 else 2.0) for i in range(10)}

        plan = plan_long(words, LOUD, interest, models(), target_sec=22.0)

        self.assertLessEqual(plan.duration, 22.0 * 1.05)
        kept_starts = [round(s.start) for s in plan.segments]
        self.assertTrue(all(start % 10 == 0 for start in kept_starts))  # so as frases pares (nota 9) ficaram
        self.assertTrue(any(name == "sem graca" for _, name in plan.markers))

    def test_shorter_than_target_keeps_everything_and_warns(self):
        words = phrase_words(3)

        plan = plan_long(words, LOUD, {}, models(), target_sec=600.0)

        # Pausa de 1 s vira 200 ms: o meio dela sai, entao as 3 frases sao 3 trechos.
        self.assertEqual(len(plan.segments), 3)
        self.assertAlmostEqual(plan.duration, 12.0 + 2 * 0.2 + 0.12, places=2)  # 3 frases + 2 pausas + folga do fim
        self.assertTrue(plan.warnings)

    def test_setup_of_a_strong_phrase_is_protected(self):
        words = phrase_words(4, gap=0.5)  # pausa curta (< 0,7 s) mas ainda separa frases (> 0,35 s)
        words[1]["word"] = " coisa0"  # frase 0 nao termina com ponto: prepara a frase 1
        interest = {0: 1.0, 1: 9.5, 2: 1.0, 3: 1.0}

        plan = plan_long(words, LOUD, interest, models(), target_sec=8.0)

        self.assertEqual(round(plan.segments[0].start, 1), 0.0)  # a preparacao (frase 0) ficou

    def test_retake_first_attempt_is_dropped(self):
        words = phrase_words(3)
        words[2]["word"], words[3]["word"] = " fala0", " coisa0."  # frase 1 repete a frase 0
        regravada = Stub(lambda row: 1.0 if row[RETAKE_SIMILARITY] > 0.9 else 0.0)

        plan = plan_long(words, LOUD, {i: 9.0 for i in range(3)}, models(regravada=regravada), target_sec=600.0)

        self.assertGreaterEqual(plan.segments[0].start, 4.0)  # a primeira tentativa saiu
        self.assertEqual(plan.markers[0][1], "regravada")

    def test_zoom_count_follows_the_learned_rate_with_minimum_gap(self):
        words = phrase_words(20)  # 100 s
        zoom = Stub(lambda row: row[ZOOM_NOTE] / 10)
        interest = {i: (9.0 if i in (3, 4, 12) else 3.0) for i in range(20)}
        params = {"zooms_per_min": 1.2, "zoom_min_gap_s": 6.0, "zoom_duration_p10": 0.6, "zoom_duration_p90": 1.3, "zoom_level_median": 1.5}

        plan = plan_long(words, LOUD, interest, models(zoom=zoom, params=params), target_sec=600.0)

        zoomed = [s for s in plan.segments if s.zoom]
        self.assertEqual(plan.zooms, 2)  # 1,2 por minuto em ~84 s; 3 e 4 estao perto demais
        self.assertTrue(all(s.zoom == 1.5 and 0.6 <= s.end - s.start <= 1.3 + 1e-6 for s in zoomed))
        joined = sorted(plan.segments, key=lambda s: s.start)
        self.assertTrue(all(a.end <= b.start + 1e-6 for a, b in itertools.pairwise(joined)))


    def test_split_target_follows_speech(self):
        # Gravacao pausada no OBS: quem fala mais ganha mais tempo do video final.
        self.assertEqual(split_target([600.0, 300.0, 0.0], 600.0), [400.0, 200.0, 0.0])
        self.assertEqual(split_target([], 600.0), [])


if __name__ == "__main__":
    unittest.main()
