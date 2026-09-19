import argparse
import json
import math
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

import ffmpeg_utils
import glossary_service
import translate_service
import translation_pipeline

try:
    from faster_whisper import WhisperModel
except ImportError as error:
    payload = {
        "event": "error",
        "status": "error",
        "stage": "bootstrap",
        "message": "faster-whisper nao instalado.",
        "error": str(error),
    }
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    sys.exit(1)


DEFAULT_MODEL = "large-v3"
DEFAULT_LANGUAGE = "pt"
DEFAULT_BEAM_SIZE = 5
DEFAULT_MAX_LINE_WIDTH = 42
DEFAULT_TARGET_WORDS = 3
DEFAULT_MIN_SUBTITLE_WORDS = 1
DEFAULT_MAX_SUBTITLE_WORDS = 5
DEFAULT_MAX_FAST_SUBTITLE_WORDS = 6
DEFAULT_MIN_SUBTITLE_DURATION = 0.45
DEFAULT_MAX_SUBTITLE_DURATION = 2.0
DEFAULT_IDEAL_SUBTITLE_DURATION_MIN = 0.8
DEFAULT_IDEAL_SUBTITLE_DURATION_MAX = 1.4

# max_words padrao aplicado automaticamente a videos verticais (retrato) quando o
# chamador nao pede um valor explicito (max_words=0) — ver resolve_max_words_for_video.
DEFAULT_MAX_WORDS_SHORTS = 3

# Alguns segmentos "naturais" do Whisper (max_words=0, sem quebra por contagem de
# palavras) podem ficar longos demais quando a fala e continua e a VAD nao detecta
# pausa — sem limite, a legenda fica parada na tela por varios segundos (ou o video
# inteiro) em vez de acompanhar a fala. Acima desse limite, refatia o segmento em
# blocos menores usando os timestamps por palavra, com parametros mais soltos que o
# modo "shorts" (frases mais longas, tipico de legenda de video horizontal).
NATURAL_SPLIT_MAX_DURATION = 7.0
NATURAL_SPLIT_TARGET_WORDS = 8
NATURAL_SPLIT_MIN_WORDS = 3
NATURAL_SPLIT_MAX_WORDS = 14
NATURAL_SPLIT_MAX_WORDS_FAST = 18
NATURAL_SPLIT_MIN_SUBTITLE_DURATION = 1.0
NATURAL_SPLIT_IDEAL_DURATION_MIN = 2.5
NATURAL_SPLIT_IDEAL_DURATION_MAX = 5.0

WEAK_TRAILING_WORDS = {
    "que",
    "de",
    "do",
    "da",
    "pra",
    "para",
    "com",
    "em",
    "e",
    "o",
    "a",
    "um",
    "uma",
    "se",
    "me",
    "te",
}


# Emite eventos JSON no stdout para o Electron acompanhar o progresso em tempo real.
def emit(event: str, status: str, stage: str, message: str, **extra: Any) -> None:
    payload = {
        "event": event,
        "status": status,
        "stage": stage,
        "message": message,
        **extra,
    }
    print(json.dumps(payload, ensure_ascii=False), flush=True)


# Converte segundos para o formato padrao do arquivo .srt.
def format_timestamp(seconds: float) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    milliseconds = math.floor((secs % 1) * 1000)
    return f"{int(hours):02}:{int(minutes):02}:{int(secs):02},{milliseconds:03}"


# Helpers de limpeza de texto aplicados antes de salvar a legenda final.
def remove_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def remove_punctuation(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text)


def clean_text(text: str, no_accents: bool = False, no_punctuation: bool = False) -> str:
    if no_punctuation:
        text = remove_punctuation(text)
    if no_accents:
        text = remove_accents(text)
    return re.sub(r"\s+", " ", text).strip()


# Normaliza palavras apenas para decidir cortes de legenda, sem alterar o texto exibido.
def normalize_boundary_word(word: str) -> str:
    return remove_accents(remove_punctuation(word)).strip().lower()


# Mede a duracao coberta por um grupo de palavras com timestamps do Whisper.
def get_words_duration(words: list[Any]) -> float:
    if not words:
        return 0.0

    start = getattr(words[0], "start", None)
    end = getattr(words[-1], "end", None)

    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return 0.0

    return max(0.0, float(end) - float(start))


