"""Pre-editor que aprende: ensina com projetos do Premiere e edita gravacoes do OBS em XML no molde.

Uso (eventos JSON no stdout, como os outros servicos):
  python preedit_service.py teach-project --project P [--project P2] --store DIR [--model M] [--audio-track 0] [--cpu]
  python preedit_service.py teach-final --project P [--project P2] --videos PASTA --store DIR [--model M] [--cpu]
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
from preedit import finals, models, store
from preedit.audio import AudioError, extract_audio, load_loudness, loudness_cache, resolve_audio_track
from preedit.dataset import build_examples
from preedit.editor import plan_long
from preedit.interest import load_interest
from preedit.molde import load_molde
from preedit.phrases import build_phrases
from preedit.project_labels import collect_labels, final_labels
from preedit.types import RecordingLabels
from preedit.xml_output import write_xml


class PreeditError(Exception):
    """Erro com mensagem pronta pra mostrar ao usuario."""


def words_cache(recording: str, audio_track: int) -> Path:
    return Path(recording).with_suffix(f".words.a{audio_track}.json")


# Palavras e volume da gravacao (so o Whisper usa a GPU). Com os caches prontos nao extrai o audio de novo.
def prepare_audio(
    recording: str, audio_track: int, get_model: Callable[[], Any], language: str, beam_size: int
) -> tuple[list[dict[str, Any]], Any]:
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
    if not words:
        raise AudioError(
            f"Sem fala reconhecida na faixa {audio_track + 1} de {Path(recording).name}: "
            "escolha a faixa do microfone com --audio-track (0 = primeira faixa)."
        )
    return words, loud


def prepare_recording(
    recording: str, audio_track: int, get_model: Callable[[], Any], language: str, beam_size: int, fmt: str, make_client: Callable[[], Any]
) -> tuple[list[dict[str, Any]], Any, dict[int, float], list[str]]:
    words, loud = prepare_audio(recording, audio_track, get_model, language, beam_size)
    interest, warning = load_interest(recording, build_phrases(words), fmt, make_client)
    return words, loud, interest, [warning] if warning else []


def _failure_message(error: Exception) -> str:
    text = str(error)
    if "out of memory" in text.lower():
        return "Placa de video sem memoria: feche outros programas que usam a GPU e ensine de novo (o que ja foi ensinado fica salvo)."
    return text


def labels_hash(labels: RecordingLabels) -> str:
    """Muda quando o usuario mexe na edicao dessa gravacao no projeto (ai ela e ensinada de novo)."""
    payload = json.dumps([[r.start, r.end] for r in labels.kept] + [[z.start, z.end, z.level] for z in labels.zooms])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def _retrain(store_dir: Path, fmt: str) -> dict[str, Any]:
    examples = store.load_examples(store_dir, fmt)
    trained = models.train_format(examples) if examples else None
    if trained is None:
        # So videos finais (ou nada): o editor nao treina, mas o que der pra medir aparece.
        report = models.evaluate(examples) if examples else {}
        report["aviso"] = "Exemplos insuficientes pra treinar esse formato (o editor precisa de gravacoes com bruto)."
        return report
    report = models.evaluate(examples)
    models.save_models(store.models_dir(store_dir, fmt), trained, report)
    return report


def _teach_labels(
    labels: list[RecordingLabels],
    store_dir: Path,
    get_model: Callable[[], Any],
    language: str,
    beam_size: int,
    audio_track: int | None,
    make_client: Callable[[], Any],
    entry_extra: Callable[[RecordingLabels], dict[str, Any]],
    prefer_mic: bool = True,
) -> tuple[list[dict], list[dict], list[dict], list[str], set[str]]:
    """Ensina os gabaritos e devolve taught, skipped, failed, warnings e os formatos tocados."""
    known = {source["id"]: source for source in store.load_library(store_dir)["sources"]}
    taught, skipped, failed, warnings = [], [], [], []
    touched: set[str] = set()
    pending = []
    for item in labels:
        previous = known.get(store.source_id(item.recording, item.format))
        # Ja ensinada so pula se a edicao no projeto e a mesma e as notas da IA vieram de verdade.
        if previous and previous.get("labelsHash") == labels_hash(item) and not previous.get("semIa"):
            skipped.append({"recording": item.recording, "reason": "ja ensinada"})
        elif not Path(item.recording).exists():
            skipped.append({"recording": item.recording, "reason": "gravacao nao encontrada"})
        else:
            pending.append(item)

    # Fase 1: fala e volume de todas (so o Whisper na GPU). Fase 2: notas da IA (so o Ollama na GPU).
    # Alternar os dois por gravacao estoura a memoria de uma placa de 8 GB (o Ollama segura o modelo carregado).
    # Uma gravacao que falha vai pra lista de falhas e o lote segue com as outras.
    prepared = []
    for number, item in enumerate(pending):
        progress = round(5 + 60 * number / max(1, len(pending)))
        emit("status", "processing", "transcribing", f"Fala [{number + 1}/{len(pending)}] {Path(item.recording).name}", progress=progress)
        try:
            track = resolve_audio_track(item.recording, audio_track, prefer_mic)
            words, loud = prepare_audio(item.recording, track, get_model, language, beam_size)
        except ImportError:
            raise
        except Exception as error:
            failed.append({"recording": item.recording, "error": _failure_message(error)})
            continue
        prepared.append((item, words, loud))

    for number, (item, words, loud) in enumerate(prepared):
        progress = round(65 + 30 * number / max(1, len(prepared)))
        emit("status", "processing", "scoring", f"Notas da IA [{number + 1}/{len(prepared)}] {Path(item.recording).name}", progress=progress)
        try:
            interest, note = load_interest(item.recording, build_phrases(words), item.format, make_client)
            examples = build_examples(item, words, loud, interest)
        except ImportError:
            raise
        except Exception as error:
            failed.append({"recording": item.recording, "error": _failure_message(error)})
            continue
        if note and note not in warnings:
            warnings.append(note)
        entry = {
            "id": store.source_id(item.recording, item.format),
            **entry_extra(item),
            "format": item.format,
            "recording": item.recording,
            "sequences": item.sequences,
            "phrases": len(examples["phrase"]),
            "zooms": examples["stats"]["zooms"],
            "labelsHash": labels_hash(item),
            "semIa": bool(note),
            "taughtAt": int(time.time()),
        }
        store.save_source(store_dir, entry, examples)
        taught.append({key: entry[key] for key in ("recording", "format", "sequences", "phrases", "zooms")})
        touched.add(item.format)
    return taught, skipped, failed, warnings, touched


def teach_projects(
    projects: list[str],
    store_path: str,
    model_size: str,
    language: str,
    beam_size: int,
    device: str,
    compute_type: str,
    audio_track: int | None,
    make_client: Callable[[], Any] = create_default_client,
) -> dict[str, Any]:
    store_dir = Path(store_path)
    emit("status", "processing", "reading-project", "Lendo os projetos do Premiere...", progress=2)
    labels = []
    ignored: list[dict[str, str]] = []
    for project in projects:
        try:
            found, left_out = collect_labels(premiere_project.read_video_edits(project))
        except premiere_project.ProjectError as error:
            raise PreeditError(str(error)) from error
        labels.extend(found)
        ignored.extend(item for item in left_out if item not in ignored)
    if not labels:
        raise PreeditError("Nenhuma sequencia desses projetos tem clipes de gravacao (com cortes) pra ensinar.")

    get_model = whisper_words.model_loader(model_size, device, compute_type)
    taught, skipped, failed, warnings, touched = _teach_labels(
        labels, store_dir, get_model, language, beam_size, audio_track, make_client, entry_extra=lambda item: {"kind": "projeto"}
    )
    emit("status", "processing", "training", "Treinando os modelos...", progress=96)
    trained = {fmt: _retrain(store_dir, fmt) for fmt in sorted(touched)}
    return {"taught": taught, "skipped": ignored + skipped, "failed": failed, "models": trained, "warnings": warnings}


def _read_candidates(projects: list[str]) -> list[finals.Candidate]:
    candidates = []
    for project in projects:
        try:
            sequences = premiere_project.read_video_edits(project)
        except (premiere_project.ProjectError, OSError, EOFError) as error:
            raise PreeditError(f"Nao consegui ler {Path(project).name}: {error}") from error
        modified = Path(project).stat().st_mtime
        candidates += [finals.Candidate(project, sequence, modified) for sequence in sequences]
    return candidates


# Ensina zoom com projetos antigos (bruto offline) e os videos que as sequencias exportaram.
def teach_finals(
    projects: list[str],
    videos_dir: str,
    store_path: str,
    model_size: str,
    language: str,
    beam_size: int,
    device: str,
    compute_type: str,
    audio_track: int | None,
    make_client: Callable[[], Any] = create_default_client,
) -> dict[str, Any]:
    folder = Path(videos_dir)
    files = finals.scan_videos(folder) if folder.is_dir() else {}
    if not files:
        raise PreeditError(f"Nenhum video (.mp4, .mov, .mkv) em {videos_dir}.")
    emit("status", "processing", "reading-project", "Lendo os projetos do Premiere...", progress=2)
    candidates = _read_candidates(projects)

    emit("status", "processing", "pairing", "Procurando os videos exportados...", progress=4)
    failed: list[dict] = []
    measured: dict[str, float] = {}

    def duration_of(path: str) -> float:
        if path not in measured:
            try:
                measured[path] = probe_source(path).duration_sec
            except (RuntimeError, ValueError, KeyError) as error:
                failed.append({"recording": path, "error": str(error)})
                measured[path] = -1.0
        return measured[path]

    pairs, skipped, unpaired = finals.pair_videos(candidates, files, duration_of)
    labels, project_of, pair_rows = [], {}, []
    for pair in pairs:
        item = final_labels(pair.sequence, pair.video, pair.start, pair.end)
        pair_rows.append(
            {
                "project": pair.project,
                "sequence": pair.sequence.name,
                "video": pair.video,
                "start": pair.start,
                "end": pair.end,
                "format": "short" if pair.sequence.vertical else "longo",
                "zooms": len(item.zooms) if item else 0,
            }
        )
        if item is None:
            skipped.append({"recording": pair.video, "reason": f"sem zoom ({pair.sequence.name})"})
            continue
        labels.append(item)
        project_of[pair.video] = pair.project

    store_dir = Path(store_path)
    get_model = whisper_words.model_loader(model_size, device, compute_type)
    taught, more_skipped, more_failed, warnings, touched = _teach_labels(
        labels,
        store_dir,
        get_model,
        language,
        beam_size,
        audio_track,
        make_client,
        entry_extra=lambda item: {"kind": "final", "project": project_of[item.recording]},
        prefer_mic=False,
    )
    emit("status", "processing", "training", "Treinando os modelos...", progress=96)
    trained = {fmt: _retrain(store_dir, fmt) for fmt in sorted(touched)}
    return {
        "pairs": pair_rows,
        "unpairedSequences": unpaired,
        "taught": taught,
        "skipped": skipped + more_skipped,
        "failed": failed + more_failed,
        "models": trained,
        "warnings": warnings,
    }


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
    audio_track: int | None,
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
        track = resolve_audio_track(recording, audio_track)
        words, loud, interest, warnings = prepare_recording(recording, track, get_model, language, beam_size, "longo", make_client)
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
    parser.add_argument("--audio-track", type=int, default=None, help="faixa de audio da voz (0 = primeira; padrao: a 2, do microfone)")
    parser.add_argument("--cpu", action="store_true")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pre-editor que aprende")
    commands = parser.add_subparsers(dest="command", required=True)

    teach_parser = commands.add_parser("teach-project")
    teach_parser.add_argument("--project", action="append", required=True)
    _add_model_args(teach_parser)

    final_parser = commands.add_parser("teach-final")
    final_parser.add_argument("--project", action="append", required=True)
    final_parser.add_argument("--videos", required=True, help="pasta com os videos exportados (procura em subpastas)")
    _add_model_args(final_parser)

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
        elif args.command == "teach-final":
            result = teach_finals(args.project, args.videos, args.store, args.model, args.language, args.beam_size, device, compute_type, args.audio_track)
            emit("done", "completed", "done", f"{len(result['taught'])} videos finais ensinados.", progress=100, report=result)
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
