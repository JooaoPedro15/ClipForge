import argparse
import json
import sys
from pathlib import Path
from typing import Any

import ffmpeg_utils
import srt_utils
import translate_service

MODE_LANGS = {
    "zh": ["zh"],
    "zh-en": ["zh", "en"],
    "zh-original": ["zh", "original"],
}

# Proporcao da altura do video usada como tamanho de fonte, por preset de formato.
# "shorts" medido direto no template do Joao (Premiere, sequencia 1080x1920): a legenda
# amarela do editor usa fonte 70px -> 70/1920 = 0.0365. Mantem a legenda traduzida do
# mesmo tamanho da legenda original.
FONT_SCALE = {
    "shorts": 0.0365,
    "long": 0.040,
}

# Distancia da borda inferior do video (proporcao da altura), por preset.
# "shorts" medido direto no template do Joao: a legenda amarela comeca (topo do texto)
# em Position Y=1369 numa sequencia de 1920px de altura, com fonte 70px -> fundo da
# legenda amarela em ~1453px do topo, ou (1920-1453)/1920 = 0.243 da borda inferior.
# A legenda traduzida fica EMBAIXO da amarela (nao em cima) — usa 0.20 pra deixar ~30px
# de respiro entre o topo da legenda traduzida e o fundo da amarela, sem encostar nem
# ficar colada na borda inferior do video.
BASE_MARGIN_SCALE = {
    "shorts": 0.20,
    "long": 0.05,
}

# Multiplicador de fonte usado como folga extra pro bloco de cima nao sobrepor o de baixo
# quando o bloco de baixo quebra em 2+ linhas (comum no preset "long" com maxWords=0).
TOP_MARGIN_EXTRA_LINE_FACTOR = 1.6

# Empurrao fixo (em pixels reais, nao proporcional) pra baixo no preset "shorts". A
# posicao em BASE_MARGIN_SCALE["shorts"] ja fica no lugar certo pro template atual do
# Joao, mas videos antigos (legenda amarela num template anterior, mais baixo na tela)
# ainda podem encostar por poucos pixels — esse empurrao sempre aplicado resolve sem
# precisar de um modo "video antigo" separado.
SHORTS_MARGIN_NUDGE_PX = 5


def emit(event: str, status: str, stage: str, message: str, **extra: Any) -> None:
    payload = {"event": event, "status": status, "stage": stage, "message": message, **extra}
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def resolve_mode_langs(mode: str) -> list[str]:
    langs = MODE_LANGS.get(mode)
    if not langs:
        raise ValueError(f"Modo de queima desconhecido: {mode}")
    return langs


def translated_srt_candidate_path(original_srt_path: str, lang: str) -> str:
    return str(Path(original_srt_path).with_suffix(f".{lang}.srt"))


def ensure_srt_for_lang(
    lang: str,
    original_srt_path: str,
    source_language: str,
    translator: "translate_service.Translator | None",
) -> str:
    if lang == "original":
        return original_srt_path

    candidate_path = translated_srt_candidate_path(original_srt_path, lang)
    if Path(candidate_path).exists():
        return candidate_path

    entries = srt_utils.parse_srt(original_srt_path)
    texts = [entry[2] for entry in entries]
    translated_texts = translator.translate_segments(texts, source_lang=source_language, target_lang=lang)

    translated_entries = [
        (start, end, translated_text)
        for (start, end, _original_text), translated_text in zip(entries, translated_texts)
    ]
    srt_utils.write_srt(translated_entries, candidate_path)

    return candidate_path


def resolve_format_profile(video_width: int, video_height: int) -> str:
    # Deteta a orientacao real do video pra escolher fonte/margem certas sem depender
    # do dropdown "Formato" da UI (que fica com o valor default se o usuario esquecer
    # de trocar) — retrato vira "shorts", paisagem vira "long".
    return "shorts" if video_height > video_width else "long"


def resolve_layer_style(format_profile: str, video_height: int, is_top: bool) -> tuple[int, int]:
    fontsize = round(video_height * FONT_SCALE[format_profile])
    base_margin = round(video_height * BASE_MARGIN_SCALE[format_profile])
    if format_profile == "shorts":
        base_margin = max(0, base_margin - SHORTS_MARGIN_NUDGE_PX)
    top_margin_extra = round(fontsize * TOP_MARGIN_EXTRA_LINE_FACTOR)
    margin_v = base_margin + top_margin_extra if is_top else base_margin
    return fontsize, margin_v


def _srt_timestamp_to_ass(timestamp: str) -> str:
    hms, millis = timestamp.split(",")
    hours, minutes, seconds = hms.split(":")
    centiseconds = int(millis) // 10
    return f"{int(hours)}:{minutes}:{seconds}.{centiseconds:02d}"


def _escape_ass_text(text: str) -> str:
    # "{" e "}" tem significado especial no ASS (abrem/fecham override tags) e
    # precisam ser escapados pra aparecer como texto literal. "\N" e a quebra de
    # linha explicita do formato ASS (uma quebra "\n" comum e ignorada no render).
    return text.replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def build_ass_content(
    entries: list[tuple[str, str, str]],
    fontsize: int,
    margin_v: int,
    video_width: int,
    video_height: int,
) -> str:
    # PlayResX/PlayResY = resolucao real do video. O filtro "subtitles" do ffmpeg, ao
    # converter um .srt puro internamente pra ASS, usa um PlayRes padrao pequeno e nao
    # documentado — a opcao "original_size" NAO corrige isso (so afeta legendas bitmap,
    # tipo DVD/PGS, nunca texto). Isso fazia FontSize/MarginV em pixels reais serem
    # escalados por um fator desconhecido (~4-6x), gerando legenda gigante ou fora da
    # tela. Gerando o .ass a mao com PlayRes = dimensoes reais do video, a escala fica
    # garantidamente 1:1 com os valores que a gente calcula.
    style = (
        f"Style: Default,Arial,{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
        f"1,0,0,0,100,100,0,0,1,2,0,2,10,10,{margin_v},1"
    )
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {video_width}",
        f"PlayResY: {video_height}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        style,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for start, end, text in entries:
        lines.append(
            f"Dialogue: 0,{_srt_timestamp_to_ass(start)},{_srt_timestamp_to_ass(end)},"
            f"Default,,0,0,0,,{_escape_ass_text(text)}"
        )
    return "\n".join(lines) + "\n"


