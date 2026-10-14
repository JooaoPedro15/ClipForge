"""Biblioteca do Pre-editor (%APPDATA%/clip-forge/preedit-learning): fontes ensinadas, exemplos e modelos."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def source_id(recording: str, fmt: str) -> str:
    normalized = os.path.normcase(os.path.abspath(recording))
    return hashlib.sha1(f"{normalized}|{fmt}".encode()).hexdigest()[:12]


def _library_path(store: Path) -> Path:
    return store / "library.json"


def load_library(store: Path) -> dict[str, Any]:
    path = _library_path(store)
    if not path.exists():
        return {"version": 1, "sources": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_library(store: Path, library: dict[str, Any]) -> None:
    store.mkdir(parents=True, exist_ok=True)
    _library_path(store).write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding="utf-8")


def _examples_path(store: Path, source: str) -> Path:
    return store / "examples" / f"{source}.json"


# Cada fonte e salva ao terminar: um lote interrompido nao perde o que ja foi ensinado.
def save_source(store: Path, entry: dict[str, Any], examples: dict[str, Any]) -> None:
    path = _examples_path(store, entry["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(examples, ensure_ascii=False), encoding="utf-8")
    library = load_library(store)
    library["sources"] = [item for item in library["sources"] if item["id"] != entry["id"]] + [entry]
    _save_library(store, library)


def remove_source(store: Path, source: str) -> str | None:
    library = load_library(store)
    removed = next((item for item in library["sources"] if item["id"] == source), None)
    if removed is None:
        return None
    library["sources"] = [item for item in library["sources"] if item["id"] != source]
    _save_library(store, library)
    _examples_path(store, source).unlink(missing_ok=True)
    return str(removed["format"])


def load_examples(store: Path, fmt: str) -> list[dict[str, Any]]:
    examples = []
    for entry in load_library(store)["sources"]:
        path = _examples_path(store, entry["id"])
        if entry["format"] == fmt and path.exists():
            examples.append(json.loads(path.read_text(encoding="utf-8")))
    return examples


def models_dir(store: Path, fmt: str) -> Path:
    return store / "models" / fmt
