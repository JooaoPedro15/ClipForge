"""Teste de caracterizacao do main() do Pre-Editor.

Troca por versoes falsas o que toca o mundo externo (engine do Clip-Splitter,
ffprobe, extracao de audio, deteccao de silencio, exportacao) e trava o que o
main orquestra: eventos, trechos mantidos, arquivo de debug e limpeza.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import clip_splitter_service as service

SEGMENTS = [
    {"start": 0.0, "end": 4.0, "text": "eu fui la e"},
    {"start": 6.0, "end": 9.0, "text": "voltei depois."},
    {"start": 12.5, "end": 19.0, "text": "e acabou"},
]
AUDIO_PAUSES = [
    {"start": 4.0, "end": 6.0, "duration": 2.0, "source": "audio"},
    {"start": 9.0, "end": 12.5, "duration": 3.5, "source": "audio"},
]
STREAMS = [{"stream_index": 1, "audio_index": 0, "title": "jogo"}, {"stream_index": 2, "audio_index": 1, "title": "mic"}]
SILENCE_KEEP_RANGES = [
    {"start": 0.0, "end": 4.225},
    {"start": 5.725, "end": 9.113},
    {"start": 12.363, "end": 19.18},
    {"start": 19.78, "end": 20.0},
]
PIPELINE_STAGES = [
    ("status", "bootstrap", 5, "Carregando engine do Clip-Splitter..."),
    ("status", "probing", 10, "Lendo duracao do video..."),
    ("status", "extracting-audio", 18, "Extraindo audio de analise da faixa 1/1..."),
    ("status", "transcribing", 34, "Transcrevendo audio com Whisper..."),
]


class Run:
    def __init__(self, code: int, events: list[dict], keep_ranges, audio_left, debug_files: list[str]):
        self.code = code
        self.events = events
        self.keep_ranges = keep_ranges
        self.audio_left = audio_left
        self.debug_files = debug_files

    def stages(self) -> list[tuple]:
        return [(event["event"], event["stage"], event.get("progress"), event["message"]) for event in self.events]


def run_main(extra_args: list[str], output_streams: int = 2, engine_error: str | None = None) -> Run:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        video = tmp_path / "live.mp4"
        video.write_bytes(b"fake")
        seen: dict = {}
        engine = types.SimpleNamespace(
            FFMPEG="ffmpeg",
            FFPROBE="ffprobe",
            WHISPER_DEVICE="cuda",
            WHISPER_COMPUTE="float16",
            get_duracao=lambda path: 20.0,
            transcrever=lambda audio_path: SEGMENTS,
        )

        def load_engine(root):
            if engine_error:
                raise RuntimeError(engine_error)
            return engine

        probes = iter([STREAMS, STREAMS[:output_streams]])

        def extract(module, video_path, temp_dir, index):
            audio = Path(temp_dir) / "audio_temp.wav"
            audio.write_bytes(b"wav")
            seen["audio"] = audio
            return str(audio)

        def export(module, video_path, output_file, keep_ranges, audio_stream_count, filter_script_path=None):
            seen["keep_ranges"] = keep_ranges
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_bytes(b"mp4")

        stdout = io.StringIO()
        with (
            mock.patch.dict(os.environ, {"CLIPFORGE_TEMP": str(tmp_path / "temp")}),
            mock.patch.object(sys, "argv", ["clip_splitter_service.py", str(video), *extra_args]),
            mock.patch.object(service, "resolve_clip_splitter_root", lambda root: tmp_path),
            mock.patch.object(service, "load_clip_splitter_module", load_engine),
            mock.patch.object(service, "probe_audio_streams", lambda module, path: next(probes)),
            mock.patch.object(service, "extract_analysis_audio_track", extract),
            mock.patch.object(service, "detect_audio_silence_ranges", lambda *args: AUDIO_PAUSES),
            mock.patch.object(service, "export_preedited_video", export),
            contextlib.redirect_stdout(stdout),
        ):
            code = service.main()

        events = []
        for line in stdout.getvalue().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue  # linhas de log livre ([debug], "Audio: ...")
            events.append(json.loads(json.dumps(event).replace(json.dumps(str(tmp_path))[1:-1], "<tmp>")))
        audio = seen.get("audio")
        return Run(
            code,
            events,
            seen.get("keep_ranges"),
            audio.exists() if audio else None,
            sorted(path.name for path in tmp_path.rglob("*.debug.json")),
        )


class PreEditorMainFlowTest(unittest.TestCase):
    def test_silence_mode_with_debug_json(self):
        run = run_main(["--write-debug-json"])

        self.assertEqual(run.code, 0)
        self.assertEqual(
            run.stages(),
            [
                *PIPELINE_STAGES,
                ("status", "planning", 56, "3 pausas analisadas para pre-edicao."),
                ("status", "planning-done", 70, "Video unico planejado para pre-edicao."),
                ("status", "exporting", 82, "Exportando video limpo unico..."),
                ("done", "done", 100, "Pre-edicao exportada com sucesso; 2 faixa(s) de audio preservada(s)."),
            ],
        )
        self.assertEqual(run.keep_ranges, SILENCE_KEEP_RANGES)
        self.assertEqual(run.debug_files, ["live_preedit.debug.json"])
        self.assertFalse(run.audio_left)

        done = run.events[-1]
        self.assertEqual(done["outputDir"], "<tmp>\\live_preedit" if os.name == "nt" else "<tmp>/live_preedit")
        self.assertEqual((done["totalClips"], done["clipsCreated"], done["sourceDurationSec"]), (1, 1, 20.0))
        clip = {key: value for key, value in done["clips"][0].items() if key not in ("clipId", "filePath")}
        self.assertEqual(
            clip,
            {
                "index": 1,
                "fileName": "live_preedit.mp4",
                "startSec": 0.0,
                "endSec": 14.65,
                "durationSec": 14.65,
                "reason": "Pre-edicao unica com 3 pausa(s) analisada(s); 5.3s removidos.",
                "transcriptSnippet": "Video limpo em ordem original para revisao manual.",
            },
        )

    def test_fixed_mode_keeps_the_whole_video(self):
        run = run_main(["--mode", "fixed"])

        self.assertEqual(run.code, 0)
        self.assertEqual(run.keep_ranges, [{"start": 0.0, "end": 20.0}])
        self.assertEqual(run.stages()[4], ("status", "planning", 56, "0 pausas analisadas para pre-edicao."))
        self.assertEqual(run.debug_files, [])
        self.assertIsNone(run.events[-1]["debugPath"])

    def test_lost_audio_track_is_reported_as_error(self):
        run = run_main([], output_streams=1)

        self.assertEqual(run.code, 1)
        error = run.events[-1]
        self.assertEqual((error["event"], error["stage"], error["message"]), ("error", "processing", "Falha ao processar o Pre-Editor."))
        self.assertEqual(error["error"], "Possivel downmix acidental: entrada tinha 2 faixa(s) de audio, saida preservou 1.")
        # Comportamento atual: o audio temporario fica pra tras quando o job falha.
        self.assertTrue(run.audio_left)

    def test_engine_failure_stops_at_bootstrap(self):
        run = run_main([], engine_error="sem clip_splitter.py")

        self.assertEqual(run.code, 1)
        self.assertEqual(
            run.events,
            [
                {"event": "status", "status": "preparing", "stage": "bootstrap", "message": "Carregando engine do Clip-Splitter...", "progress": 5},
                {"event": "error", "status": "error", "stage": "bootstrap", "message": "Falha ao carregar engine do Clip-Splitter.", "error": "sem clip_splitter.py"},
            ],
        )

    def test_missing_input_file(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", ["clip_splitter_service.py", "Z:\\nao\\existe.mp4"]), contextlib.redirect_stdout(stdout):
            code = service.main()

        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout.getvalue())["stage"], "input")


if __name__ == "__main__":
    unittest.main()
