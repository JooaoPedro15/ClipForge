"""Arvores do Pre-editor por formato: trecho fica?, regravada sai?, quanto de pausa sobra, zoom? e nivel do zoom.

scikit-learn e joblib importados dentro das funcoes, como no Meu estilo.
"""

import json
import shutil
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from style_model import percentile

from preedit.features import PAUSE_FEATURES, PHRASE_FEATURES, RETAKE_FEATURES, ZOOM_FEATURES

MIN_RECORDINGS = 3
# Arvore pequena generaliza e da pra ler; sem limite ela decora as gravacoes.
TREE = {"max_depth": 6, "min_samples_leaf": 15, "random_state": 0}
# Uma gravacao em cada quatro vai pro teste (nunca a mesma gravacao em treino e teste).
TEST_EVERY = 4
NAMES = {
    "trecho": PHRASE_FEATURES,
    "regravada": RETAKE_FEATURES,
    "pausa": PAUSE_FEATURES,
    "zoom": ZOOM_FEATURES,
    "nivel": ZOOM_FEATURES,
}
DEFAULT_PARAMS = {
    "zooms_per_min": 0.0,
    "zoom_min_gap_s": 3.0,
    "zoom_duration_p10": 0.6,
    "zoom_duration_p90": 1.3,
    "zoom_level_median": 1.3,
}


@dataclass
class FormatModels:
    trecho: Any
    regravada: Any | None
    pausa: Any | None
    zoom: Any | None
    nivel: Any | None
    params: dict[str, Any]


def _rows(examples: list[dict], kind: str) -> tuple[list[list[float]], list[float]]:
    rows = [row for example in examples for row in example.get(kind, [])]
    return [row["x"] for row in rows], [row["y"] for row in rows]


def _classifier(features: list[list[float]], labels: list[float]) -> Any | None:
    if len(set(labels)) < 2:
        return None
    from sklearn.tree import DecisionTreeClassifier

    return DecisionTreeClassifier(class_weight="balanced", **TREE).fit(features, [int(y) for y in labels])


def _regressor(features: list[list[float]], labels: list[float]) -> Any | None:
    if len(labels) < TREE["min_samples_leaf"]:
        return None
    from sklearn.tree import DecisionTreeRegressor

    return DecisionTreeRegressor(**TREE).fit(features, labels)


def probabilities(model: Any, rows: list[list[float]]) -> list[float]:
    if model is None or not rows:
        return []
    classes = list(model.classes_)
    if 1 not in classes:
        return [0.0] * len(rows)
    position = classes.index(1)
    return [float(row[position]) for row in model.predict_proba(rows)]


def compute_params(examples: list[dict]) -> dict[str, Any]:
    # Gravacao sem nenhuma frase (sem fala na faixa) nao ensina nada; video final ensina so o ritmo do zoom.
    examples = [example for example in examples if example.get("phrase") or example.get("final")]
    stats = [example["stats"] for example in examples]
    final_sec = sum(item["final_sec"] for item in stats)
    durations = [value for item in stats for value in item["zoom_durations"]]
    levels = [value for item in stats for value in item["zoom_levels"]]
    gaps = [value for item in stats for value in item["zoom_gaps"]]
    return {
        # O minimo pro editor conta so gravacoes com bruto: o corte depende do modelo de trecho.
        "recordings": sum(1 for example in examples if example.get("phrase")),
        "zooms_per_min": round(sum(item["zooms"] for item in stats) / final_sec * 60, 3) if final_sec else 0.0,
        "zoom_min_gap_s": percentile(gaps, 10) or DEFAULT_PARAMS["zoom_min_gap_s"],
        "zoom_duration_p10": percentile(durations, 10) or DEFAULT_PARAMS["zoom_duration_p10"],
        "zoom_duration_p90": percentile(durations, 90) or DEFAULT_PARAMS["zoom_duration_p90"],
        "zoom_level_median": float(statistics.median(levels)) if levels else DEFAULT_PARAMS["zoom_level_median"],
    }


def train_format(examples: list[dict]) -> FormatModels | None:
    trecho = _classifier(*_rows(examples, "phrase"))
    if trecho is None:
        return None
    zoom_rows = [row for example in examples for row in example.get("zoom", [])]
    zoomed = [row for row in zoom_rows if row["y"] == 1 and row.get("level")]
    return FormatModels(
        trecho=trecho,
        regravada=_classifier(*_rows(examples, "retake")),
        pausa=_regressor(*_rows(examples, "pause")),
        zoom=_classifier(*_rows(examples, "zoom")),
        nivel=_regressor([row["x"] for row in zoomed], [row["level"] for row in zoomed]),
        params=compute_params(examples),
    )


def _f1(truth: list[float], predicted: list[int]) -> float | None:
    if not truth:
        return None
    from sklearn.metrics import f1_score

    return round(float(f1_score([int(y) for y in truth], predicted, zero_division=0)), 3)


# Chance de uma frase mantida ter nota maior que uma tirada (AUC; 0,5 = chute). E o que o editor usa:
# ele tira as frases de menor nota ate a duracao alvo, entao vale mais que o F1 no limiar de 0,5.
def _ranking(truth: list[float], scores: list[float]) -> float | None:
    if not scores or len(set(truth)) < 2:
        return None
    from sklearn.metrics import roc_auc_score

    return round(float(roc_auc_score([int(y) for y in truth], scores)), 3)


