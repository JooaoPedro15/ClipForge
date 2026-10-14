import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from preedit import audio


def write_wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(audio.SAMPLE_RATE)
        handle.writeframes(samples.astype(np.int16).tobytes())


def tone(seconds: float, amplitude: float) -> np.ndarray:
    t = np.arange(int(seconds * audio.SAMPLE_RATE)) / audio.SAMPLE_RATE
    return (np.sin(2 * np.pi * 220 * t) * amplitude * 32767).astype(np.int16)


class LoudnessTest(unittest.TestCase):
    def test_tone_and_silence(self):
        samples = np.concatenate([np.zeros(audio.SAMPLE_RATE, dtype=np.int16), tone(1.0, 0.5)])

        loud = audio.loudness_from_samples(samples)

        self.assertEqual(len(loud.db), 20)
        self.assertEqual(loud.db[0], audio.SILENCE_DB)
        self.assertAlmostEqual(loud.db[15], -9.0, delta=0.5)  # seno de amplitude 0,5: RMS ~ -9 dB
        mean, peak = loud.stats(1.0, 2.0)
        self.assertAlmostEqual(peak, -9.0, delta=0.5)
        self.assertEqual(loud.stats(0.0, 1.0), (audio.SILENCE_DB, audio.SILENCE_DB))
        self.assertAlmostEqual(mean, peak, delta=0.2)

    def test_cache_is_written_once_per_track(self):
        with tempfile.TemporaryDirectory() as tmp:
            recording = str(Path(tmp) / "gravacao.mp4")
            wav = Path(tmp) / "voz.wav"
            write_wav(wav, tone(0.5, 0.25))

            first = audio.load_loudness(recording, 1, wav)
            wav.unlink()
            second = audio.load_loudness(recording, 1, None)

            self.assertEqual(first.db, second.db)
            self.assertTrue((Path(tmp) / "gravacao.loudness.a1.json").exists())

    def test_without_cache_or_wav(self):
        with self.assertRaises(audio.AudioError):
            audio.load_loudness(r"C:\nao\existe.mp4", 0, None)


if __name__ == "__main__":
    unittest.main()
