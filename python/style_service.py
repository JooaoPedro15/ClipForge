"""Ensina o estilo de legenda do usuario a partir de um video corrigido no Premiere.

Uso (chamado pelo Electron, eventos JSON no stdout):
  python style_service.py learn --original V --srt S --final F --store DIR [--model M] [--language pt] [--cpu]
  python style_service.py learn --original V --srt PROJETO.prproj --sequence NOME --final F --store DIR
  python style_service.py scan-project --project PROJETO.prproj [--originals PASTA_OU_MP3 ...]
  python style_service.py learn-project --project PROJETO.prproj [--originals ...] [--finals ...] [--only NOME] --store DIR
  python style_service.py forget --id ID --store DIR
"""

import argparse
import difflib
import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import premiere_project
import segmentation
import style_alignment
import style_features
import style_model
import style_store
import subtitle_service
from events import emit
from text_utils import normalize_token

# Com menos espacos rotulados que isso, o video ensina pouco sobre quebras.
MIN_GAP_EXAMPLES = 30


class StyleError(Exception):
    """Erro com mensagem pronta pra mostrar ao usuario."""


def transcribe_words(model: Any, media_path: str, language: str, beam_size: int) -> list[dict[str, Any]]:
    segments, _info = subtitle_service.run_whisper(model, media_path, language, beam_size)
    words: list[dict[str, Any]] = []
    for segment_index, segment in enumerate(segments):
        words.extend(subtitle_service.whisper_word_dicts(segment, segment_index, len(words)))
    return words


# Palavras do video cru: reaproveita o words.json da geracao; video antigo (sem ele) e transcrito agora.
def load_original_words(original: Path, get_model, language: str, beam_size: int) -> list[dict[str, Any]]:
    words_path = original.with_suffix(".words.json")
    if words_path.exists():
        return json.loads(words_path.read_text(encoding="utf-8"))

    words = transcribe_words(get_model(), str(original), language, beam_size)
    words_path.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    return words


# Como a formula atual quebraria esse video, em grupos de indices (referencia de F1).
def formula_groups(words: list[dict[str, Any]], profile: str) -> list[tuple[int, int]]:
    max_words = subtitle_service.DEFAULT_MAX_WORDS_SHORTS if profile == "vertical" else 0
    groups: list[tuple[int, int]] = []
    start = 0
    while start < len(words):
        end = start
        while end < len(words) and words[end]["segment_id"] == words[start]["segment_id"]:
            end += 1
        segment_words = words[start:end]
        duration = float(segment_words[-1]["end"]) - float(segment_words[0]["start"])
        parts = segmentation.word_groups_for_segment(segment_words, duration, max_words) or [segment_words]
        offset = start
        for part in parts:
            groups.append((offset, offset + len(part)))
            offset += len(part)
        start = end
    return groups


# Legendas corrigidas: SRT exportado ou, se for projeto do Premiere, os graficos de texto da sequencia.
def load_corrected_cards(corrections_path: str, sequence: str | None) -> list[style_alignment.Card]:
    path = Path(corrections_path)
    if path.suffix.lower() != ".prproj":
        return style_alignment.parse_srt_text(path.read_text(encoding="utf-8-sig"))
    if not sequence:
        raise StyleError("Escolha a sequencia do projeto do Premiere.")
    try:
        return premiere_project.sequence_cards(path, sequence)
    except premiere_project.ProjectError as error:
        raise StyleError(str(error)) from error