def _split(examples: list[dict]) -> tuple[list[dict], list[dict]]:
    ordered = sorted(examples, key=lambda example: example["recording"])
    test = ordered[TEST_EVERY - 1 :: TEST_EVERY]
    return [example for example in ordered if example not in test], test


def _zoom_f1(train: list[dict], test: list[dict]) -> float | None:
    x, y = _rows(test, "zoom")
    predicted = [int(p >= 0.5) for p in probabilities(_classifier(*_rows(train, "zoom")), x)]
    return _f1(y, predicted) if predicted else None


# Mede em gravacoes que ficaram fora do treino, ao lado do que o Pre-editor atual faria:
# ele mantem todo o conteudo, nao tira regravada, nao da zoom e deixa uma pausa "padrao" (a mediana).
# Videos finais (sem bruto) so ensinam zoom: entram no treino do zoom e tem a medida deles.
def evaluate(examples: list[dict]) -> dict[str, Any]:
    raw = [example for example in examples if not example.get("final")]
    finals = [example for example in examples if example.get("final")]
    report: dict[str, Any] = {}
    if len(raw) < TEST_EVERY:
        report["aviso"] = f"Poucas gravacoes pra medir (precisa de {TEST_EVERY})."
    else:
        report.update(_raw_report(raw, finals))
    if finals:
        if len(finals) < TEST_EVERY:
            report["aviso_finais"] = f"Poucos videos finais pra medir (precisa de {TEST_EVERY})."
        else:
            train_finals, test_finals = _split(finals)
            _, y = _rows(test_finals, "zoom")
            report.update({"finais_treino": len(train_finals), "finais_teste": len(test_finals)})
            report["zoom_f1_finais"] = _zoom_f1(raw + train_finals, test_finals)
            report["zoom_f1_finais_referencia"] = _f1(y, [0] * len(y))
    return report


def _raw_report(raw: list[dict], finals: list[dict]) -> dict[str, Any]:
    train, test = _split(raw)
    trained = train_format(train + finals)
    report: dict[str, Any] = {"gravacoes_treino": len(train), "gravacoes_teste": len(test)}

    x, y = _rows(test, "phrase")
    scores = probabilities(trained.trecho if trained else None, x)
    predicted = [int(p >= 0.5) for p in scores]
    report["trecho_f1"] = _f1(y, predicted) if predicted else None
    report["trecho_f1_referencia"] = _f1(y, [1] * len(y))
    report["trecho_ordem"] = _ranking(y, scores)
    report["trecho_ordem_referencia"] = 0.5

    x, y = _rows(test, "retake")
    predicted = [int(p >= 0.5) for p in probabilities(trained.regravada if trained else None, x)]
    report["regravada_f1"] = _f1(y, predicted) if predicted else None
    report["regravada_f1_referencia"] = _f1(y, [0] * len(y))

    x, y = _rows(test, "pause")
    _, train_y = _rows(train, "pause")
    if y and trained and trained.pausa is not None:
        predicted_ms = trained.pausa.predict(x)
        report["pausa_erro_ms"] = round(sum(abs(a - b) for a, b in zip(predicted_ms, y, strict=True)) / len(y), 1)
        constant = statistics.median(train_y) if train_y else 0.0
        report["pausa_erro_ms_referencia"] = round(sum(abs(constant - b) for b in y) / len(y), 1)

    x, y = _rows(test, "zoom")
    predicted = [int(p >= 0.5) for p in probabilities(trained.zoom if trained else None, x)]
    report["zoom_f1"] = _f1(y, predicted) if predicted else None
    report["zoom_f1_referencia"] = _f1(y, [0] * len(y))
    if finals:
        # O mesmo zoom treinado so com os brutos: diz se misturar o audio dos videos finais ajuda no bruto.
        report["zoom_f1_sem_finais"] = _zoom_f1(train, test)
    return report


def save_models(directory: Path, trained: FormatModels, report: dict[str, Any]) -> None:
    import joblib
    from sklearn.tree import export_text

    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    for name, features in NAMES.items():
        model = getattr(trained, name)
        if model is None:
            continue
        joblib.dump(model, directory / f"{name}.joblib")
        (directory / f"tree_{name}.txt").write_text(export_text(model, feature_names=features), encoding="utf-8")
    (directory / "params.json").write_text(json.dumps(trained.params, indent=2), encoding="utf-8")
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


# So carrega modelo salvo pelo proprio app (joblib usa pickle: nunca abrir arquivo de terceiros).
def load_models(directory: Path, min_recordings: int = MIN_RECORDINGS) -> FormatModels | None:
    params_path = directory / "params.json"
    if not params_path.exists() or not (directory / "trecho.joblib").exists():
        return None
    params = json.loads(params_path.read_text(encoding="utf-8"))
    if int(params.get("recordings", 0)) < min_recordings:
        return None

    import joblib

    loaded = {name: joblib.load(directory / f"{name}.joblib") if (directory / f"{name}.joblib").exists() else None for name in NAMES}
    return FormatModels(params=params, **loaded)
