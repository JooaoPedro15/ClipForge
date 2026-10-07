"""Ensina o estilo de legenda do usuario a partir de um video corrigido no Premiere.

Uso (chamado pelo Electron, eventos JSON no stdout):
  python style_service.py learn --original V --srt S --final F --store DIR [--model M] [--language pt] [--cpu]
  python style_service.py forget --id ID --store DIR
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import segmentation
import style_alignment
import style_features
import style_model
import style_store
import subtitle_service
from events import emit

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
) -> dict[str, Any]:
    original = Path(original_path)
    store = Path(store_path)
    for label, path in (("Video original", original), ("SRT corrigido", Path(srt_path)), ("Video final", Path(final_path))):
        if not path.exists():
            raise StyleError(f"{label} nao encontrado: {path}")

    loaded_model: dict[str, Any] = {}

    def get_model() -> Any:
        if "model" not in loaded_model:
            emit("status", "preparing", "loading-model", f"Carregando modelo {model_size}...", progress=8)
            loaded_model["model"] = subtitle_service.load_whisper_model(model_size, device, compute_type)
        return loaded_model["model"]

    emit("status", "processing", "original-words", "Lendo as palavras do video original...", progress=15)
    words = load_original_words(original, get_model, language, beam_size)

    cards = style_alignment.parse_srt_text(Path(srt_path).read_text(encoding="utf-8-sig"))
    if not cards:
        raise StyleError("O SRT corrigido esta vazio.")
    breaks = style_alignment.align_breaks(words, cards)
    if breaks.match_ratio < style_alignment.MIN_MATCH_RATIO:
        raise StyleError(f"O SRT corrigido nao parece ser desse video (so {breaks.match_ratio:.0%} das palavras bateram).")

    emit("status", "processing", "final-words", "Transcrevendo o video final (com os seus cortes)...", progress=40)
    final_words = transcribe_words(get_model(), final_path, language, beam_size)
    speech = style_alignment.align_speech(cards, final_words)
    if speech.match_ratio < style_alignment.MIN_MATCH_RATIO:
        raise StyleError(f"O video final nao parece ser o desse SRT (so {speech.match_ratio:.0%} das palavras bateram).")

    emit("status", "processing", "aligning", "Comparando a sua legenda com a gerada...", progress=75)
    profile = subtitle_service.resolve_style_profile_name(str(original))
    gaps = style_features.build_gap_examples(words, breaks)
    timing = style_features.build_timing_samples(words, cards, breaks, speech)

    emit("status", "processing", "evaluating", "Medindo quanto o perfil atual acertaria...", progress=82)
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

    emit("status", "processing", "training", "Treinando o seu estilo...", progress=90)
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
        "warnings": warnings,
    }


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
    learn_parser.add_argument("--srt", required=True)
    learn_parser.add_argument("--final", required=True)
    learn_parser.add_argument("--store", required=True)
    learn_parser.add_argument("--model", default=subtitle_service.DEFAULT_MODEL)
    learn_parser.add_argument("--language", default=subtitle_service.DEFAULT_LANGUAGE)
    learn_parser.add_argument("--beam-size", type=int, default=subtitle_service.DEFAULT_BEAM_SIZE)
    learn_parser.add_argument("--cpu", action="store_true")

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
            )
            emit("done", "completed", "done", "Estilo atualizado.", progress=100, report=report)
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
