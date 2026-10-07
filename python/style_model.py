"""Arvore de decisao que aprende onde o usuario quebra a legenda, mais os tempos dele.

Unico modulo que usa scikit-learn/joblib, sempre importados dentro das funcoes:
sem a biblioteca instalada o resto do app segue com a formula antiga.
"""

import json
import shutil
import statistics
from pathlib import Path
from typing import Any

from style_features import FEATURE_NAMES, gap_features

# Abaixo disso a geracao nao usa o perfil (pouco dado = arvore pouco confiavel).
MIN_VIDEOS_FOR_MODEL = 3
BREAK_THRESHOLD = 0.5
# Buraco menor que isso entre duas legendas do usuario conta como "colou uma na outra".
GLUE_USER_GAP_MS = 40.0
TREE_MAX_DEPTH = 5
TREE_MIN_SAMPLES_LEAF = 20


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = round(q / 100 * (len(ordered) - 1))
    return float(ordered[max(0, min(len(ordered) - 1, position))])


# Travas e tempos tirados das legendas do proprio usuario (nada chutado).
def compute_params(videos: list[dict[str, Any]]) -> dict[str, Any]:
    timing = [video["timing"] for video in videos]
    card_words = [count for item in timing for count in item["card_words"] if count > 0]
    card_ms = [value for item in timing for value in item["card_ms"]]
    lead_in = [value for item in timing for value in item["lead_in_ms"]]
    hold = [value for item in timing for value in item["hold_ms"]]
    glued_raw_gaps = [gap["raw_gap_ms"] for item in timing for gap in item["glue"] if gap["user_gap_ms"] < GLUE_USER_GAP_MS]

    min_words = max(1, int(percentile(card_words, 5) or 1))
    max_words = max(min_words, int(percentile(card_words, 95) or 8))
    return {
        "min_words": min_words,
        "max_words": max_words,
        "max_card_ms": percentile(card_ms, 95) or 5000.0,
        "lead_in_ms": float(statistics.median(lead_in)) if lead_in else 0.0,
        "hold_ms": float(statistics.median(hold)) if hold else 0.0,
        "glue_ms": percentile(glued_raw_gaps, 90) or 0.0,
        "min_card_ms": percentile(card_ms, 5) or 0.0,
    }


def train_profile(videos: list[dict[str, Any]]) -> tuple[Any, dict[str, Any]]:
    from sklearn.tree import DecisionTreeClassifier

    features = [gap["x"] for video in videos for gap in video["gaps"]]
    labels = [gap["y"] for video in videos for gap in video["gaps"]]
    if len(set(labels)) < 2:
        raise ValueError("Exemplos insuficientes: precisa de pelo menos uma quebra e uma nao-quebra.")

    # Profundidade e folha minima limitadas: arvore sem limite decora os videos
    # (overfitting) e erra em video novo; pequena, generaliza e da pra ler.
    tree = DecisionTreeClassifier(
        max_depth=TREE_MAX_DEPTH,
        min_samples_leaf=TREE_MIN_SAMPLES_LEAF,
        class_weight="balanced",
        random_state=0,
    )
    tree.fit(features, labels)

    params = compute_params(videos)
    params["videos"] = len(videos)
    params["gap_examples"] = len(features)
    return tree, params


# Chance de quebra num espaco. Desce a arvore na mao (no -> filho esquerdo/direito ate a folha):
# chamar predict_proba uma vez por palavra custa ~1ms de overhead cada no scikit-learn.
def break_probability(tree: Any, features: list[float]) -> float:
    classes = list(tree.classes_)
    if 1 not in classes:
        return 0.0

    structure = getattr(tree, "tree_", None)
    if structure is None:
        return float(tree.predict_proba([features])[0][classes.index(1)])

    import numpy as np

    node = 0
    while structure.children_left[node] != -1:
        # O scikit-learn compara em float32; converter evita divergir nos limiares.
        if np.float32(features[structure.feature[node]]) <= structure.threshold[node]:
            node = structure.children_left[node]
        else:
            node = structure.children_right[node]
    leaf = structure.value[node][0]
    total = float(leaf.sum())
    return float(leaf[classes.index(1)]) / total if total else 0.0


