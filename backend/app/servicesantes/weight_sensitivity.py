"""
weight_sensitivity.py
=====================

Barrido de sensibilidad de los pesos (w_text, w_layout, w_pii) de la huella
multimodal sobre el SÍMPLEX, con dos objetivos en paralelo:

    - RANKING   : Recall@1 / MRR sobre familias de test (lo que el grid search
                  optimiza hoy).
    - DETECCIÓN : AUC variantes-vs-distractores con el max_score (el uso binario).

MOTIVACIÓN
----------
En la corrida final desacoplada el grid search asignó w_layout = 0.50 aunque
`layout_only` da Recall@1 = 0.0375 (inútil en aislamiento). Eso es señal de que
el óptimo es una MESETA: muchos vectores de peso muy distintos logran un Recall@1
casi idéntico, así que el argmax no es identificable y NO debe interpretarse
("el layout pesa 0.5"). Este harness lo cuantifica: mide el ANCHO de la meseta
(rango de cada peso entre las configuraciones casi-óptimas).

Además mide el AUC de detección sobre el mismo símplex. La hipótesis, sugerida
por los resultados (text_layout AUC=0.589 vs multimodal AUC=0.17), es que los dos
objetivos JALAN EN DIRECCIONES OPUESTAS respecto a w_pii: el ranking es plano en
w_pii, pero la detección MEJORA cuando w_pii -> 0. Si se confirma, la mejora
concreta de la huella es sacar el PII del score fusionado.

EFICIENCIA
----------
Los sub-scores por canal (selected_text, layout, pii) son INDEPENDIENTES de los
pesos. Se calculan UNA vez por (query, referencia) y se cachean; el barrido luego
solo recombina linealmente y re-rankea. Así el sweep de cientos de vectores de
peso cuesta segundos.

USO
---
    from app.services.weight_sensitivity import run_sensitivity
    run_sensitivity(n_legit=100, n_distractors=200, seed=42, step=0.05,
                    text_channel="lexical", out_prefix="sensitivity_final")

Requiere el entorno con las dependencias (reportlab/PyMuPDF/sentence-transformers
/scipy/sklearn). El bloque __main__ corre un self-test de la lógica pura del
barrido con datos sintéticos cuando esas dependencias no están.
"""

from __future__ import annotations

import csv
import json
import hashlib
from itertools import product
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np


# --------------------------------------------------------------------------- #
# Símplex de pesos
# --------------------------------------------------------------------------- #
def weight_simplex(step: float = 0.05) -> List[Tuple[float, float, float]]:
    """Todos los (w_text, w_layout, w_pii) en una grilla de paso `step` con suma 1."""
    n = int(round(1.0 / step))
    grid = []
    for i in range(n + 1):
        for j in range(n + 1 - i):
            k = n - i - j
            grid.append((round(i * step, 4), round(j * step, 4), round(k * step, 4)))
    return grid


# --------------------------------------------------------------------------- #
# Métricas puras sobre sub-scores cacheados (testeables sin dependencias)
# --------------------------------------------------------------------------- #
def _rank_metrics(cache: dict, w: Tuple[float, float, float]) -> Tuple[float, float]:
    """Recall@1 y MRR para un vector de pesos, sobre las variantes de test."""
    wt, wl, wp = w
    n_top1 = 0
    rr_sum = 0.0
    n = len(cache["var_T"])
    if n == 0:
        return 0.0, 0.0
    for q in range(n):
        final = wt * cache["var_T"][q] + wl * cache["var_L"][q] + wp * cache["var_P"][q]
        truth = cache["var_truth_idx"][q]
        order = np.argsort(-final, kind="stable")  # mayor score primero
        rank = int(np.where(order == truth)[0][0]) + 1
        if rank == 1:
            n_top1 += 1
        rr_sum += 1.0 / rank
    return n_top1 / n, rr_sum / n


