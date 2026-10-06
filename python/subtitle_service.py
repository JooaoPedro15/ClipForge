import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import ffmpeg_utils
import glossary_service
import segmentation
import srt_utils
import translate_service
import translation_pipeline
from events import emit

# Carregado sob demanda em load_whisper_model: importar este modulo nao exige o
# faster-whisper (testes e outros servicos reaproveitam funcoes daqui).
WhisperModel: Any = None


# Importa o faster-whisper so na hora de abrir o modelo; sem ele, ImportError aqui.
def load_whisper_model(model_size: str, device: str, compute_type: str) -> Any:
    global WhisperModel
    if WhisperModel is None:
        from faster_whisper import WhisperModel as faster_whisper_model

        WhisperModel = faster_whisper_model
    return WhisperModel(model_size, device=device, compute_type=compute_type)


DEFAULT_MODEL = "large-v3"
DEFAULT_LANGUAGE = "pt"
DEFAULT_BEAM_SIZE = 5
DEFAULT_MAX_LINE_WIDTH = 42

# max_words padrao aplicado automaticamente a videos verticais (retrato) quando o
# chamador nao pede um valor explicito (max_words=0) — ver resolve_max_words_for_video.
DEFAULT_MAX_WORDS_SHORTS = 3


# Deteta a orientacao real do video (retrato x paisagem) pra pre-definir max_words sem
# depender do usuario lembrar de trocar o preset "Formato" na UI. So atua quando o
# chamador nao pediu um max_words explicito (0 = "automatico/sem preferencia"); se o
# probe falhar (ex.: arquivo e so audio, sem stream de video), mantem o comportamento
# anterior sem quebrar a transcricao.
def resolve_max_words_for_video(input_path: str, max_words: int) -> int:
    if max_words > 0:
        return max_words

    try:
        video_info = ffmpeg_utils.probe_video(input_path)
    except Exception:
        return max_words

    if video_info.height > video_info.width:
        return DEFAULT_MAX_WORDS_SHORTS

    return max_words


# Fronteira com o Whisper: palavras viram dicts simples, o formato que a segmentacao usa.
def whisper_word_dicts(segment: Any) -> list[dict[str, Any]]:
    return [
        {"word": str(word.word), "start": float(word.start), "end": float(word.end)}
        for word in (getattr(segment, "words", None) or [])
    ]


# Gera um progresso aproximado mesmo quando o Whisper ainda nao terminou tudo.
def estimate_progress(segment_end: float | None, total_duration: float | None, segment_count: int) -> int:
    if total_duration and total_duration > 0 and segment_end is not None:
        return min(96, max(50, 50 + math.floor((segment_end / total_duration) * 44)))

    return min(96, 50 + math.floor(segment_count / 5))


