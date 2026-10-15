import random
import tempfile
import unittest
from pathlib import Path

from preedit import models
from preedit.features import PAUSE_FEATURES, PHRASE_FEATURES, RETAKE_FEATURES, ZOOM_FEATURES


def synthetic_recording(seed: int) -> dict:
    """Gravacao falsa: fica a frase com nota da IA > 5; zoom quando o pico passa de 10 dB."""
    rng = random.Random(seed)
    phrase, zoom, pause, retake = [], [], [], []
    for _ in range(80):
        x = [rng.uniform(0, 10) for _ in PHRASE_FEATURES]
        phrase.append({"x": x, "y": int(x[5] > 5)})
        z = [rng.uniform(0, 20) for _ in ZOOM_FEATURES]
        zoom.append({"x": z, "y": int(z[0] > 10), "level": 1.5 if z[0] > 10 else None})
        p = [rng.uniform(0, 1500) for _ in PAUSE_FEATURES]
        pause.append({"x": p, "y": min(p[0], 300.0)})
        r = [rng.uniform(0, 1) for _ in RETAKE_FEATURES]
        retake.append({"x": r, "y": int(r[0] > 0.8)})
    return {
        "recording": f"gravacao{seed}.mp4",
        "format": "longo",
        "phrase": phrase,
        "retake": retake,
        "pause": pause,
        "zoom": zoom,
        "stats": {"final_sec": 600.0, "zooms": 30, "zoom_durations": [0.6, 0.9, 1.3], "zoom_levels": [1.4, 1.5, 1.7], "zoom_gaps": [8.0, 12.0, 20.0]},
    }


class ModelsTest(unittest.TestCase):
    def test_trains_learns_the_rule_and_reports_against_the_baseline(self):
        examples = [synthetic_recording(seed) for seed in range(4)]

        trained = models.train_format(examples)
        report = models.evaluate(examples)

        self.assertIsNotNone(trained.zoom)
        self.assertEqual(trained.params["recordings"], 4)
        self.assertAlmostEqual(trained.params["zooms_per_min"], 3.0)
        self.assertEqual(trained.params["zoom_level_median"], 1.5)
        self.assertGreater(report["trecho_f1"], 0.9)
        self.assertGreater(report["trecho_f1"], report["trecho_f1_referencia"])
        self.assertLess(report["pausa_erro_ms"], report["pausa_erro_ms_referencia"])
        self.assertEqual(report["zoom_f1_referencia"], 0.0)

    def test_report_says_how_well_the_weakest_phrases_are_ranked(self):
        examples = [synthetic_recording(seed) for seed in range(4)]
        all_kept = [{**example, "phrase": [{**row, "y": 1} for row in example["phrase"]]} for example in examples]

        report = models.evaluate(examples)

        self.assertGreater(report["trecho_ordem"], 0.9)
        self.assertEqual(report["trecho_ordem_referencia"], 0.5)
        self.assertIsNone(models.evaluate(all_kept)["trecho_ordem"])

    def test_save_load_needs_three_recordings(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "longo"
            two = models.train_format([synthetic_recording(1), synthetic_recording(2)])
            models.save_models(directory, two, {})
            self.assertIsNone(models.load_models(directory))

            three = models.train_format([synthetic_recording(seed) for seed in range(3)])
            models.save_models(directory, three, {"trecho_f1": 1.0})
            loaded = models.load_models(directory)

            self.assertIsNotNone(loaded)
            row = synthetic_recording(9)["phrase"][0]["x"]
            self.assertEqual(models.probabilities(loaded.trecho, [row]), models.probabilities(three.trecho, [row]))
            self.assertIn("nota_ia", (directory / "tree_trecho.txt").read_text(encoding="utf-8"))

    def test_recordings_without_rows_do_not_count(self):
        empty = {**synthetic_recording(5), "phrase": [], "zoom": [], "pause": [], "retake": []}

        trained = models.train_format([synthetic_recording(1), synthetic_recording(2), empty])

        self.assertEqual(trained.params["recordings"], 2)

    def test_evaluate_with_few_recordings_and_empty_rows(self):
        self.assertIn("aviso", models.evaluate([synthetic_recording(1)]))
        self.assertEqual(models.probabilities(None, []), [])
        self.assertIsNone(models.train_format([{**synthetic_recording(1), "phrase": []}]))


if __name__ == "__main__":
    unittest.main()
