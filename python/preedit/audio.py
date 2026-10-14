"""Audio da gravacao: extrai a faixa de voz em wav 16 kHz mono e mede o volume em janelas de 100 ms."""

import json
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import ffmpeg_utils
import numpy as np

SAMPLE_RATE = 16000
WINDOW_SEC = 0.1
SILENCE_DB = -90.0


class AudioError(Exception):
    """Erro com mensagem pronta pra mostrar ao usuario."""


@dataclass
class Loudness:
    window: float
    # Volume (dB, 0 = maximo) de cada janela, a partir do inicio da gravacao.
    db: list[float]

    @property
    def median(self) -> float:
        return float(np.median(self.db)) if self.db else SILENCE_DB

    def stats(self, start: float, end: float) -> tuple[float, float]:
        first = max(0, int(start / self.window))
        last = max(first + 1, int(np.ceil(end / self.window)))
        chunk = self.db[first:last]
        if not chunk:
            return SILENCE_DB, SILENCE_DB
        return float(np.mean(chunk)), float(np.max(chunk))


def loudness_from_samples(samples: np.ndarray, sample_rate: int = SAMPLE_RATE, window: float = WINDOW_SEC) -> Loudness:
    size = max(1, int(sample_rate * window))
    count = len(samples) // size
    if count == 0:
        return Loudness(window, [])
    frames = samples[: count * size].astype(np.float64).reshape(count, size) / 32768.0
    rms = np.sqrt(np.mean(frames**2, axis=1))
    db = np.maximum(20 * np.log10(np.maximum(rms, 1e-12)), SILENCE_DB)
    return Loudness(window, [round(float(value), 2) for value in db])


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        return np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)


# Faixa N do arquivo (0 = primeira) em wav mono 16 kHz: o Whisper e o volume leem dele.
def extract_audio(recording: str, audio_track: int, out_wav: Path) -> Path:
    command = [
        ffmpeg_utils.resolve_ffmpeg_path(),
        "-y",
        "-v",
        "error",
        "-i",
        recording,
        "-map",
        f"0:a:{audio_track}",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
        str(out_wav),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        detail = result.stderr.strip()[-200:]
        raise AudioError(f"Nao deu pra ler a faixa de audio {audio_track + 1} de {Path(recording).name}: {detail}")
    return out_wav


def loudness_cache(recording: str, audio_track: int) -> Path:
    return Path(recording).with_suffix(f".loudness.a{audio_track}.json")


def load_loudness(recording: str, audio_track: int, wav: Path | None) -> Loudness:
    cache = loudness_cache(recording, audio_track)
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        return Loudness(float(data["window"]), [float(value) for value in data["db"]])
    if wav is None or not wav.exists():
        raise AudioError(f"Sem audio extraido de {Path(recording).name} pra medir o volume.")
    loud = loudness_from_samples(_read_wav(wav))
    cache.write_text(json.dumps({"window": loud.window, "db": loud.db}), encoding="utf-8")
    return loud
