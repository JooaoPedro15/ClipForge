"""Pre-editor que aprende: ensina com projetos do Premiere e edita gravacoes do OBS em XML no molde.

Uso (eventos JSON no stdout, como os outros servicos):
  python preedit_service.py teach-project (--project P ... | --projects-dir PASTA) --store DIR [--model M] [--audio-track 0] [--cpu]
  python preedit_service.py teach-final (--project P ... | --projects-dir PASTA) --videos PASTA --store DIR [--model M] [--cpu]
  python preedit_service.py edit --recording R [--recording R2 ...] [--molde M] --store DIR --minutes 12 [--zoom-style aproximando|seco]
      [--out X] [--audio-track 0] [--cpu]
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
from cortes.xmeml_writer import required_audio_streams
from events import emit
from llm_service import create_default_client
from preedit import finals, models, store
from preedit.audio import AudioError, extract_audio, load_loudness, loudness_cache, resolve_audio_track
from preedit.dataset import build_examples
from preedit.editor import plan_long, split_target
from preedit.interest import load_interest
from preedit.molde import default_molde, load_molde
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


# Um projeto que nao abre (Auto-Save truncado) vai pra lista de falhas e os outros seguem; so e erro se nenhum abrir.
def _read_candidates(projects: list[str]) -> tuple[list[finals.Candidate], list[dict]]:
    candidates, failed = [], []
    for number, project in enumerate(projects):
        emit("status", "processing", "reading-project", f"Projeto [{number + 1}/{len(projects)}] {Path(project).name}", progress=2)
        try:
            sequences = premiere_project.read_video_edits(project)
        except (premiere_project.ProjectError, OSError, EOFError) as error:
            failed.append({"recording": project, "error": f"Nao consegui ler {Path(project).name}: {error}"})
            continue
        modified = Path(project).stat().st_mtime
        candidates += [finals.Candidate(project, sequence, modified) for sequence in sequences]
    if failed and len(failed) == len(projects):
        raise PreeditError(failed[0]["error"])
    return candidates, failed


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
    candidates, failed = _read_candidates(projects)

    emit("status", "processing", "pairing", "Procurando os videos exportados...", progress=4)
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
    store_dir = Path(store_path)
    taught_raw = {os.path.normcase(source["recording"]) for source in store.load_library(store_dir)["sources"] if source.get("kind") == "projeto"}
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
        # Bruto ainda no disco ou ja ensinado: o teach-project ensina essa edicao (com os cortes). Ensinar
        # tambem o video final contaria a mesma edicao duas vezes e enviesaria o "com x sem finais".
        twin = next((source for source in item.sources if os.path.normcase(source) in taught_raw or Path(source).exists()), None)
        if twin:
            skipped.append({"recording": pair.video, "reason": f"bruto disponivel ({Path(twin).name}): ensine com teach-project"})
            continue
        labels.append(item)
        project_of[pair.video] = pair.project

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


def _probe_recordings(recordings: list[str], warnings: list[str]) -> dict[str, Any]:
    """Duracao, tamanho e faixas de cada bruto. A parte que travou (MP4 sem indice, MKV sem duracao) sai com aviso."""
    sources = {}
    for path in recordings:
        try:
            sources[path] = probe_source(path)
        except (RuntimeError, ValueError, KeyError) as error:
            warnings.append(f"{Path(path).name} ficou de fora: nao consegui ler o arquivo ({error}).")
    return sources


def _hear_recordings(
    recordings: list[str], audio_track: int | None, get_model: Callable[[], Any], language: str, beam_size: int, warnings: list[str]
) -> list[tuple[str, list[dict[str, Any]], Any]]:
    """Fala e volume de cada bruto (so o Whisper na GPU). Bruto sem fala (parte que travou, so ruido) sai com aviso."""
    heard = []
    for number, path in enumerate(recordings):
        progress = round(10 + 50 * number / max(1, len(recordings)))
        emit("status", "processing", "transcribing", f"Fala [{number + 1}/{len(recordings)}] {Path(path).name}", progress=progress)
        try:
            track = resolve_audio_track(path, audio_track)
            words, loud = prepare_audio(path, track, get_model, language, beam_size)
        except AudioError as error:
            warnings.append(f"{Path(path).name} ficou de fora: {error}")
            continue
        heard.append((path, words, loud))
    return heard


# Uma gravacao pausada no OBS vira varios arquivos: todos entram numa sequencia so, na ordem do nome
# (o OBS nomeia pela data e hora), e os minutos se dividem pela fala de cada um.
def edit_recordings(
    recordings: list[str],
    molde_path: str | None,
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
    zoom_style: str = "aproximando",
) -> dict[str, Any]:
    if not recordings:
        raise PreeditError("Escolha pelo menos uma gravacao.")
    ordered = sorted(recordings, key=lambda path: Path(path).name.casefold())
    for path in ordered:
        if not Path(path).exists():
            raise PreeditError(f"Gravacao nao encontrada: {path}")
    trained = models.load_models(store.models_dir(Path(store_path), "longo"))
    if trained is None:
        raise PreeditError(f"Ensine pelo menos {models.MIN_RECORDINGS} gravacoes de video longo antes de editar.")
    warnings: list[str] = []
    sources = _probe_recordings(ordered, warnings)
    readable = [path for path in ordered if path in sources]
    if not readable:
        raise PreeditError("Nenhuma gravacao deu pra ler. " + " ".join(warnings))
    try:
        # Sem molde: sequencia simples do tamanho da gravacao (o molde so muda algo com trilhas extras, efeitos ou zoom).
        molde = load_molde(molde_path) if molde_path else default_molde(sources[readable[0]])
    except (TemplateError, OSError) as error:
        raise PreeditError(f"Molde invalido: {error}") from error
    # Antes do Whisper e da IA (que podem levar uma hora): bruto com menos faixas de audio que o molde.
    needed = required_audio_streams(molde.template)
    for path in readable:
        if sources[path].audio_streams < needed:
            raise PreeditError(f"O molde usa a faixa de audio {needed}, mas {Path(path).name} so tem {sources[path].audio_streams}.")

    heard = _hear_recordings(readable, audio_track, whisper_words.model_loader(model_size, device, compute_type), language, beam_size, warnings)
    if not heard:
        raise PreeditError("Nenhuma gravacao tem fala reconhecida. " + " ".join(warnings))

    # Notas da IA depois de todo o Whisper (os dois juntos nao cabem numa placa de 8 GB).
    scored = []
    for number, (path, words, loud) in enumerate(heard):
        emit("status", "processing", "scoring", f"Notas da IA [{number + 1}/{len(heard)}] {Path(path).name}", progress=round(60 + 20 * number / len(heard)))
        phrases = build_phrases(words)
        interest, note = load_interest(path, phrases, "longo", make_client)
        if note and note not in warnings:
            warnings.append(note)
        scored.append((path, words, loud, interest, sum(phrase.duration for phrase in phrases)))

    emit("status", "processing", "planning", "Escolhendo cortes e zooms...", progress=82)
    parts, recordings_report = [], []
    for (path, words, loud, interest, _), target in zip(scored, split_target([item[4] for item in scored], minutes * 60), strict=True):
        plan = plan_long(words, loud, interest, trained, target)
        warnings += [warning for warning in plan.warnings if warning not in warnings]
        if plan.segments:
            parts.append((sources[path], plan))
        recordings_report.append({"path": path, "durationSec": sources[path].duration_sec, "keptSec": plan.duration})
    if not parts:
        raise PreeditError("Nada pra montar: as gravacoes nao tem fala reconhecida.")
    planned_zooms = sum(plan.zooms for _, plan in parts)
    if not molde_path:
        warnings.append("Sem molde: sequencia do tamanho da gravacao e sem zoom (pra ter zoom, use --molde com um video seu que tenha um clipe com zoom).")
    elif molde.zoom is None and planned_zooms:
        warnings.append("O molde nao tem clipe com zoom: o XML saiu sem zoom.")

    emit("status", "processing", "writing", "Montando o XML no molde...", progress=92)
    first = parts[0][0].path
    out = Path(out_path) if out_path else Path(first).with_suffix(".preedicao.longo.xml")
    try:
        write_xml(molde, parts, out, f"{Path(first).stem} pre-edicao", zoom_style)
    except ValueError as error:
        raise PreeditError(str(error)) from error
    return {
        "xmlPath": str(out),
        "durationSec": sum(plan.duration for _, plan in parts),
        "segments": sum(len(plan.segments) for _, plan in parts),
        "zooms": planned_zooms if molde.zoom else 0,
        "recordings": recordings_report,
        "warnings": warnings,
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


# Projetos escolhidos um a um mais todos os .prproj de uma pasta (centenas de caminhos estourariam a linha
# de comando do Windows). O mesmo projeto pelos dois caminhos entra uma vez so.
def project_paths(projects: list[str] | None, projects_dir: str | None) -> list[str]:
    found = list(projects or [])
    if projects_dir:
        found += sorted((str(path) for path in Path(projects_dir).glob("*.prproj")), key=lambda path: Path(path).name.casefold())
    seen: set[str] = set()
    unique = []
    for path in found:
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen:
            seen.add(key)
            unique.append(path)
    if not unique:
        raise PreeditError("Escolha pelo menos um projeto do Premiere.")
    return unique


def _add_projects_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", action="append")
    parser.add_argument("--projects-dir", help="pasta: todos os .prproj dela")


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
    _add_projects_args(teach_parser)
    _add_model_args(teach_parser)

    final_parser = commands.add_parser("teach-final")
    _add_projects_args(final_parser)
    final_parser.add_argument("--videos", required=True, help="pasta com os videos exportados (procura em subpastas)")
    _add_model_args(final_parser)

    edit_parser = commands.add_parser("edit")
    edit_parser.add_argument("--recording", action="append", required=True, help="bruto (repita pra cada arquivo de uma gravacao pausada)")
    edit_parser.add_argument("--zoom-style", choices=("aproximando", "seco"), default="aproximando")
    edit_parser.add_argument("--molde", help="XML de um video seu exportado do Premiere (sem ele: sequencia do tamanho da gravacao, sem zoom)")
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
            result = teach_projects(project_paths(args.project, args.projects_dir), args.store, args.model, args.language, args.beam_size, device, compute_type, args.audio_track)
            emit("done", "completed", "done", f"{len(result['taught'])} gravacoes ensinadas.", progress=100, report=result)
        elif args.command == "teach-final":
            result = teach_finals(project_paths(args.project, args.projects_dir), args.videos, args.store, args.model, args.language, args.beam_size, device, compute_type, args.audio_track)
            emit("done", "completed", "done", f"{len(result['taught'])} videos finais ensinados.", progress=100, report=result)
        elif args.command == "edit":
            result = edit_recordings(
                args.recording,
                args.molde,
                args.store,
                args.minutes,
                args.out,
                args.model,
                args.language,
                args.beam_size,
                device,
                compute_type,
                args.audio_track,
                zoom_style=args.zoom_style,
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