# Segmenta timestamps por palavra buscando blocos naturais em torno de 3 palavras.
def segment_words_naturally(
    words: list[Any],
    target_words: int = DEFAULT_TARGET_WORDS,
    min_words: int = DEFAULT_MIN_SUBTITLE_WORDS,
    max_words: int = DEFAULT_MAX_SUBTITLE_WORDS,
    max_words_fast_speech: int = DEFAULT_MAX_FAST_SUBTITLE_WORDS,
    min_duration: float = DEFAULT_MIN_SUBTITLE_DURATION,
    max_duration: float = DEFAULT_MAX_SUBTITLE_DURATION,
    ideal_duration_min: float = DEFAULT_IDEAL_SUBTITLE_DURATION_MIN,
    ideal_duration_max: float = DEFAULT_IDEAL_SUBTITLE_DURATION_MAX,
) -> list[list[Any]]:
    word_items = list(words)
    if not word_items:
        return []

    min_words = max(1, min_words)
    target_words = max(min_words, target_words or DEFAULT_TARGET_WORDS)
    max_words = max(target_words, max_words)
    max_words_fast_speech = max(max_words, max_words_fast_speech)

    segments: list[list[Any]] = []
    index = 0

    while index < len(word_items):
        remaining = len(word_items) - index
        normal_limit = min(max_words, remaining)
        fast_limit = min(max_words_fast_speech, remaining)
        fast_duration = get_words_duration(word_items[index : index + fast_limit])
        limit = fast_limit if fast_limit > normal_limit and 0 < fast_duration <= max_duration else normal_limit
        best_count = min(target_words, limit)
        best_score = float("inf")

        for count in range(min(min_words, remaining), limit + 1):
            candidate = word_items[index : index + count]
            duration = get_words_duration(candidate)
            remaining_after = remaining - count
            trailing_word = normalize_boundary_word(str(getattr(candidate[-1], "word", "")))
            score = abs(count - target_words) * 10

            if trailing_word in WEAK_TRAILING_WORDS and remaining_after > 0:
                score += 80

            if remaining_after == 1 and count < limit:
                score += 45

            if duration > 0:
                if duration < min_duration:
                    score += (min_duration - duration) * 30
                elif ideal_duration_min <= duration <= ideal_duration_max:
                    score -= 6
                elif duration < ideal_duration_min:
                    score += (ideal_duration_min - duration) * 8
                elif duration <= max_duration:
                    score += (duration - ideal_duration_max) * 8
                else:
                    score += 40 + (duration - max_duration) * 60

            if count > max_words:
                score += (count - max_words) * 6

            if score < best_score:
                best_score = score
                best_count = count

        while best_count < limit:
            trailing_word = normalize_boundary_word(str(getattr(word_items[index + best_count - 1], "word", "")))
            if trailing_word not in WEAK_TRAILING_WORDS:
                break
            best_count += 1

        if remaining - best_count == 1 and best_count < limit:
            best_count += 1

        segments.append(word_items[index : index + best_count])
        index += best_count

    return segments


# Quebra a fala em linhas menores para melhorar a leitura do subtitulo.
def split_text_into_lines(text: str, max_width: int) -> str:
    words = text.split()
    lines: list[str] = []
    current_line = ""

    for word in words:
        if current_line and len(current_line) + 1 + len(word) > max_width:
            lines.append(current_line)
            current_line = word
        else:
            current_line = f"{current_line} {word}".strip()

    if current_line:
        lines.append(current_line)

    return "\n".join(lines)


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


