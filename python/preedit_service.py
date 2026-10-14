"""Pre-editor que aprende: ensina com projetos do Premiere e edita gravacoes do OBS em XML no molde.

Uso (eventos JSON no stdout, como os outros servicos):
  python preedit_service.py teach-project --project P [--project P2] --store DIR [--model M] [--audio-track 0] [--cpu]
  python preedit_service.py edit --recording R --molde M --store DIR --minutes 12 [--out X] [--audio-track 0] [--cpu]
  python preedit_service.py report --store DIR
  python preedit_service.py forget --id ID --store DIR
"""

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import ffmpeg_utils
import premiere_project
import subtitle_service
import whisper_words
from cortes.media import probe_source
from cortes.xmeml_template import TemplateError
from events import emit
from llm_service import create_default_client
from preedit import models, store
from preedit.audio import AudioError, extract_audio, load_loudness, loudness_cache
from preedit.dataset import build_examples
from preedit.editor import plan_long
from preedit.interest import load_interest
from preedit.molde import load_molde
from preedit.phrases import build_phrases
from preedit.project_labels import labels_from_sequences
from preedit.xml_output import write_xml


class PreeditError(Exception):
    """Erro com mensagem pronta pra mostrar ao usuario."""


def words_cache(recording: str, audio_track: int) -> Path:
    return Path(recording).with_suffix(f".words.a{audio_track}.json")


# Palavras, volume e notas da IA da gravacao. Com os caches prontos nao extrai o audio de novo.
def prepare_recording(
    recording: str, audio_track: int, get_model: Callable[[], Any], language: str, beam_size: int, fmt: str, make_client: Callable[[], Any]
) -> tuple[list[dict[str, Any]], Any, dict[int, float], list[str]]:
    words_path = words_cache(recording, audio_track)
    wav = None
    if not (words_path.exists() and loudness_cache(recording, audio_track).exists()):
        digest = hashlib.sha1(recording.encode("utf-8")).hexdigest()[:10]
        wav = extract_audio(recording, audio_track, ffmpeg_utils.resolve_short_temp_dir(Path(recording)) / f"preedit-{digest}.wav")
    try:
        words = whisper_words.load_words(wav or Path(recording), get_model, language, beam_size, cache=words_path)
        loud = load_loudness(recording, audio_track, wav)
    finally:
        if wav is not None:
            wav.unlink(missing_ok=True)
    interest, warning = load_interest(recording, build_phrases(words), fmt, make_client)
    return words, loud, interest, [warning] if warning else []


def _retrain(store_dir: Path, fmt: str) -> dict[str, Any]:
    examples = store.load_examples(store_dir, fmt)
    directory = store.models_dir(store_dir, fmt)
    trained = models.train_format(examples) if examples else None
    if trained is None:
        return {"aviso": "Exemplos insuficientes pra treinar esse formato."}
    report = models.evaluate(examples)
    models.save_models(directory, trained, report)
    return report


def teach_projects(
    projects: list[str],
    store_path: str,
    model_size: str,
    language: str,
    beam_size: int,
    device: str,
    compute_type: str,
    audio_track: int,
    make_client: Callable[[], Any] = create_default_client,
) -> dict[str, Any]:
    store_dir = Path(store_path)
    emit("status", "processing", "reading-project", "Lendo os projetos do Premiere...", progress=2)
    labels = []
    for project in projects:
        try:
            labels.extend(labels_from_sequences(premiere_project.read_video_edits(project)))
        except premiere_project.ProjectError as error:
            raise PreeditError(str(error)) from error
    if not labels:
        raise PreeditError("Nenhuma sequencia desses projetos tem clipes de gravacao pra ensinar.")

    taught_ids = {source["id"] for source in store.load_library(store_dir)["sources"]}
    get_model = whisper_words.model_loader(model_size, device, compute_type)
    taught, skipped, failed, warnings = [], [], [], []
    touched: set[str] = set()
    for number, item in enumerate(labels):
        source = store.source_id(item.recording, item.format)
        if source in taught_ids:
            skipped.append({"recording": item.recording, "reason": "ja ensinada"})
            continue
        if not Path(item.recording).exists():
            skipped.append({"recording": item.recording, "reason": "gravacao nao encontrada"})
            continue
        progress = round(5 + 90 * number / len(labels))
        emit("status", "processing", "teaching", f"[{number + 1}/{len(labels)}] {Path(item.recording).name}", progress=progress)
        try:
            words, loud, interest, notes = prepare_recording(item.recording, audio_track, get_model, language, beam_size, item.format, make_client)
            examples = build_examples(item, words, loud, interest)
        except AudioError as error:
            failed.append({"recording": item.recording, "error": str(error)})
            continue
        warnings.extend(note for note in notes if note not in warnings)
        entry = {
            "id": source,
            "kind": "projeto",
            "format": item.format,
            "recording": item.recording,
            "sequences": item.sequences,
            "phrases": len(examples["phrase"]),
            "zooms": examples["stats"]["zooms"],
            "taughtAt": int(time.time()),
        }
        store.save_source(store_dir, entry, examples)
        taught.append({key: entry[key] for key in ("recording", "format", "sequences", "phrases", "zooms")})
        touched.add(item.format)

    emit("status", "processing", "training", "Treinando os modelos...", progress=96)
    trained = {fmt: _retrain(store_dir, fmt) for fmt in sorted(touched)}
    return {"taught": taught, "skipped": skipped, "failed": failed, "models": trained, "warnings": warnings}