# Fluxo principal: carrega o modelo, transcreve, formata e grava o .srt.
def transcribe_video(
    input_path: str,
    model_size: str = DEFAULT_MODEL,
    language: str = DEFAULT_LANGUAGE,
    beam_size: int = DEFAULT_BEAM_SIZE,
    max_line_width: int = DEFAULT_MAX_LINE_WIDTH,
    max_words: int = 0,
    word_timestamps: bool = True,
    device: str = "cuda",
    compute_type: str = "float16",
    output_path: str | None = None,
    uppercase: bool = False,
    lowercase: bool = False,
    no_accents: bool = False,
    no_punctuation: bool = False,
    translate_to: list[str] | None = None,
    channel_glossary_path: str = glossary_service.DEFAULT_CHANNEL_GLOSSARY_PATH,
    video_type: str = "",
) -> str:
    input_file = Path(input_path)

    if not input_file.exists():
        emit(
            "error",
            "error",
            "input",
            "Arquivo nao encontrado.",
            error=f"Arquivo nao encontrado: {input_path}",
        )
        raise FileNotFoundError(input_path)

    output_file = input_file.with_suffix(".srt") if output_path is None else Path(output_path)

    max_words = resolve_max_words_for_video(str(input_file), max_words)

    emit(
        "status",
        "preparing",
        "starting",
        "Inicializando SubtitleForge...",
        progress=5,
        outputPath=str(output_file),
    )
    emit(
        "status",
        "preparing",
        "loading-model",
        f"Carregando modelo {model_size}...",
        progress=12,
    )

    load_started_at = time.time()
    model = load_whisper_model(model_size, device, compute_type)
    load_time = round(time.time() - load_started_at, 1)

    emit(
        "status",
        "preparing",
        "model-ready",
        f"Modelo carregado em {load_time}s.",
        progress=28,
        loadTimeSec=load_time,
    )
    emit(
        "status",
        "processing",
        "transcribing",
        "Transcrevendo audio...",
        progress=42,
    )

    transcribe_started_at = time.time()
    segments, info = model.transcribe(
        str(input_file),
        beam_size=beam_size,
        language=language,
        word_timestamps=word_timestamps,
        vad_filter=True,
        vad_parameters={
            "min_silence_duration_ms": 300,
        },
    )

    detected_language = getattr(info, "language", language)
    language_probability = getattr(info, "language_probability", None)
    total_duration = getattr(info, "duration", None)

    probability_text = f"{language_probability:.1%}" if isinstance(language_probability, (int, float)) else "--"

    emit(
        "status",
        "processing",
        "language-detected",
        f"Idioma detectado: {detected_language} ({probability_text}).",
        progress=50,
        detectedLanguage=detected_language,
        languageProbability=language_probability,
    )

    card_records: list[dict[str, Any]] = []
    segment_count = 0
    segment_index = -1

    for segment in segments:
        segment_index += 1
        segment_info = {
            "id": segment_index,
            "start": segment.start,
            "end": segment.end,
            "text": segment.text,
            "avg_logprob": getattr(segment, "avg_logprob", None),
        }
        words = whisper_word_dicts(segment) if word_timestamps else []
        card_records.extend(
            segmentation.cards_for_segment(words, segment_info, max_words, first_index=len(card_records))
        )
        segment_count = len(card_records)
        segment_end = getattr(segment, "end", None)

        if segment_count == 1 or segment_count % 25 == 0:
            # Emite checkpoints periodicos para a UI nao ficar "morta" durante arquivos longos.
            emit(
                "status",
                "processing",
                "segments",
                f"{segment_count} segmentos processados.",
                progress=estimate_progress(segment_end, total_duration, segment_count),
                processedSegments=segment_count,
            )

    transcribe_time = round(time.time() - transcribe_started_at, 1)

    emit(
        "status",
        "processing",
        "writing",
        "Gravando arquivo .srt...",
        progress=97,
        processedSegments=segment_count,
        totalSegments=segment_count,
        outputPath=str(output_file),
    )

    srt_text = srt_utils.render_srt(
        card_records,
        max_line_width=max_line_width,
        uppercase=uppercase,
        lowercase=lowercase,
        no_accents=no_accents,
        no_punctuation=no_punctuation,
    )
    with open(output_file, "w", encoding="utf-8") as file_handle:
        file_handle.write(srt_text)

    cards_path = output_file.with_suffix(".cards.json")
    cards_path.write_text(json.dumps(card_records, ensure_ascii=False, indent=2), encoding="utf-8")

    if translate_to:
        # Um Translator so pro loop inteiro: o construtor e leve, mas
        # _ensure_loaded carrega o modelo NLLB do disco na primeira chamada e
        # guarda em self._translator — instanciar de novo a cada idioma
        # recarregaria o modelo do zero pra cada target_lang extra.
        translator = translate_service.Translator(device=device, compute_type=compute_type)

        for target_lang in translate_to:
            emit(
                "status",
                "processing",
                "translating",
                f"Traduzindo para {target_lang}...",
                progress=98,
            )
            try:
                translated_output = str(output_file.with_suffix(f".{target_lang}.srt"))
                translation_pipeline.traduzir_cards(
                    cards=card_records,
                    translator=translator,
                    source_lang=detected_language,
                    target_lang=target_lang,
                    output_path=translated_output,
                    channel_glossary_path=channel_glossary_path,
                    uppercase=uppercase,
                    lowercase=lowercase,
                    video_type=video_type,
                )

                emit(
                    "translation-done",
                    "completed",
                    "translating",
                    f"Traducao para {target_lang} concluida.",
                    targetLang=target_lang,
                    outputPath=translated_output,
                )
            except Exception as error:
                emit(
                    "translation-error",
                    "error",
                    "translating",
                    f"Falha ao traduzir para {target_lang}.",
                    targetLang=target_lang,
                    error=str(error),
                )

    emit(
        "done",
        "completed",
        "done",
        "Transcricao concluida.",
        progress=100,
        outputPath=str(output_file),
        processedSegments=segment_count,
        totalSegments=segment_count,
        durationSec=transcribe_time,
        detectedLanguage=detected_language,
    )

    return str(output_file)


# Define a interface CLI usada pelo processo principal do Electron.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ClipForge Subtitle service")
    parser.add_argument("input", help="Caminho do video ou audio")
    parser.add_argument("-o", "--output", default=None)
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL)
    parser.add_argument("-l", "--language", default=DEFAULT_LANGUAGE)
    parser.add_argument("-b", "--beam-size", type=int, default=DEFAULT_BEAM_SIZE)
    parser.add_argument("-w", "--max-width", type=int, default=DEFAULT_MAX_LINE_WIDTH)
    parser.add_argument("--uppercase", action="store_true")
    parser.add_argument("--lowercase", action="store_true")
    parser.add_argument("--no-accents", action="store_true")
    parser.add_argument("--no-punctuation", action="store_true")
    parser.add_argument("--max-words", type=int, default=0)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--translate-to", default="")
    parser.add_argument("--video-type", default="", help="Contexto do video (ex.: gameplay de terror) pra traducao")
    return parser.parse_args()


# Configura device/compute type e transforma excecoes em saidas previsiveis para o Electron.
def main() -> int:
    args = parse_args()
    device = "cpu" if args.cpu else "cuda"
    compute_type = "int8" if args.cpu else "float16"
    translate_to = [lang.strip() for lang in args.translate_to.split(",") if lang.strip()]

    try:
        transcribe_video(
            input_path=args.input,
            model_size=args.model,
            language=args.language,
            beam_size=args.beam_size,
            max_line_width=args.max_width,
            max_words=args.max_words,
            device=device,
            compute_type=compute_type,
            output_path=args.output,
            uppercase=args.uppercase,
            lowercase=args.lowercase,
            no_accents=args.no_accents,
            no_punctuation=args.no_punctuation,
            translate_to=translate_to,
            video_type=args.video_type,
        )
        return 0
    except FileNotFoundError:
        return 1
    except KeyboardInterrupt:
        emit(
            "error",
            "error",
            "cancelled",
            "Processo interrompido.",
            error="Processo interrompido.",
        )
        return 130
    except ImportError as error:
        emit(
            "error",
            "error",
            "bootstrap",
            "faster-whisper nao instalado.",
            error=str(error),
        )
        return 1
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        emit(
            "error",
            "error",
            "runtime",
            "Falha durante a transcricao.",
            error=str(error),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

