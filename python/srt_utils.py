from pathlib import Path
from typing import Any

# format_timestamp tambem e reexportado: translation_pipeline chama srt_utils.format_timestamp.
from text_utils import clean_text, format_timestamp, split_text_into_lines


def parse_srt(path: str) -> list[tuple[str, str, str]]:
    content = Path(path).read_text(encoding="utf-8")
    blocks = [block for block in content.strip().split("\n\n") if block.strip()]

    entries: list[tuple[str, str, str]] = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        # lines[0] e o indice numerico, lines[1] e "start --> end", o resto e o texto.
        timestamp_line = lines[1]
        start, end = [part.strip() for part in timestamp_line.split("-->")]
        text = "\n".join(lines[2:])

        entries.append((start, end, text))

    return entries


def write_srt(entries: list[tuple[str, str, str]], path: str) -> None:
    blocks: list[str] = []
    for index, (start, end, text) in enumerate(entries, start=1):
        blocks.append(f"{index}\n{start} --> {end}\n{text}")

    Path(path).write_text("\n\n".join(blocks), encoding="utf-8")


# Monta o texto do .srt a partir dos cards. Limpeza, maiuscula/minuscula e quebra
# de linha por largura acontecem so aqui, iguais pra toda legenda.
def render_srt(
    cards: list[dict[str, Any]],
    max_line_width: int,
    uppercase: bool = False,
    lowercase: bool = False,
    no_accents: bool = False,
    no_punctuation: bool = False,
) -> str:
    lines: list[str] = []
    for number, card in enumerate(cards, start=1):
        text = clean_text(str(card["text"]), no_accents, no_punctuation)
        if uppercase:
            text = text.upper()
        elif lowercase:
            text = text.lower()
        lines.append(str(number))
        lines.append(f"{format_timestamp(card['start'])} --> {format_timestamp(card['end'])}")
        lines.append(split_text_into_lines(text, max_line_width))
        lines.append("")
    return "\n".join(lines)