def _detection_auc(cache: dict, w: Tuple[float, float, float]) -> Optional[float]:
    """AUC variantes(1) vs distractores(0) usando el max_score sobre el índice."""
    wt, wl, wp = w
    pos = [float(np.max(wt * cache["var_T"][q] + wl * cache["var_L"][q] + wp * cache["var_P"][q]))
           for q in range(len(cache["var_T"]))]
    neg = [float(np.max(wt * cache["dist_T"][q] + wl * cache["dist_L"][q] + wp * cache["dist_P"][q]))
           for q in range(len(cache["dist_T"]))]
    if not pos or not neg:
        return None
    try:
        from sklearn.metrics import roc_auc_score
        labels = [1] * len(pos) + [0] * len(neg)
        return float(roc_auc_score(labels, pos + neg))
    except Exception:
        # Fallback: AUC por conteo de pares concordantes (Mann-Whitney U).
        wins = ties = 0
        for p in pos:
            for ngt in neg:
                if p > ngt:
                    wins += 1
                elif p == ngt:
                    ties += 1
        return (wins + 0.5 * ties) / (len(pos) * len(neg))


def sweep(cache: dict, step: float = 0.05) -> List[dict]:
    """Evalúa Recall@1, MRR y AUC de detección en todo el símplex."""
    out = []
    for w in weight_simplex(step):
        r1, mrr = _rank_metrics(cache, w)
        auc = _detection_auc(cache, w)
        out.append({"w_text": w[0], "w_layout": w[1], "w_pii": w[2],
                    "recall_at_1": round(r1, 4), "mrr": round(mrr, 4),
                    "detection_auc": round(auc, 4) if auc is not None else None})
    return out


def plateau(records: List[dict], tol: float) -> dict:
    """Conjunto casi-óptimo en Recall@1 (a `tol` del mejor) y el RANGO de cada
    peso dentro de ese conjunto. Rangos anchos => pesos NO identificables."""
    best = max(r["recall_at_1"] for r in records)
    near = [r for r in records if best - r["recall_at_1"] <= tol + 1e-9]
    rng = {k: (min(r[k] for r in near), max(r[k] for r in near))
           for k in ("w_text", "w_layout", "w_pii")}
    return {
        "best_recall_at_1": best,
        "tolerance": tol,
        "n_near_optimal_configs": len(near),
        "n_total_configs": len(records),
        "weight_ranges_in_plateau": rng,
        "auc_range_in_plateau": (
            min((r["detection_auc"] for r in near if r["detection_auc"] is not None), default=None),
            max((r["detection_auc"] for r in near if r["detection_auc"] is not None), default=None),
        ),
    }


def best_for_detection(records: List[dict]) -> dict:
    """Mejor vector para DETECCIÓN (AUC) — para contrastar con el de ranking."""
    cand = [r for r in records if r["detection_auc"] is not None]
    if not cand:
        return {}
    return max(cand, key=lambda r: r["detection_auc"])


# --------------------------------------------------------------------------- #
# Cacheo de sub-scores (parte pesada; requiere el motor + dependencias)
# --------------------------------------------------------------------------- #
def build_subscore_cache(text_channel: str = "lexical",
                         n_legit: int = 100, n_distractors: int = 200,
                         seed: int = 42, transformations=None) -> dict:
    """Construye el corpus (variantes DESACOPLADAS) y cachea, para cada query de
    TEST y cada referencia, los tres sub-scores por canal.

    text_channel: 'lexical' | 'semantic' | 'hybrid' -> elige qué score textual
    entra en la fusión (lee selected_text_score con los flags correspondientes).
    """
    from app.services.evaluation import (
        prepare_corpus, family_split, _split_distractors,
    )
    from app.services.fingerprint import compare_fingerprints

    use_semantic = text_channel == "semantic"
    use_hybrid = text_channel == "hybrid"

    transformations = transformations or [
        "drop_fields",
        "mask_pii",
        "combo_strong",
        "visual_strong",
    ]

    corpus = prepare_corpus(
        n_legit=n_legit,
        n_distractors=n_distractors,
        seed=seed,
        transformations=transformations,
        decouple_visual_seed=True,
        distractor_profiles=[
            "random_different_identity",
            "same_type_different_identity",
            "same_identity_different_document",
            "same_identity_same_type_modified_context",
        ],
    )

    references = corpus["references"]
    ref_ids = [r["document_id"] for r in references]
    ref_index = {rid: i for i, rid in enumerate(ref_ids)}

    splits = family_split(ref_ids, 0.2, 0.2, seed)
    dist_splits = _split_distractors(corpus["distractor_queries"], 0.2, seed)

    def subscores(query_fp):
        T = np.empty(len(references)); L = np.empty(len(references)); P = np.empty(len(references))
        for i, ref in enumerate(references):
            sc = compare_fingerprints(query_fp, ref["fingerprint"], 1.0, 1.0, 1.0,
                                      use_semantic_text=use_semantic, use_hybrid_text=use_hybrid)
            T[i] = sc["selected_text_score"]; L[i] = sc["layout_score"]; P[i] = sc["pii_score"]
        return T, L, P

    var_T, var_L, var_P, var_truth = [], [], [], []
    for case in corpus["variant_cases"]:
        if case["family"] not in splits["test"]:
            continue
        T, L, P = subscores(case["fingerprint"])
        var_T.append(T); var_L.append(L); var_P.append(P)
        var_truth.append(ref_index[case["ground_truth_document_id"]])

    dist_T, dist_L, dist_P, dist_profiles = [], [], [], []
    for d in corpus["distractor_queries"]:
        if d["distractor_id"] not in dist_splits["test"]:
            continue
        T, L, P = subscores(d["fingerprint"])
        dist_T.append(T); dist_L.append(L); dist_P.append(P)
        dist_profiles.append(d.get("profile", d.get("distractor_profile", "unknown")))

    return {
        "text_channel": text_channel,
        "ref_ids": ref_ids,
        "var_T": var_T, "var_L": var_L, "var_P": var_P, "var_truth_idx": var_truth,
        "dist_T": dist_T, "dist_L": dist_L, "dist_P": dist_P, "dist_profiles": dist_profiles,
        "n_test_variants": len(var_T), "n_test_distractors": len(dist_T),
    }