# Monta e adiciona ao .srt uma entrada curta (grupo de poucas palavras), usada tanto no
# modo "shorts" (max_words explicito) quanto no fallback de segmentos naturais longos.
def append_word_group_entry(
    words_group: list[Any],
    segment_count: int,
    srt_content: list[str],
    subtitle_entries: list[tuple[str, str, str]],
    no_accents: bool,
    no_punctuation: bool,
    uppercase: bool,
    lowercase: bool,
    card_records: list[dict[str, Any]],
    segment_index: int,
    avg_logprob: float | None,
) -> None:
    sub_start = format_timestamp(words_group[0].start)
    sub_end = format_timestamp(words_group[-1].end)
    raw_text = " ".join(word.word.strip() for word in words_group)
    text = clean_text(raw_text, no_accents, no_punctuation)
    if uppercase:
        text = text.upper()
    elif lowercase:
        text = text.lower()

    subtitle_entries.append((sub_start, sub_end, text))

    srt_content.append(f"{segment_count}")
    srt_content.append(f"{sub_start} --> {sub_end}")
    srt_content.append(text)
    srt_content.append("")

    card_records.append(
        {
            "i": len(card_records),
            "start": words_group[0].start,
            "end": words_group[-1].end,
            "text": raw_text,
            "segment_id": segment_index,
            "avg_logprob": avg_logprob,
        }
    )


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

    if output_path is None:
        output_file = input_file.with_suffix(".srt")
    else:
        output_file = Path(output_path)

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
    model = WhisperModel(
        model_size,
        device=device,
        compute_type=compute_type,
    )
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

    srt_content: list[str] = []
    subtitle_entries: list[tuple[str, str, str]] = []
    segment_count = 0
    card_records: list[dict[str, Any]] = []
    segment_index = -1

    for segment in segments:
        segment_index += 1
        if max_words > 0 and word_timestamps and segment.words:
            # Neste modo, usa timestamps por palavra para fatiar legendas por ritmo e limites naturais.
            for words_group in segment_words_naturally(segment.words, target_words=max_words):
                segment_count += 1
                append_word_group_entry(
                    words_group,
                    segment_count,
                    srt_content,
                    subtitle_entries,
                    no_accents,
                    no_punctuation,
                    uppercase,
                    lowercase,
                    card_records=card_records,
                    segment_index=segment_index,
                    avg_logprob=getattr(segment, "avg_logprob", None),
                )

            segment_end = getattr(segment, "end", None)
        elif word_timestamps and segment.words and (segment.end - segment.start) > NATURAL_SPLIT_MAX_DURATION:
            # Segmento natural longo demais (fala continua sem pausa detectada pela VAD) —
            # refatia em blocos menores em vez de deixar uma legenda estatica na tela.
            for words_group in segment_words_naturally(
                segment.words,
                target_words=NATURAL_SPLIT_TARGET_WORDS,
                min_words=NATURAL_SPLIT_MIN_WORDS,
                max_words=NATURAL_SPLIT_MAX_WORDS,
                max_words_fast_speech=NATURAL_SPLIT_MAX_WORDS_FAST,
                min_duration=NATURAL_SPLIT_MIN_SUBTITLE_DURATION,
                max_duration=NATURAL_SPLIT_MAX_DURATION,
                ideal_duration_min=NATURAL_SPLIT_IDEAL_DURATION_MIN,
                ideal_duration_max=NATURAL_SPLIT_IDEAL_DURATION_MAX,
            ):
                segment_count += 1
                append_word_group_entry(
                    words_group,
                    segment_count,
                    srt_content,
                    subtitle_entries,
                    no_accents,
                    no_punctuation,
                    uppercase,
                    lowercase,
                    card_records=card_records,
                    segment_index=segment_index,
                    avg_logprob=getattr(segment, "avg_logprob", None),
                )

            segment_end = getattr(segment, "end", None)
        else:
            # Sem max_words, cada segmento do Whisper vira uma entrada do .srt.
            segment_count += 1
            raw_text = segment.text.strip()
            text = clean_text(raw_text, no_accents, no_punctuation)
            if uppercase:
                text = text.upper()
            elif lowercase:
                text = text.lower()

            subtitle_entries.append((format_timestamp(segment.start), format_timestamp(segment.end), text))

            card_records.append(
                {
                    "i": len(card_records),
                    "start": segment.start,
                    "end": segment.end,
                    "text": raw_text,
                    "segment_id": segment_index,
                    "avg_logprob": getattr(segment, "avg_logprob", None),
                }
            )

            text = split_text_into_lines(text, max_line_width)

            srt_content.append(f"{segment_count}")
            srt_content.append(f"{format_timestamp(segment.start)} --> {format_timestamp(segment.end)}")
            srt_content.append(text)
            srt_content.append("")

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

    with open(output_file, "w", encoding="utf-8") as file_handle:
        file_handle.write("\n".join(srt_content))

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

