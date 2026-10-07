"""Biblioteca local do aprendizado de estilo (userData/subtitle-style).

library.json lista os videos ensinados; cada video guarda seus exemplos em
examples/<id>.json, pra dar pra remover um video e retreinar sem ele.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Any

LIBRARY_VERSION = 1


# Mesmo video (mesmo caminho, sem diferenciar maiusculas no Windows) -> mesmo id.
def video_id_for(original_path: str) -> str:
    normalized = str(Path(original_path)).lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def profile_dir(store: Path, profile: str) -> Path:
    return store / "profiles" / profile


def load_library(store: Path) -> dict[str, Any]:
    path = store / "library.json"
    if not path.exists():
        return {"version": LIBRARY_VERSION, "videos": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_library(store: Path, library: dict[str, Any]) -> None:
    store.mkdir(parents=True, exist_ok=True)
    (store / "library.json").write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding="utf-8")


def save_video(store: Path, entry: dict[str, Any], examples: dict[str, Any]) -> None:
    examples_dir = store / "examples"
    examples_dir.mkdir(parents=True, exist_ok=True)
    (examples_dir / f"{entry['id']}.json").write_text(json.dumps(examples, ensure_ascii=False), encoding="utf-8")

    library = load_library(store)
    # Ensinar o mesmo video de novo substitui a entrada anterior.
    library["videos"] = [video for video in library["videos"] if video["id"] != entry["id"]]
    library["videos"].append({**entry, "taughtAt": int(time.time() * 1000)})
    _save_library(store, library)


# Devolve o perfil do video removido (pra retreinar) ou None se ele nao existia.
def remove_video(store: Path, video_id: str) -> str | None:
    library = load_library(store)
    removed = next((video for video in library["videos"] if video["id"] == video_id), None)
    if removed is None:
        return None

    library["videos"] = [video for video in library["videos"] if video["id"] != video_id]
    _save_library(store, library)
    (store / "examples" / f"{video_id}.json").unlink(missing_ok=True)
    return str(removed["profile"])


def load_profile_examples(store: Path, profile: str) -> list[dict[str, Any]]:
    videos = []
    for video in load_library(store)["videos"]:
        path = store / "examples" / f"{video['id']}.json"
        if video["profile"] == profile and path.exists():
            videos.append(json.loads(path.read_text(encoding="utf-8")))
    return videos


# Conta as trocas "Whisper escreveu X, usuario corrigiu pra Y" (base pra corrigir sozinho no futuro).
def add_word_fixes(store: Path, fixes: list[tuple[str, str]]) -> None:
    if not fixes:
        return
    path = store / "word_fixes.json"
    counts: dict[str, int] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for whisper_word, user_word in fixes:
        key = f"{whisper_word}->{user_word}"
        counts[key] = counts.get(key, 0) + 1
    store.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(counts, ensure_ascii=False, indent=2), encoding="utf-8")