# --------------------------------------------------------------------------- #
# Orquestación + reporte
# --------------------------------------------------------------------------- #
def run_sensitivity(n_legit: int = 100, n_distractors: int = 200, seed: int = 42,
                    step: float = 0.05, text_channel: str = "lexical",
                    out_prefix: str = "weight_sensitivity") -> dict:
    cache = build_subscore_cache(text_channel, n_legit, n_distractors, seed)
    records = sweep(cache, step)
    tol = 1.0 / max(cache["n_test_variants"], 1)  # 1 caso de tolerancia
    plat = plateau(records, tol)
    det = best_for_detection(records)

    # CSV de la superficie completa (para graficar el símplex)
    csv_path = Path(f"{out_prefix}_{text_channel}.csv")
    with csv_path.open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(records[0].keys()))
        wr.writeheader(); wr.writerows(records)

    corners = {
        "text_only": (1.0, 0.0, 0.0), "layout_only": (0.0, 1.0, 0.0), "pii_only": (0.0, 0.0, 1.0),
        "text_layout(no_pii)": (0.5, 0.5, 0.0), "text_pii(no_layout)": (0.5, 0.0, 0.5),
        "equal_thirds": (round(1/3, 4), round(1/3, 4), round(1/3, 4)),
    }
    corner_rows = []
    for name, w in corners.items():
        r1, mrr = _rank_metrics(cache, w); auc = _detection_auc(cache, w)
        corner_rows.append({"config": name, "w": w, "recall_at_1": round(r1, 4),
                            "mrr": round(mrr, 4), "detection_auc": round(auc, 4) if auc else None})

    report = {
        "text_channel": text_channel,
        "n_test_variants": cache["n_test_variants"],
        "n_test_distractors": cache["n_test_distractors"],
        "ranking_plateau": plat,
        "best_for_detection": det,
        "corners": corner_rows,
        "surface_csv": str(csv_path),
    }
    Path(f"{out_prefix}_{text_channel}_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n=== Sensibilidad de pesos (canal texto={text_channel}) ===")
    print(f"n_test_variants={cache['n_test_variants']}  n_test_distractors={cache['n_test_distractors']}")
    print(f"\n[Ranking] Mejor Recall@1={plat['best_recall_at_1']}  |  MESETA (tol={tol:.4f}):")
    print(f"  configs casi-óptimas: {plat['n_near_optimal_configs']} de {plat['n_total_configs']}")
    print(f"  rango de pesos en la meseta: {plat['weight_ranges_in_plateau']}")
    print(f"  -> si los rangos son anchos, los pesos NO son identificables.")
    print(f"\n[Detección] Mejor AUC: {det.get('detection_auc')} en "
          f"(t={det.get('w_text')}, l={det.get('w_layout')}, p={det.get('w_pii')})")
    print(f"  AUC dentro de la meseta de ranking: {plat['auc_range_in_plateau']}")
    print("\n[Esquinas]")
    for r in corner_rows:
        print(f"  {r['config']:22s} R@1={r['recall_at_1']:.4f}  MRR={r['mrr']:.4f}  AUC={r['detection_auc']}")
    print(f"\nSuperficie completa -> {csv_path}")
    return report