# "Sequencia 42" antes de "Sequencia 9": numero comparado como numero, nao como texto.
def _natural_key(name: str) -> list[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def _project_sequences(project_path: str, originals: list[str] | None) -> list[premiere_project.ProjectSequence]:
    try:
        sequences = premiere_project.read_sequences(project_path, originals)
    except premiere_project.ProjectError as error:
        raise StyleError(str(error)) from error
    if not sequences:
        raise StyleError("Nenhuma sequencia desse projeto tem legenda em grafico ou na trilha de legenda.")
    return sequences


# Sequencias com legenda num projeto do Premiere, a mais nova (maior numero) primeiro.
def scan_project(project_path: str, originals: list[str] | None = None) -> dict[str, Any]:
    sequences = _project_sequences(project_path, originals)
    ordered = sorted(sequences, key=lambda sequence: _natural_key(sequence.name), reverse=True)
    return {
        "projectPath": project_path,
        "sequences": [
            {"name": item.name, "cards": len(item.cards), "finalPath": item.final_path, "originalPath": item.original_path}
            for item in ordered
        ],
    }


# Treina de novo com todos os videos do perfil; sem video nenhum, o perfil some.
def retrain_profile(store: Path, profile: str) -> tuple[Any, dict[str, Any]] | None:
    videos = style_store.load_profile_examples(store, profile)
    directory = style_store.profile_dir(store, profile)
    if not videos:
        style_model.delete_profile(directory)
        return None

    try:
        tree, params = style_model.train_profile(videos)
    except ValueError:
        # Sem quebras e nao-quebras suficientes: mantem o perfil anterior.
        return None
    style_model.save_profile(directory, tree, params)
    return tree, params


def _current_profile(store: Path, profile: str) -> tuple[Any, dict[str, Any]] | None:
    try:
        return style_model.load_profile(style_store.profile_dir(store, profile), min_videos=1)
    except Exception:
        return None


def learn(
    original_path: str,
    srt_path: str,
    final_path: str,
    store_path: str,
    model_size: str,
    language: str,
    beam_size: int,
    device: str,
    compute_type: str,
    sequence: str | None = None,
) -> dict[str, Any]:
    original = Path(original_path)
    store = Path(store_path)
    for label, path in (("Video original", original), ("Correcoes (SRT ou projeto)", Path(srt_path)), ("Video final", Path(final_path))):
        if not path.exists():
            raise StyleError(f"{label} nao encontrado: {path}")

    get_model = model_loader(model_size, device, compute_type)
    cards = load_corrected_cards(srt_path, sequence)
    if not cards:
        raise StyleError("A legenda corrigida esta vazia.")
    return learn_from_cards(original, cards, final_path, store, get_model, language, beam_size)


# Whisper carregado so na primeira vez que alguem pede (video com words.json pode nem precisar).
def model_loader(model_size: str, device: str, compute_type: str) -> Callable[[], Any]:
    loaded_model: dict[str, Any] = {}

    def get_model() -> Any:
        if "model" not in loaded_model:
            emit("status", "preparing", "loading-model", f"Carregando modelo {model_size}...", progress=8)
            loaded_model["model"] = subtitle_service.load_whisper_model(model_size, device, compute_type)
        return loaded_model["model"]

    return get_model


def _emit_status(stage: str, message: str, progress: int) -> None:
    emit("status", "processing", stage, message, progress=progress)


def learn_from_cards(
    original: Path,
    cards: list[style_alignment.Card],
    final_path: str,
    store: Path,
    get_model: Callable[[], Any],
    language: str,
    beam_size: int,
    status: Callable[[str, str, int], None] = _emit_status,
    final_words: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    status("original-words", "Lendo as palavras do video original...", 15)
    words = load_original_words(original, get_model, language, beam_size)

    breaks = style_alignment.align_breaks(words, cards)
    if breaks.match_ratio < style_alignment.MIN_MATCH_RATIO:
        raise StyleError(f"A legenda corrigida nao parece ser desse video (so {breaks.match_ratio:.0%} das palavras bateram).")

    if final_words is None:
        status("final-words", "Transcrevendo o video final (com os seus cortes)...", 40)
        final_words = transcribe_words(get_model(), final_path, language, beam_size)
    speech = style_alignment.align_speech(cards, final_words)
    if speech.match_ratio < style_alignment.MIN_MATCH_RATIO:
        raise StyleError(f"O video final nao parece ser o dessa legenda (so {speech.match_ratio:.0%} das palavras bateram).")

    status("aligning", "Comparando a sua legenda com a gerada...", 75)
    # Bruto em mp3 nao tem imagem: a orientacao vem do video final.
    profile = subtitle_service.resolve_style_profile_name(str(original), subtitle_service.resolve_style_profile_name(final_path))
    gaps = style_features.build_gap_examples(words, breaks)
    timing = style_features.build_timing_samples(cards, speech)

    status("evaluating", "Medindo quanto o perfil atual acertaria...", 82)
    current = _current_profile(store, profile)
    f1_before = style_model.break_f1(style_model.segment_with_model(words, *current), breaks.labels) if current else None
    f1_formula = style_model.break_f1(formula_groups(words, profile), breaks.labels)

    video_id = style_store.video_id_for(str(original))
    style_store.save_video(
        store,
        {
            "id": video_id,
            "profile": profile,
            "name": original.name,
            "originalPath": str(original),
            "f1Before": f1_before,
            "f1Formula": f1_formula,
            "gapExamples": len(gaps),
            "timingSamples": len(timing["lead_in_ms"]),
        },
        {"gaps": gaps, "timing": timing},
    )
    style_store.add_word_fixes(store, breaks.word_fixes)

    status("training", "Treinando o seu estilo...", 90)
    trained = retrain_profile(store, profile)
    f1_after = style_model.break_f1(style_model.segment_with_model(words, *trained), breaks.labels) if trained else None

    warnings = []
    if len(gaps) < MIN_GAP_EXAMPLES:
        warnings.append(f"So {len(gaps)} espacos entre palavras deu pra comparar: esse video ensina pouco sobre quebras.")
    return {
        "videoId": video_id,
        "profile": profile,
        "f1Before": f1_before,
        "f1Formula": f1_formula,
        "f1After": f1_after,
        "gapExamples": len(gaps),
        "timingSamples": len(timing["lead_in_ms"]),
        # Parte do bruto cortada no Premiere: ficou de fora do aprendizado (nao e erro de legenda).
        "cutShare": round(breaks.cut_share, 3),
        "warnings": warnings,
    }


def _video_files(sources: list[str]) -> list[Path]:
    found: list[Path] = []
    for source in sources:
        path = Path(source)
        if path.is_dir():
            found.extend(sorted(child for child in path.iterdir() if child.suffix.lower() in premiere_project.VIDEO_EXTENSIONS))
        elif path.exists():
            found.append(path)
    return found


def _same_file(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


# Quanto a fala do video lembra o texto das legendas (0 a 1). Simetrica de proposito: so "as palavras
# da legenda aparecem no video" faria uma sequencia de uma legenda so bater com qualquer video longo.
def speech_similarity(cards: list[style_alignment.Card], words: list[dict[str, Any]]) -> float:
    card_tokens = [token for card in cards for raw in card.text.split() if (token := normalize_token(raw))]
    spoken = [token for word in words if (token := normalize_token(str(word["word"])))]
    if not card_tokens or not spoken:
        return 0.0
    return difflib.SequenceMatcher(None, card_tokens, spoken, autojunk=False).ratio()


# Videos finais escolhidos pelo usuario (nome livre) que o projeto nao liga a nenhuma sequencia:
# transcreve cada um e da pra sequencia cuja legenda mais parece com o que se fala nele.
def _match_finals_by_speech(
    waiting: list[premiere_project.ProjectSequence],
    candidates: list[Path],
    get_model: Callable[[], Any],
    language: str,
    beam_size: int,
    transcribed: dict[str, list[dict[str, Any]]],
) -> None:
    for number, candidate in enumerate(candidates):
        open_sequences = [sequence for sequence in waiting if not sequence.final_path]
        if not open_sequences:
            return
        emit(
            "status",
            "processing",
            "matching-finals",
            f"Descobrindo de qual sequencia e cada video final ({number + 1}/{len(candidates)}): {candidate.name}",
            progress=3,
        )
        words = transcribe_words(get_model(), str(candidate), language, beam_size)
        score, best = max(((speech_similarity(sequence.cards, words), sequence) for sequence in open_sequences), key=lambda item: item[0])
        if score >= style_alignment.MIN_MATCH_RATIO:
            best.final_path = str(candidate)
            transcribed[str(candidate)] = words


# Ensina de uma vez as sequencias de um projeto (ou so `only`). Bruto pelo nome da sequencia; video final pelo
# projeto ou, se faltar, pelo conteudo dos videos escolhidos. Uma que falha nao para as outras; ja ensinada e pulada
# (menos quando pedida pelo nome: ai ensina de novo).
def learn_project(
    project_path: str,
    originals: list[str],
    finals: list[str],
    store_path: str,
    model_size: str,
    language: str,
    beam_size: int,
    device: str,
    compute_type: str,
    only: str | None = None,
) -> dict[str, Any]:
    store = Path(store_path)
    emit("status", "processing", "reading-project", "Lendo o projeto do Premiere...", progress=2)
    sequences = sorted(_project_sequences(project_path, originals), key=lambda sequence: _natural_key(sequence.name))
    if only is not None:
        sequences = [sequence for sequence in sequences if sequence.name == only]
        if not sequences:
            raise StyleError(f"A sequencia '{only}' nao tem legenda em grafico no projeto.")
    taught_originals = {
        style_store.video_id_for(str(video.get("originalPath", ""))) for video in style_store.load_library(store).get("videos", [])
    }

    todo: list[premiere_project.ProjectSequence] = []
    skipped: list[dict[str, str]] = []
    for sequence in sequences:
        if not sequence.original_path:
            skipped.append({"name": sequence.name, "reason": "bruto nao encontrado"})
        elif only is None and style_store.video_id_for(sequence.original_path) in taught_originals:
            skipped.append({"name": sequence.name, "reason": "ja ensinada"})
        else:
            todo.append(sequence)

    get_model = model_loader(model_size, device, compute_type)
    transcribed: dict[str, list[dict[str, Any]]] = {}
    waiting = [sequence for sequence in todo if not sequence.final_path]
    if waiting and finals:
        # Final que o projeto ja liga a uma sequencia nao precisa ser transcrito pra descobrir de quem e.
        linked = [sequence.final_path for sequence in sequences if sequence.final_path]
        candidates = [video for video in _video_files(finals) if not any(_same_file(video, path) for path in linked)]
        _match_finals_by_speech(waiting, candidates, get_model, language, beam_size, transcribed)
    for sequence in waiting:
        if not sequence.final_path:
            todo.remove(sequence)
            skipped.append({"name": sequence.name, "reason": "video final nao encontrado"})
    skipped.sort(key=lambda item: _natural_key(item["name"]))

    taught: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for number, sequence in enumerate(todo):

        def status(stage: str, message: str, progress: int, number: int = number, name: str = sequence.name) -> None:
            overall = round(5 + 95 * (number + progress / 100) / len(todo))
            emit("status", "processing", stage, f"[{number + 1}/{len(todo)}] {name}: {message}", progress=overall)

        try:
            report = learn_from_cards(
                Path(sequence.original_path or ""),
                sequence.cards,
                sequence.final_path or "",
                store,
                get_model,
                language,
                beam_size,
                status,
                transcribed.get(sequence.final_path or ""),
            )
            taught.append({"name": sequence.name, **report})
        except StyleError as error:
            failed.append({"name": sequence.name, "error": str(error)})
        except (ImportError, MemoryError):
            raise
        except Exception as error:
            # Arquivo quebrado ou ilegivel: registra e segue com as outras sequencias.
            failed.append({"name": sequence.name, "error": str(error)})

    return {"taught": taught, "skipped": skipped, "failed": failed}


def forget(video_id: str, store_path: str) -> dict[str, Any]:
    store = Path(store_path)
    profile = style_store.remove_video(store, video_id)
    if profile is None:
        raise StyleError("Video nao encontrado na biblioteca do estilo.")
    retrain_profile(store, profile)
    return {"videoId": video_id, "profile": profile}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aprendizado do estilo de legenda")
    commands = parser.add_subparsers(dest="command", required=True)

    learn_parser = commands.add_parser("learn")
    learn_parser.add_argument("--original", required=True)
    learn_parser.add_argument("--srt", required=True, help="SRT corrigido ou projeto do Premiere (.prproj)")
    learn_parser.add_argument("--sequence", help="sequencia do projeto (quando --srt e um .prproj)")
    learn_parser.add_argument("--final", required=True)
    learn_parser.add_argument("--store", required=True)
    learn_parser.add_argument("--model", default=subtitle_service.DEFAULT_MODEL)
    learn_parser.add_argument("--language", default=subtitle_service.DEFAULT_LANGUAGE)
    learn_parser.add_argument("--beam-size", type=int, default=subtitle_service.DEFAULT_BEAM_SIZE)
    learn_parser.add_argument("--cpu", action="store_true")

    scan_parser = commands.add_parser("scan-project")
    scan_parser.add_argument("--project", required=True)
    scan_parser.add_argument("--originals", action="append", help="pasta ou mp3 dos brutos (Sequencia 43.mp3 = sequencia Sequencia 43)")

    batch_parser = commands.add_parser("learn-project")
    batch_parser.add_argument("--project", required=True)
    batch_parser.add_argument("--originals", action="append")
    batch_parser.add_argument("--finals", action="append", help="videos finais (ou pasta) pra casar pelo conteudo")
    batch_parser.add_argument("--only", help="ensina so esta sequencia (mesmo se ja ensinada)")
    batch_parser.add_argument("--store", required=True)
    batch_parser.add_argument("--model", default=subtitle_service.DEFAULT_MODEL)
    batch_parser.add_argument("--language", default=subtitle_service.DEFAULT_LANGUAGE)
    batch_parser.add_argument("--beam-size", type=int, default=subtitle_service.DEFAULT_BEAM_SIZE)
    batch_parser.add_argument("--cpu", action="store_true")

    forget_parser = commands.add_parser("forget")
    forget_parser.add_argument("--id", required=True)
    forget_parser.add_argument("--store", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "learn":
            report = learn(
                args.original,
                args.srt,
                args.final,
                args.store,
                args.model,
                args.language,
                args.beam_size,
                "cpu" if args.cpu else "cuda",
                "int8" if args.cpu else "float16",
                args.sequence,
            )
            emit("done", "completed", "done", "Estilo atualizado.", progress=100, report=report)
        elif args.command == "scan-project":
            report = scan_project(args.project, args.originals)
            emit("done", "completed", "done", f"{len(report['sequences'])} sequencias com legenda.", progress=100, report=report)
        elif args.command == "learn-project":
            report = learn_project(
                args.project,
                args.originals or [],
                args.finals or [],
                args.store,
                args.model,
                args.language,
                args.beam_size,
                "cpu" if args.cpu else "cuda",
                "int8" if args.cpu else "float16",
                args.only,
            )
            emit("done", "completed", "done", f"{len(report['taught'])} sequencias ensinadas.", progress=100, report=report)
        else:
            report = forget(args.id, args.store)
            emit("done", "completed", "done", "Video removido e perfil retreinado.", progress=100, report=report)
        return 0
    except StyleError as error:
        emit("error", "error", "style", str(error), error=str(error))
        return 1
    except ImportError as error:
        message = "Dependencia Python faltando (faster-whisper ou scikit-learn). Rode: pip install -r python/requirements.txt"
        emit("error", "error", "bootstrap", message, error=str(error))
        return 1
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        emit("error", "error", "runtime", "Falha ao aprender o estilo.", error=str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
