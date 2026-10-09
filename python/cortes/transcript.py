"""Transcricao em linhas com tempo pro LLM: '[mm:ss] FILME: ...', '[mm:ss] VOCE: ...', '[mm:ss] [C12]'."""

from collections.abc import Iterable

from cortes.candidates import Candidate


def clock(seconds: float) -> str:
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def transcript_lines(
    film_segments: list[dict],
    mic_segments: list[dict],
    start: float,
    end: float,
    candidates: Iterable[Candidate] = (),
) -> list[str]:
    items = []
    for speaker, segments in (("FILME", film_segments), ("VOCE", mic_segments)):
        for segment in segments:
            if start <= segment["start"] < end:
                items.append((segment["start"], 0, f"[{clock(segment['start'])}] {speaker}: {segment['text']}"))
    for candidate in candidates:
        items.append((candidate.t, 1, f"[{clock(candidate.t)}] [{candidate.id}]"))
    return [text for _t, _order, text in sorted(items, key=lambda item: (item[0], item[1]))]
