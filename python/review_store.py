"""Arquivo de revisao da traducao (`video.zh.review.json`).

Uma linha por FRASE em portugues (nao por legenda: uma frase longa vira 2+
legendas na tela). Cada linha guarda a fala, as legendas em chines que
sairam dela, a retraducao literal pro portugues e a suspeita de sentido —
e o que a tela "Revisar traducao" mostra pra quem nao le chines. O .zh.srt
e sempre derivado daqui (review_to_groups) quando uma linha e editada.
"""

import json
from pathlib import Path
from typing import Any

REVIEW_VERSION = 1


def review_path_for(translated_srt_path: str) -> str:
    """video.zh.srt -> video.zh.review.json"""
    return str(Path(translated_srt_path).with_suffix(".review.json"))


def build_review(groups: list[dict[str, Any]], lang: str) -> dict[str, Any] | None:
    """None quando os grupos nao vieram do caminho LLM (sem sentence_id)."""
    if not groups or any("sentence_id" not in g for g in groups):
        return None

    rows: list[dict[str, Any]] = []
    for group in groups:
        part = {"cards": group["cards"], "start": group["start"], "end": group["end"], "zh": group["zh"]}
        if rows and rows[-1]["id"] == group["sentence_id"]:
            row = rows[-1]
            row["parts"].append(part)
            row["cards"] += group["cards"]
            row["end"] = group["end"]
            continue
        rows.append(
            {
                "id": group["sentence_id"],
                "pt": group.get("sentence_text", ""),
                "cards": list(group["cards"]),
                "start": group["start"],
                "end": group["end"],
                "parts": [part],
                "back_pt": group.get("back_pt", ""),
                "note": group.get("review_note", ""),
                "edited": False,
            }
        )
    return {"version": REVIEW_VERSION, "lang": lang, "rows": rows}


def review_to_groups(review: dict[str, Any]) -> list[dict[str, Any]]:
    groups = []
    for row in review["rows"]:
        for part in row["parts"]:
            groups.append(
                {
                    "cards": part["cards"],
                    "start": part["start"],
                    "end": part["end"],
                    "zh": part["zh"],
                    "flag": "",
                    "text": row["pt"],
                }
            )
    return groups


def save_review(review: dict[str, Any], path: str) -> None:
    Path(path).write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")


def load_review(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