# Percorre as palavras perguntando "quebro aqui?" a arvore, dentro das travas do usuario.
def segment_with_model(words: list[dict[str, Any]], tree: Any, params: dict[str, Any]) -> list[tuple[int, int]]:
    if not words:
        return []

    groups: list[tuple[int, int]] = []
    card_start = 0
    for index in range(len(words) - 1):
        count = index - card_start + 1
        card_ms = (float(words[index]["end"]) - float(words[card_start]["start"])) * 1000
        if count < params["min_words"]:
            should_break = False
        elif count >= params["max_words"] or card_ms >= params["max_card_ms"]:
            should_break = True
        else:
            should_break = break_probability(tree, gap_features(words, card_start, index)) >= BREAK_THRESHOLD
        if should_break:
            groups.append((card_start, index + 1))
            card_start = index + 1
    groups.append((card_start, len(words)))
    return groups


# F1 das quebras nos espacos rotulados: junta "das quebras do usuario, quantas o app fez"
# (revocacao) com "das quebras do app, quantas o usuario fez" (precisao).
def break_f1(groups: list[tuple[int, int]], labels: dict[int, int]) -> float:
    predicted = {end - 1 for _start, end in groups[:-1]}
    true_positive = sum(1 for gap, label in labels.items() if label == 1 and gap in predicted)
    false_positive = sum(1 for gap, label in labels.items() if label == 0 and gap in predicted)
    false_negative = sum(1 for gap, label in labels.items() if label == 1 and gap not in predicted)
    if true_positive == 0:
        return 0.0
    precision = true_positive / (true_positive + false_positive)
    recall = true_positive / (true_positive + false_negative)
    return 2 * precision * recall / (precision + recall)


# Entra antes, segura depois, cola buracos pequenos, garante duracao minima e nunca sobrepoe.
def apply_timing(cards: list[dict[str, Any]], params: dict[str, Any]) -> list[dict[str, Any]]:
    lead_in = params["lead_in_ms"] / 1000
    hold = params["hold_ms"] / 1000
    glue = params["glue_ms"] / 1000
    min_duration = params["min_card_ms"] / 1000

    adjusted = [{**card, "start": max(0.0, float(card["start"]) - lead_in), "end": float(card["end"]) + hold} for card in cards]
    for index, card in enumerate(adjusted):
        following = adjusted[index + 1] if index + 1 < len(adjusted) else None
        if following is not None:
            # Decide colar olhando o buraco ORIGINAL da fala, que e o que o usuario via.
            raw_gap = float(cards[index + 1]["start"]) - float(cards[index]["end"])
            if 0 <= raw_gap <= glue:
                card["end"] = following["start"]
        if card["end"] - card["start"] < min_duration:
            card["end"] = card["start"] + min_duration
        if following is not None:
            following["start"] = max(following["start"], card["start"])
            card["end"] = min(card["end"], following["start"])
        card["end"] = max(card["end"], card["start"])
    return adjusted


def save_profile(profile_dir: Path, tree: Any, params: dict[str, Any]) -> None:
    import joblib
    from sklearn.tree import export_text

    profile_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(tree, profile_dir / "model.joblib")
    (profile_dir / "params.json").write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
    (profile_dir / "tree.txt").write_text(export_text(tree, feature_names=FEATURE_NAMES), encoding="utf-8")


# So carrega modelo salvo pelo proprio app (joblib usa pickle: nunca abrir arquivo de terceiros).
def load_profile(profile_dir: Path, min_videos: int = MIN_VIDEOS_FOR_MODEL) -> tuple[Any, dict[str, Any]] | None:
    model_path = profile_dir / "model.joblib"
    params_path = profile_dir / "params.json"
    if not model_path.exists() or not params_path.exists():
        return None

    params = json.loads(params_path.read_text(encoding="utf-8"))
    if int(params.get("videos", 0)) < min_videos:
        return None

    import joblib

    return joblib.load(model_path), params


def delete_profile(profile_dir: Path) -> None:
    shutil.rmtree(profile_dir, ignore_errors=True)