def edit_recording(
    recording: str,
    molde_path: str,
    store_path: str,
    minutes: float,
    out_path: str | None,
    model_size: str,
    language: str,
    beam_size: int,
    device: str,
    compute_type: str,
    audio_track: int,
    make_client: Callable[[], Any] = create_default_client,
) -> dict[str, Any]:
    if not Path(recording).exists():
        raise PreeditError(f"Gravacao nao encontrada: {recording}")
    trained = models.load_models(store.models_dir(Path(store_path), "longo"))
    if trained is None:
        raise PreeditError(f"Ensine pelo menos {models.MIN_RECORDINGS} gravacoes de video longo antes de editar.")
    try:
        molde = load_molde(molde_path)
    except (TemplateError, OSError) as error:
        raise PreeditError(f"Molde invalido: {error}") from error

    emit("status", "processing", "transcribing", "Lendo a gravacao (fala, volume e notas da IA)...", progress=10)
    get_model = whisper_words.model_loader(model_size, device, compute_type)
    try:
        words, loud, interest, warnings = prepare_recording(recording, audio_track, get_model, language, beam_size, "longo", make_client)
    except AudioError as error:
        raise PreeditError(str(error)) from error

    emit("status", "processing", "planning", "Escolhendo cortes e zooms...", progress=80)
    plan = plan_long(words, loud, interest, trained, minutes * 60)
    if not plan.segments:
        raise PreeditError("Nada pra montar: a gravacao nao tem fala reconhecida.")
    if molde.zoom is None and plan.zooms:
        warnings.append("O molde nao tem clipe com zoom: o XML saiu sem zoom.")

    emit("status", "processing", "writing", "Montando o XML no molde...", progress=92)
    out = Path(out_path) if out_path else Path(recording).with_suffix(".preedicao.longo.xml")
    write_xml(molde, probe_source(recording), plan, out, f"{Path(recording).stem} pre-edicao")
    return {
        "xmlPath": str(out),
        "durationSec": plan.duration,
        "segments": len(plan.segments),
        "zooms": plan.zooms if molde.zoom else 0,
        "warnings": warnings + plan.warnings,
    }


def report(store_path: str) -> dict[str, Any]:
    store_dir = Path(store_path)
    result: dict[str, Any] = {"sources": store.load_library(store_dir)["sources"], "models": {}}
    for fmt in ("longo", "short"):
        directory = store.models_dir(store_dir, fmt)
        if (directory / "params.json").exists():
            result["models"][fmt] = {
                "params": json.loads((directory / "params.json").read_text(encoding="utf-8")),
                "report": json.loads((directory / "report.json").read_text(encoding="utf-8")),
            }
    return result


def forget(source: str, store_path: str) -> dict[str, Any]:
    store_dir = Path(store_path)
    fmt = store.remove_source(store_dir, source)
    if fmt is None:
        raise PreeditError("Fonte nao encontrada na biblioteca do Pre-editor.")
    _retrain(store_dir, fmt)
    return {"id": source, "format": fmt}


def _add_model_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--store", required=True)
    parser.add_argument("--model", default=subtitle_service.DEFAULT_MODEL)
    parser.add_argument("--language", default=subtitle_service.DEFAULT_LANGUAGE)
    parser.add_argument("--beam-size", type=int, default=subtitle_service.DEFAULT_BEAM_SIZE)
    parser.add_argument("--audio-track", type=int, default=0, help="faixa de audio da voz (0 = primeira)")
    parser.add_argument("--cpu", action="store_true")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pre-editor que aprende")
    commands = parser.add_subparsers(dest="command", required=True)

    teach_parser = commands.add_parser("teach-project")
    teach_parser.add_argument("--project", action="append", required=True)
    _add_model_args(teach_parser)

    edit_parser = commands.add_parser("edit")
    edit_parser.add_argument("--recording", required=True)
    edit_parser.add_argument("--molde", required=True)
    edit_parser.add_argument("--minutes", type=float, required=True)
    edit_parser.add_argument("--out")
    _add_model_args(edit_parser)

    report_parser = commands.add_parser("report")
    report_parser.add_argument("--store", required=True)

    forget_parser = commands.add_parser("forget")
    forget_parser.add_argument("--id", required=True)
    forget_parser.add_argument("--store", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    device = "cpu" if getattr(args, "cpu", False) else "cuda"
    compute_type = "int8" if getattr(args, "cpu", False) else "float16"
    try:
        if args.command == "teach-project":
            result = teach_projects(args.project, args.store, args.model, args.language, args.beam_size, device, compute_type, args.audio_track)
            emit("done", "completed", "done", f"{len(result['taught'])} gravacoes ensinadas.", progress=100, report=result)
        elif args.command == "edit":
            result = edit_recording(
                args.recording, args.molde, args.store, args.minutes, args.out, args.model, args.language, args.beam_size, device, compute_type, args.audio_track
            )
            emit("done", "completed", "done", "Pre-edicao pronta.", progress=100, report=result)
        elif args.command == "report":
            emit("done", "completed", "done", "Biblioteca do Pre-editor.", progress=100, report=report(args.store))
        else:
            emit("done", "completed", "done", "Fonte removida e modelos retreinados.", progress=100, report=forget(args.id, args.store))
        return 0
    except PreeditError as error:
        emit("error", "error", "preedit", str(error), error=str(error))
        return 1
    except ImportError as error:
        message = "Dependencia Python faltando (faster-whisper ou scikit-learn). Rode: pip install -r python/requirements.txt"
        emit("error", "error", "bootstrap", message, error=str(error))
        return 1
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        emit("error", "error", "runtime", "Falha no Pre-editor.", error=str(error))
        return 1


if __name__ == "__main__":
    exit_code = main()
    # O resultado ja foi enviado: sai sem rodar os destrutores (o do Whisper na GPU pode travar o processo).
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
