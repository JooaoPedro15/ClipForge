import math
from pathlib import Path


def format_timestamp(seconds: float) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    milliseconds = math.floor((secs % 1) * 1000)
    return f"{int(hours):02}:{int(minutes):02}:{int(secs):02},{milliseconds:03}"


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