def write_ass_for_srt(
    srt_path: str,
    ass_path: str,
    fontsize: int,
    margin_v: int,
    video_width: int,
    video_height: int,
) -> None:
    entries = srt_utils.parse_srt(srt_path)
    content = build_ass_content(entries, fontsize, margin_v, video_width, video_height)
    Path(ass_path).write_text(content, encoding="utf-8")


def build_ffmpeg_burn_command(
    ffmpeg_path: str,
    video_path: str,
    ass_paths_top_to_bottom: list[str],
    output_path: str,
) -> list[str]:
    filters = []
    for ass_path in ass_paths_top_to_bottom:
        escaped_path = ffmpeg_utils.escape_path_for_subtitles_filter(ass_path)
        filters.append(f"subtitles='{escaped_path}'")

    return [
        ffmpeg_path,
        "-y",
        "-i",
        video_path,
        "-vf",
        ",".join(filters),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "19",
        "-c:a",
        "copy",
        output_path,
    ]


def run_hardsub(
    video_path: str,
    original_srt_path: str,
    source_language: str,
    mode: str,
    format_profile: str,
    output_path: str | None,
    device: str = "cuda",
    compute_type: str = "default",
) -> str:
    emit("status", "preparing", "starting", "Preparando queima de legenda...", progress=5)

    for path, label in [(video_path, "video"), (original_srt_path, "srt original")]:
        ffmpeg_utils.assert_safe_path_length(path, label)

    ffmpeg_path = ffmpeg_utils.resolve_ffmpeg_path()
    video_info = ffmpeg_utils.probe_video(video_path)
    # Ignora o "format_profile" recebido (reflete o dropdown "Formato" da UI, que fica
    # no valor default se o usuario esquecer de trocar) e deteta a orientacao real do
    # video — garante fonte/margem corretas mesmo se a UI mandar o preset errado.
    resolved_format_profile = resolve_format_profile(video_info.width, video_info.height)

    langs = resolve_mode_langs(mode)
    needs_translation = any(
        lang != "original" and not Path(translated_srt_candidate_path(original_srt_path, lang)).exists()
        for lang in langs
    )
    translator = translate_service.Translator(device=device, compute_type=compute_type) if needs_translation else None

    ass_paths: list[str] = []
    for index, lang in enumerate(langs):
        if lang != "original":
            emit("status", "processing", "translating", f"Verificando legenda em {lang}...", progress=20)
        srt_path = ensure_srt_for_lang(lang, original_srt_path, source_language, translator)

        is_top = index == 0 and len(langs) > 1
        fontsize, margin_v = resolve_layer_style(resolved_format_profile, video_info.height, is_top)

        ass_path = str(Path(srt_path).with_suffix(f".burn-{index}.ass"))
        write_ass_for_srt(srt_path, ass_path, fontsize, margin_v, video_info.width, video_info.height)
        # O caminho da legenda entra dentro do filtro subtitles=..., o ponto mais sensivel
        # ao limite de path do Windows — usa copia em pasta curta como fallback em vez
        # de so falhar, quando o caminho original for longo demais.
        ass_path = ffmpeg_utils.ensure_short_srt_path(ass_path)
        ass_paths.append(ass_path)

    output = output_path or str(Path(video_path).with_suffix("")) + f".hardsub.{mode}{Path(video_path).suffix}"
    ffmpeg_utils.assert_safe_path_length(output, "video de saida")

    command = build_ffmpeg_burn_command(ffmpeg_path, video_path, ass_paths, output)

    emit("status", "processing", "burning", "Queimando legenda no video...", progress=40)

    def on_progress(percent: int) -> None:
        scaled = 40 + int(percent * 0.6)
        emit("status", "processing", "burning", f"Queimando legenda... {percent}%", progress=min(99, scaled))

    ffmpeg_utils.run_ffmpeg_with_progress(command, video_info.duration_sec, on_progress)

    emit("done", "completed", "done", "Video com legenda queimada gerado.", progress=100, outputPath=output)

    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SubtitleForge hardsub service")
    parser.add_argument("--video", required=True)
    parser.add_argument("--original-srt", required=True)
    parser.add_argument("--source-language", required=True)
    parser.add_argument("--mode", required=True, choices=sorted(MODE_LANGS.keys()))
    parser.add_argument("--format", required=True, choices=sorted(FONT_SCALE.keys()))
    parser.add_argument("--output", default=None)
    parser.add_argument("--cpu", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    device = "cpu" if args.cpu else "cuda"
    compute_type = "int8" if args.cpu else "default"

    try:
        run_hardsub(
            video_path=args.video,
            original_srt_path=args.original_srt,
            source_language=args.source_language,
            mode=args.mode,
            format_profile=args.format,
            output_path=args.output,
            device=device,
            compute_type=compute_type,
        )
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        emit("error", "error", "runtime", "Falha ao queimar legenda no video.", error=str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