# --------------------------------------------------------------------------- #
# Self-test de la lógica pura (sin dependencias del motor)
# --------------------------------------------------------------------------- #
def _synthetic_cache(seed: int = 0) -> dict:
    """Cache sintético que imita el fenómeno observado: el texto separa bien
    (variante verdadera tiene texto alto), el PII es alto tanto para la variante
    verdadera como para distractores 'misma identidad' (envenena la detección),
    y el layout es ruido débil. Sirve para validar que el harness reproduce que
    subir w_pii NO mejora ranking pero HUNDE el AUC."""
    rng = np.random.default_rng(seed)
    n_ref = 10
    var_T, var_L, var_P, truth = [], [], [], []
    for q in range(40):
        t = rng.uniform(0.10, 0.45, n_ref); l = rng.uniform(0.1, 0.5, n_ref); p = rng.uniform(0.0, 0.1, n_ref)
        gt = q % n_ref
        # Texto separa a la verdadera para RANKING, pero su pico (0.55-0.65) se
        # solapa con el max textual de los distractores -> detección por texto
        # buena pero no perfecta.
        t[gt] = 0.55 + rng.uniform(0, 0.10)
        # ~60% conservan PII (0.9); ~40% 'enmascaradas' -> PII no separa (mirror real).
        p[gt] = 0.90 if rng.random() < 0.6 else rng.uniform(0.0, 0.1)
        var_T.append(t); var_L.append(l); var_P.append(p); truth.append(gt)
    dist_T, dist_L, dist_P = [], [], []
    for q in range(40):
        t = rng.uniform(0.10, 0.50, n_ref); l = rng.uniform(0.1, 0.5, n_ref); p = rng.uniform(0.0, 0.1, n_ref)
        # Distractor 'misma identidad': PII MUY alto contra un ref -> su max_score
        # con PII supera al de las variantes verdaderas (envenena la detección).
        p[q % n_ref] = 0.97
        dist_T.append(t); dist_L.append(l); dist_P.append(p)
    return {"var_T": var_T, "var_L": var_L, "var_P": var_P, "var_truth_idx": truth,
            "dist_T": dist_T, "dist_L": dist_L, "dist_P": dist_P,
            "n_test_variants": 40, "n_test_distractors": 40}


def _selftest() -> None:
    cache = _synthetic_cache()
    print("== Self-test lógica pura (cache sintético) ==")
    for name, w in [("text_only", (1, 0, 0)), ("text_layout", (0.5, 0.5, 0.0)),
                    ("text_pii", (0.5, 0.0, 0.5)), ("pii_only", (0, 0, 1)),
                    ("equal", (1/3, 1/3, 1/3))]:
        r1, mrr = _rank_metrics(cache, w); auc = _detection_auc(cache, w)
        print(f"  {name:12s} R@1={r1:.3f} MRR={mrr:.3f} AUC={auc:.3f}")
    recs = sweep(cache, step=0.1)
    plat = plateau(recs, tol=1/40)
    det = best_for_detection(recs)
    print(f"\n  Meseta ranking: best R@1={plat['best_recall_at_1']:.3f}, "
          f"{plat['n_near_optimal_configs']}/{plat['n_total_configs']} configs casi-óptimas")
    print(f"  rango w_pii en meseta: {plat['weight_ranges_in_plateau']['w_pii']} "
          f"(ancho => no identificable)")
    print(f"  Mejor para detección: AUC={det['detection_auc']:.3f} con w_pii={det['w_pii']} "
          f"(esperado w_pii bajo)")


if __name__ == "__main__":
    try:
        # Si el motor está disponible, correr el barrido real:
        from app.services.evaluation import prepare_corpus  # noqa: F401
        run_sensitivity()
    except Exception as exc:
        print(f"[motor no disponible: {type(exc).__name__}] corriendo self-test de lógica pura\n")
        _selftest()
