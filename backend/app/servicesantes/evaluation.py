# =============================================================================
# evaluation.py  ·  motor de evaluación forense (fuente única de verdad)
# -----------------------------------------------------------------------------
# Reescritura integral alineada al protocolo. Resuelve los hallazgos de la
# revisión metodológica:
#   - FPR operativo sobre DISTRACTORES (§5.1), no FPR por par.
#   - Split POR FAMILIA: el umbral/pesos se ajustan en dev y se reportan en
#     test (familias disjuntas) -> sin fuga (C4).
#   - Umbral por método vía Youden's J sobre el score de decisión = max score
#     sobre el índice (§4.5), comparable entre métodos de distinta escala.
#   - IC 95% por bootstrap A NIVEL DE CASO (no de par) en Recall@1/5, MRR, AUC.
#   - Significancia G vs E: McNemar (Recall@1) y Wilcoxon (reciprocal rank).
#   - Baseline TLSH sobre TEXTO extraído (no bytes) + SHA-256 como cota inferior.
#   - METHODS unificado y derivado del protocolo (PII 0.45 / texto 0.35 /
#     layout 0.20); las combinaciones parciales renormalizan esos ratios.
#   - Texto del método propuesto = HÍBRIDO (léxico + SBERT); la ablación de
#     modalidades mantiene la codificación de texto constante (híbrida) para
#     que G vs E sea apples-to-apples.
#   - AUC nunca se enmascara a 0.5: si no es computable, devuelve None.
#
# NO ejecutable sin reportlab / PyMuPDF / sentence-transformers / scipy /
# sklearn / (opcional) python-tlsh. Requiere smoke test en entorno del grupo.
# =============================================================================

import math
import json
import hashlib
import random as _random
from time import perf_counter
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, Any, List, Callable, Optional, Tuple

import numpy as np

from app.services.extractor import extract_text, extract_layout_blocks
from app.services.pii_detector import detect_pii_masked
from app.services.fingerprint import build_fingerprint, strip_boilerplate
from app.services.matcher import (
    add_reference_document,
    clear_reference_index,
    match_all_references,
)
from app.services.synthetic_generator import (
    set_global_seed,
    generate_synthetic_pdfs,
    generate_distractor_pdfs,
)
from app.services.variant_generator import (
    generate_variant_from_pdf,
    TRANSFORMATION_TYPES,
    PROTOCOL_TRANSFORMATION_MAP,
)

try:
    from app.services.doc_seed_decoupling import generate_variant_decoupled
except Exception:
    generate_variant_decoupled = None


# ----- dependencias estadísticas (presentes junto a sklearn) ---------------- #
try:
    from sklearn.metrics import roc_auc_score
    _SKLEARN = True
except Exception:
    _SKLEARN = False

try:
    from scipy.stats import wilcoxon, binomtest
    _SCIPY = True
except Exception:
    _SCIPY = False

# ----- baseline TLSH (opcional; pip puro, sin libs C) ----------------------- #
try:
    import tlsh
    _TLSH = True
except Exception:
    _TLSH = False

TLSH_DIFF_CAP = 300.0  # diff TLSH -> similitud en [0,1] = 1 - min(diff,CAP)/CAP


# --------------------------------------------------------------------------- #
# METHODS: fuente única de verdad, derivada del protocolo
# --------------------------------------------------------------------------- #
_W = {"pii": 0.45, "text": 0.35, "layout": 0.20}  # referencia §1.2 / §4.4


def _renorm(*keys: str) -> Dict[str, float]:
    s = sum(_W[k] for k in keys)
    return {k: _W[k] / s for k in keys}


def _fp_method(w_text=0.0, w_layout=0.0, w_pii=0.0, use_hybrid_text=False,
               use_semantic_text=False, description="") -> Dict[str, Any]:
    return {
        "type": "fingerprint",
        "w_text": w_text, "w_layout": w_layout, "w_pii": w_pii,
        "use_hybrid_text": use_hybrid_text, "use_semantic_text": use_semantic_text,
        "description": description,
    }


def build_methods() -> Dict[str, Dict[str, Any]]:
    tl = _renorm("text", "layout")
    tp = _renorm("text", "pii")
    lp = _renorm("layout", "pii")
    return {
        # --- baselines ---
        "sha256_exact": {"type": "hash", "description": "SHA-256 exacto (cota inferior)."},
        "tlsh_text": {"type": "tlsh", "description": "TLSH sobre texto extraído normalizado."},
        # --- ablación de modalidades (texto = HÍBRIDO constante) ---
        "text_only": _fp_method(1.0, 0.0, 0.0, use_hybrid_text=True,
                                 description="A: solo texto (híbrido)."),
        "layout_only": _fp_method(0.0, 1.0, 0.0,
                                   description="C: solo layout."),
        "pii_only": _fp_method(0.0, 0.0, 1.0,
                               description="B: solo PII."),
        "text_layout": _fp_method(tl["text"], tl["layout"], 0.0, use_hybrid_text=True,
                                  description="D: texto + layout (sin PII)."),
        "text_pii": _fp_method(tp["text"], 0.0, tp["pii"], use_hybrid_text=True,
                               description="E: texto + PII (sin layout)."),
        "layout_pii": _fp_method(0.0, lp["layout"], lp["pii"],
                                 description="F: layout + PII (sin texto)."),
        "multimodal": _fp_method(_W["text"], _W["layout"], _W["pii"], use_hybrid_text=True,
                                 description="G: huella multimodal propuesta (texto híbrido)."),
        # --- estudio de codificación de texto (§4.1), secundario ---
        "multimodal_lexical": _fp_method(_W["text"], _W["layout"], _W["pii"],
                                         description="G con texto solo léxico (TF)."),
        "multimodal_semantic": _fp_method(_W["text"], _W["layout"], _W["pii"],
                                          use_semantic_text=True,
                                          description="G con texto solo SBERT."),
    }


PROPOSED_METHOD = "multimodal"      # G
NO_LAYOUT_METHOD = "text_pii"       # E  (para la prueba de aporte del layout)


# --------------------------------------------------------------------------- #
# Hashing / fingerprinting auxiliar
# --------------------------------------------------------------------------- #
def compute_sha256(file_path: str) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _normalized_text_for_tlsh(text: str) -> str:
    return " ".join(strip_boilerplate(text).split())


def compute_tlsh(text: str) -> Optional[str]:
    if not _TLSH:
        return None
    payload = _normalized_text_for_tlsh(text).encode("utf-8", errors="ignore")
    if len(payload) < 50:  # TLSH requiere un mínimo de entrada
        return None
    try:
        return tlsh.hash(payload)
    except Exception:
        return None


def _tlsh_similarity(h1: Optional[str], h2: Optional[str]) -> float:
    if not h1 or not h2:
        return 0.0
    diff = tlsh.diff(h1, h2)
    return max(0.0, 1.0 - min(float(diff), TLSH_DIFF_CAP) / TLSH_DIFF_CAP)


# --------------------------------------------------------------------------- #
# Construcción del corpus (índice completo + distractores + variantes)
# --------------------------------------------------------------------------- #
def _fingerprint_for_path(path: str) -> Tuple[Dict[str, Any], str]:
    text = extract_text(path)
    pii = detect_pii_masked(text)
    layout = extract_layout_blocks(path)
    return build_fingerprint(text, pii, layout), text


def _case_seed(base_seed: int, document_id: str, transformation: str) -> int:
    """Semilla determinista por caso. Evita que todas las variantes compartan
    la misma semilla global y permite comparar A/B de forma reproducible."""
    payload = f"CASE|{base_seed}|{document_id}|{transformation}"
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8], 16)



def prepare_corpus(n_legit: int, n_distractors: int, seed: int,
                   transformations: List[str],
                   decouple_visual_seed: bool = False,
                   distractor_profiles: List[str] | None = None) -> Dict[str, Any]:
    """Genera el corpus completo, construye el ?ndice con TODOS los leg?timos
    y arma variantes + distractores como queries.

    Distractores perfilados:
      - random_different_identity: documento independiente.
      - same_type_different_identity: mismo tipo documental, otra identidad.
      - same_identity_different_document: misma identidad, otro tipo documental.
      - same_identity_same_type_modified_context: misma identidad y tipo, contexto modificado.
    """
    import copy
    from uuid import uuid4

    from app.services.synthetic_generator import (
        DOCUMENT_TYPES,
        DISTRACTOR_OUTPUT_DIR,
        build_person_data,
        load_document_metadata,
        render_document_from_data,
        random_money,
        random_date,
        random_bank_account,
        _metadata_path_for,
    )

    if distractor_profiles is None:
        distractor_profiles = [
            "random_different_identity",
            "same_type_different_identity",
            "same_identity_different_document",
            "same_identity_same_type_modified_context",
        ]

    set_global_seed(seed)
    clear_reference_index()

    # --- leg?timos -> ?ndice completo ---
    legit_docs = generate_synthetic_pdfs(n_legit, seed=seed)
    references = []
    for doc in legit_docs:
        fp, text = _fingerprint_for_path(doc["path"])
        ref = {
            "document_id": doc["document_id"],
            "filename": doc["filename"],
            "stored_path": doc["path"],
            "fingerprint": fp,
            "text": text,
            "tlsh": compute_tlsh(text),
            "sha256": compute_sha256(doc["path"]),
        }
        add_reference_document(ref)
        references.append(ref)

    # --- variantes (queries con match verdadero) ---
    variant_cases = []
    for ref in references:
        for transformation in transformations:
            case_seed = _case_seed(seed, ref["document_id"], transformation)

            if decouple_visual_seed:
                if generate_variant_decoupled is None:
                    raise RuntimeError(
                        "decouple_visual_seed=True requiere app.services.doc_seed_decoupling"
                    )
                variant = generate_variant_decoupled(
                    ref["stored_path"],
                    transformation,
                    case_seed=case_seed,
                    parent_doc_id=ref["document_id"],
                )
            else:
                variant = generate_variant_from_pdf(
                    ref["stored_path"],
                    transformation,
                    seed=case_seed,
                )

            fp, text = _fingerprint_for_path(variant["variant_path"])
            variant_cases.append({
                "case_key": f"{ref['document_id']}::{transformation}",
                "family": ref["document_id"],
                "ground_truth_document_id": ref["document_id"],
                "transformation_type": transformation,
                "protocol_id": PROTOCOL_TRANSFORMATION_MAP.get(transformation, transformation),
                "variant_path": variant["variant_path"],
                "fingerprint": fp,
                "text": text,
                "tlsh": compute_tlsh(text),
                "visual_seed_decoupled": bool(variant.get("visual_seed_decoupled", False)),
                "visual_seed": variant.get("visual_seed"),
            })

    # --- distractores perfilados (queries SIN match verdadero) ---
    distractor_queries = []
    DISTRACTOR_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for i in range(n_distractors):
        profile = distractor_profiles[i % len(distractor_profiles)]
        parent_ref = references[i % len(references)]
        parent_meta = load_document_metadata(parent_ref["stored_path"]) or {}
        parent_data = copy.deepcopy(parent_meta.get("data") or build_person_data())
        parent_type = parent_meta.get("document_type") or DOCUMENT_TYPES[i % len(DOCUMENT_TYPES)]
        parent_doc_id = parent_ref["document_id"]

        d_seed = _case_seed(seed, parent_doc_id, f"DISTRACTOR|{profile}|{i}")

        if profile == "random_different_identity":
            data = build_person_data()
            document_type = DOCUMENT_TYPES[i % len(DOCUMENT_TYPES)]

        elif profile == "same_type_different_identity":
            data = build_person_data()
            document_type = parent_type

        elif profile == "same_identity_different_document":
            data = copy.deepcopy(parent_data)
            current_index = DOCUMENT_TYPES.index(parent_type) if parent_type in DOCUMENT_TYPES else 0
            document_type = DOCUMENT_TYPES[(current_index + 1) % len(DOCUMENT_TYPES)]

        elif profile == "same_identity_same_type_modified_context":
            data = copy.deepcopy(parent_data)
            document_type = parent_type
            data["amount"] = random_money()
            data["date"] = random_date()
            data["account"] = random_bank_account()
            data["operation_code"] = f"OP-{d_seed % 900000 + 100000}"

        else:
            data = build_person_data()
            document_type = DOCUMENT_TYPES[i % len(DOCUMENT_TYPES)]

        short = {
            "random_different_identity": "RAND",
            "same_type_different_identity": "TYPE",
            "same_identity_different_document": "ID-DOC",
            "same_identity_same_type_modified_context": "ID-CTX",
        }.get(profile, "UNK")

        doc_code = f"DIST-{short}-{i+1:04d}"
        filename = f"{doc_code}_{document_type}_{uuid4().hex[:8]}.pdf"
        output_path = DISTRACTOR_OUTPUT_DIR / filename

        render_document_from_data(
            data,
            document_type,
            doc_code,
            str(output_path),
            doc_seed=d_seed,
        )

        metadata = {
            "document_id": filename,
            "filename": filename,
            "path": str(output_path),
            "document_type": document_type,
            "doc_code": doc_code,
            "document_role": "distractor",
            "distractor_profile": profile,
            "source_parent_document_id": parent_doc_id,
            "doc_seed": d_seed,
            "data": data,
        }

        with _metadata_path_for(output_path).open("w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        fp, text = _fingerprint_for_path(str(output_path))
        distractor_queries.append({
            "distractor_id": filename,
            "path": str(output_path),
            "fingerprint": fp,
            "text": text,
            "tlsh": compute_tlsh(text),
            "profile": profile,
            "source_parent_document_id": parent_doc_id,
            "document_type": document_type,
        })

    return {
        "references": references,
        "variant_cases": variant_cases,
        "distractor_queries": distractor_queries,
    }


# --------------------------------------------------------------------------- #
# Ranking por método
# --------------------------------------------------------------------------- #
def _rank(method: Dict[str, Any], query: Dict[str, Any],
          references: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    mtype = method["type"]

    if mtype == "fingerprint":
        return match_all_references(
            query_fingerprint=query["fingerprint"],
            w_text=method["w_text"], w_layout=method["w_layout"], w_pii=method["w_pii"],
            use_semantic_text=method.get("use_semantic_text", False),
            use_hybrid_text=method.get("use_hybrid_text", False),
        )

    if mtype == "tlsh":
        scored = [
            {"document_id": r["document_id"], "score": _tlsh_similarity(query.get("tlsh"), r.get("tlsh"))}
            for r in references
        ]
    elif mtype == "hash":
        q_sha = compute_sha256(query["_path"])
        scored = [
            {"document_id": r["document_id"], "score": 1.0 if q_sha == r["sha256"] else 0.0}
            for r in references
        ]
    else:
        raise ValueError(f"Tipo de método no soportado: {mtype}")

    scored.sort(key=lambda x: (-x["score"], hashlib.md5(x["document_id"].encode()).hexdigest()))
    return [{"document_id": s["document_id"], "scores": {"final_score": s["score"]}} for s in scored]


def _max_score(matches: List[Dict[str, Any]]) -> float:
    return matches[0]["scores"]["final_score"] if matches else 0.0


def _rank_position(matches, target) -> Optional[int]:
    for i, m in enumerate(matches, start=1):
        if m["document_id"] == target:
            return i
    return None


# --------------------------------------------------------------------------- #
# Evaluación de un método sobre todas las queries
# --------------------------------------------------------------------------- #
def evaluate_method(method_name: str, method: Dict[str, Any],
                    corpus: Dict[str, Any], top_k: int = 5) -> Dict[str, Any]:
    references = corpus["references"]

    variant_records: Dict[str, Dict[str, Any]] = {}
    latencies = []

    for case in corpus["variant_cases"]:
        query = dict(case)
        query["_path"] = case["variant_path"]
        t0 = perf_counter()
        matches = _rank(method, query, references)
        latencies.append((perf_counter() - t0) * 1000)

        score_values = [
            float(m.get("scores", {}).get("final_score", 0.0))
            for m in matches
        ]
        score_values_sorted = sorted(score_values, reverse=True)
        max_score = score_values_sorted[0] if score_values_sorted else 0.0
        second_score = score_values_sorted[1] if len(score_values_sorted) > 1 else 0.0
        margin_score = max_score - second_score

        pos = None if max_score == 0.0 else _rank_position(matches, case["ground_truth_document_id"])
        variant_records[case["case_key"]] = {
            "family": case["family"],
            "transformation_type": case["transformation_type"],
            "protocol_id": case["protocol_id"],
            "rank_position": pos,
            "top1": pos == 1,
            "top5": pos is not None and pos <= top_k,
            "reciprocal_rank": (1.0 / pos) if pos else 0.0,
            "max_score": max_score,
            "second_score": second_score,
            "margin_score": margin_score,
            "all_zero": max_score == 0.0,
        }

    distractor_max: Dict[str, float] = {}
    distractor_margin: Dict[str, float] = {}
    distractor_profile: Dict[str, str] = {}

    for d in corpus["distractor_queries"]:
        query = dict(d)
        query["_path"] = d["path"]
        matches = _rank(method, query, references)

        score_values = [
            float(m.get("scores", {}).get("final_score", 0.0))
            for m in matches
        ]
        score_values_sorted = sorted(score_values, reverse=True)
        max_score = score_values_sorted[0] if score_values_sorted else 0.0
        second_score = score_values_sorted[1] if len(score_values_sorted) > 1 else 0.0

        distractor_max[d["distractor_id"]] = max_score
        distractor_margin[d["distractor_id"]] = max_score - second_score
        distractor_profile[d["distractor_id"]] = d.get("profile", "unknown")

    return {
        "method": method_name,
        "description": method.get("description", ""),
        "variant_records": variant_records,
        "distractor_max": distractor_max,
        "distractor_margin": distractor_margin,
        "distractor_profile": distractor_profile,
        "avg_latency_ms": round(float(np.mean(latencies)), 2) if latencies else 0.0,
        "p95_latency_ms": round(float(np.percentile(latencies, 95)), 2) if latencies else 0.0,
    }


# --------------------------------------------------------------------------- #
# Split por familia (sin fuga): dev (ajuste) vs test (reporte)
# --------------------------------------------------------------------------- #
def family_split(reference_ids: List[str], test_fraction: float, val_fraction: float,
                 seed: int) -> Dict[str, set]:
    ids = list(reference_ids)
    rng = _random.Random(seed)
    rng.shuffle(ids)

    n = len(ids)
    n_test = max(1, int(round(n * test_fraction)))
    test = set(ids[:n_test])
    dev = ids[n_test:]

    # val (umbral) dentro de dev; el resto es train (grid de pesos en grid_search)
    n_val = max(1, int(round(n * val_fraction)))
    val = set(dev[:n_val])
    train = set(dev[n_val:]) if len(dev) > n_val else set(dev)
    return {"train": train, "val": val, "test": test, "dev": set(dev)}


def _split_distractors(distractors, test_fraction: float, seed: int):
    """Split de distractores. Si recibe dicts con profile, estratifica por perfil."""
    if not distractors:
        return {"test": set(), "dev": set()}

    if isinstance(distractors[0], dict):
        by_profile = defaultdict(list)
        for d in distractors:
            by_profile[d.get("profile", "unknown")].append(d["distractor_id"])

        test, dev = set(), set()
        rng = _random.Random(seed + 7)

        for profile, ids in sorted(by_profile.items()):
            ids = list(ids)
            rng.shuffle(ids)
            n_test = max(1, int(round(len(ids) * test_fraction)))
            test.update(ids[:n_test])
            dev.update(ids[n_test:])

        return {"test": test, "dev": dev}

    ids = list(distractors)
    _random.Random(seed + 7).shuffle(ids)
    n_test = max(1, int(round(len(ids) * test_fraction)))
    return {"test": set(ids[:n_test]), "dev": set(ids[n_test:])}


# --------------------------------------------------------------------------- #
# Umbral por Youden y métricas con IC bootstrap (nivel de caso)
# --------------------------------------------------------------------------- #
def youden_threshold(pos_scores: List[float], neg_scores: List[float]) -> Optional[float]:
    """Umbral que maximiza TPR - FPR sobre el score de decisión (max score sobre
    el índice). pos = variantes (deben superar el umbral), neg = distractores."""
    if not pos_scores or not neg_scores:
        return None
    candidates = sorted(set(pos_scores + neg_scores))
    best_thr, best_j = candidates[0], -1.0
    P, N = len(pos_scores), len(neg_scores)
    for thr in candidates:
        tpr = sum(1 for s in pos_scores if s >= thr) / P
        fpr = sum(1 for s in neg_scores if s >= thr) / N
        j = tpr - fpr
        if j > best_j:
            best_j, best_thr = j, thr
    return float(best_thr)


def _bootstrap_ci(values: List[float], stat_fn: Callable[[List[float]], float],
                  iters: int, seed: int) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if not values:
        return None, None, None
    rng = np.random.default_rng(seed)
    arr = np.array(values, dtype=float)
    n = len(arr)
    point = stat_fn(arr.tolist())
    boots = []
    for _ in range(iters):
        sample = arr[rng.integers(0, n, n)]
        boots.append(stat_fn(sample.tolist()))
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return round(float(point), 4), round(float(lo), 4), round(float(hi), 4)


def _auc(labels: List[int], scores: List[float]) -> Optional[float]:
    """AUC de DETECCIÓN: separar variantes (1) de distractores (0) por el max
    score sobre el índice. Independiente por query. Devuelve None si no es
    computable (nunca se enmascara a 0.5)."""
    if not _SKLEARN or len(set(labels)) < 2:
        return None
    try:
        return float(roc_auc_score(labels, scores))
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Resumen por método sobre el split de test (con IC) + matriz por transformación
# --------------------------------------------------------------------------- #
def summarize_method(eval_result: Dict[str, Any], splits: Dict[str, set],
                     dist_splits: Dict[str, set], bootstrap_iters: int,
                     seed: int) -> Dict[str, Any]:
    vr = eval_result["variant_records"]
    dmax = eval_result["distractor_max"]
    dmargin = eval_result.get("distractor_margin", {})
    dprofile = eval_result.get("distractor_profile", {})

    def vrecords(split_name):
        return [r for k, r in vr.items() if r["family"] in splits[split_name]]

    val_v = vrecords("val")
    test_v = vrecords("test")

    val_d = [s for did, s in dmax.items() if did in dist_splits["dev"]]
    test_d = [s for did, s in dmax.items() if did in dist_splits["test"]]

    val_d_margin = [s for did, s in dmargin.items() if did in dist_splits["dev"]]
    test_d_margin = [s for did, s in dmargin.items() if did in dist_splits["test"]]

    thr = youden_threshold([r["max_score"] for r in val_v], val_d)
    thr_margin = youden_threshold([r.get("margin_score", 0.0) for r in val_v], val_d_margin)

    r1 = _bootstrap_ci(
        [1.0 if r["top1"] else 0.0 for r in test_v],
        lambda v: float(np.mean(v)) if v else 0.0,
        bootstrap_iters,
        seed,
    )
    r5 = _bootstrap_ci(
        [1.0 if r["top5"] else 0.0 for r in test_v],
        lambda v: float(np.mean(v)) if v else 0.0,
        bootstrap_iters,
        seed + 1,
    )
    mrr = _bootstrap_ci(
        [r["reciprocal_rank"] for r in test_v],
        lambda v: float(np.mean(v)) if v else 0.0,
        bootstrap_iters,
        seed + 2,
    )

    if thr is not None:
        pos_pred = [
            (r["max_score"] > 0.0 and r["max_score"] >= thr)
            for r in test_v
        ]
        neg_pred = [
            (s > 0.0 and s >= thr)
            for s in test_d
        ]

        tp = sum(1 for pred in pos_pred if pred)
        fn = sum(1 for pred in pos_pred if not pred)
        fp = sum(1 for pred in neg_pred if pred)
        tn = sum(1 for pred in neg_pred if not pred)

        fpr = (fp / (fp + tn)) if (fp + tn) else None
        detection_rate = (tp / (tp + fn)) if (tp + fn) else None
        precision_operating = (tp / (tp + fp)) if (tp + fp) else None
        specificity = (tn / (tn + fp)) if (tn + fp) else None
    else:
        tp = fn = fp = tn = None
        fpr = detection_rate = precision_operating = specificity = None

    if thr_margin is not None:
        pos_pred_margin = [
            (r.get("margin_score", 0.0) > 0.0 and r.get("margin_score", 0.0) >= thr_margin)
            for r in test_v
        ]
        neg_pred_margin = [
            (s > 0.0 and s >= thr_margin)
            for s in test_d_margin
        ]

        tp_margin = sum(1 for pred in pos_pred_margin if pred)
        fn_margin = sum(1 for pred in pos_pred_margin if not pred)
        fp_margin = sum(1 for pred in neg_pred_margin if pred)
        tn_margin = sum(1 for pred in neg_pred_margin if not pred)

        fpr_margin = (fp_margin / (fp_margin + tn_margin)) if (fp_margin + tn_margin) else None
        detection_rate_margin = (
            tp_margin / (tp_margin + fn_margin)
        ) if (tp_margin + fn_margin) else None
        precision_operating_margin = (
            tp_margin / (tp_margin + fp_margin)
        ) if (tp_margin + fp_margin) else None
        specificity_margin = (
            tn_margin / (tn_margin + fp_margin)
        ) if (tn_margin + fp_margin) else None
    else:
        tp_margin = fn_margin = fp_margin = tn_margin = None
        fpr_margin = detection_rate_margin = precision_operating_margin = specificity_margin = None

    det_labels = [1] * len(test_v) + [0] * len(test_d)
    det_scores = [r["max_score"] for r in test_v] + list(test_d)
    auc = _auc(det_labels, det_scores)

    det_scores_margin = [r.get("margin_score", 0.0) for r in test_v] + list(test_d_margin)
    auc_margin = _auc(det_labels, det_scores_margin)

    # FPR/AUC desagregado por perfil de distractor.
    by_profile = defaultdict(list)
    for did, score in dmax.items():
        if did in dist_splits["test"]:
            by_profile[dprofile.get(did, "unknown")].append({
                "id": did,
                "max_score": score,
                "margin_score": dmargin.get(did, 0.0),
            })

    pos_scores_max = [r["max_score"] for r in test_v]
    pos_scores_margin = [r.get("margin_score", 0.0) for r in test_v]

    fpr_by_profile = []
    for profile, rows in sorted(by_profile.items()):
        neg_max = [r["max_score"] for r in rows]
        neg_margin = [r["margin_score"] for r in rows]

        fp_profile = (
            sum(1 for s in neg_max if s > 0.0 and s >= thr)
            if thr is not None else None
        )
        fp_margin_profile = (
            sum(1 for s in neg_margin if s > 0.0 and s >= thr_margin)
            if thr_margin is not None else None
        )

        fpr_profile = (
            fp_profile / len(neg_max)
            if fp_profile is not None and neg_max else None
        )
        fpr_margin_profile = (
            fp_margin_profile / len(neg_margin)
            if fp_margin_profile is not None and neg_margin else None
        )

        auc_profile = _auc(
            [1] * len(pos_scores_max) + [0] * len(neg_max),
            pos_scores_max + neg_max,
        )
        auc_margin_profile = _auc(
            [1] * len(pos_scores_margin) + [0] * len(neg_margin),
            pos_scores_margin + neg_margin,
        )

        fpr_by_profile.append({
            "profile": profile,
            "n_test_distractors": len(rows),
            "fp_max": fp_profile,
            "fpr_max": round(fpr_profile, 4) if fpr_profile is not None else None,
            "auc_max_vs_profile": round(auc_profile, 4) if auc_profile is not None else None,
            "mean_max_score": round(float(np.mean(neg_max)), 4) if neg_max else None,
            "fp_margin": fp_margin_profile,
            "fpr_margin": round(fpr_margin_profile, 4) if fpr_margin_profile is not None else None,
            "auc_margin_vs_profile": round(auc_margin_profile, 4) if auc_margin_profile is not None else None,
            "mean_margin_score": round(float(np.mean(neg_margin)), 4) if neg_margin else None,
        })

    by_t = defaultdict(list)
    for r in test_v:
        by_t[r["transformation_type"]].append(r)

    matrix = []
    for t, group in sorted(by_t.items()):
        matrix.append({
            "transformation_type": t,
            "protocol_id": group[0]["protocol_id"],
            "recall_at_1": round(float(np.mean([1.0 if g["top1"] else 0.0 for g in group])), 4),
            "recall_at_5": round(float(np.mean([1.0 if g["top5"] else 0.0 for g in group])), 4),
            "mrr": round(float(np.mean([g["reciprocal_rank"] for g in group])), 4),
            "n": len(group),
        })

    return {
        "method": eval_result["method"],
        "description": eval_result["description"],
        "threshold": round(thr, 4) if thr is not None else None,
        "threshold_margin": round(thr_margin, 4) if thr_margin is not None else None,
        "threshold_policy": "youden_j_calibrated_on_validation",
        "threshold_source": "validation_variants_vs_dev_distractors",
        "operating_score_primary": "max_score",
        "operating_score_alternative": "margin_score_top1_minus_top2",
        "ranking_metrics_threshold_independent": True,
        "threshold_validation_cases": {
            "positive_variants_val": len(val_v),
            "negative_distractors_dev": len(val_d),
        },
        "confusion_matrix": {
            "tp": tp,
            "fn": fn,
            "fp": fp,
            "tn": tn,
            "positive_class": "variant_with_reference_match",
            "negative_class": "distractor_without_reference_match",
            "score_used": "max_score",
        },
        "confusion_matrix_margin": {
            "tp": tp_margin,
            "fn": fn_margin,
            "fp": fp_margin,
            "tn": tn_margin,
            "positive_class": "variant_with_reference_match",
            "negative_class": "distractor_without_reference_match",
            "score_used": "margin_score_top1_minus_top2",
        },
        "recall_at_1": r1[0],
        "recall_at_1_ci": [r1[1], r1[2]],
        "recall_at_5": r5[0],
        "recall_at_5_ci": [r5[1], r5[2]],
        "mrr": mrr[0],
        "mrr_ci": [mrr[1], mrr[2]],
        "fpr": round(fpr, 4) if fpr is not None else None,
        "detection_rate": round(detection_rate, 4) if detection_rate is not None else None,
        "precision_operating": round(precision_operating, 4) if precision_operating is not None else None,
        "specificity": round(specificity, 4) if specificity is not None else None,
        "fpr_margin": round(fpr_margin, 4) if fpr_margin is not None else None,
        "detection_rate_margin": round(detection_rate_margin, 4) if detection_rate_margin is not None else None,
        "precision_operating_margin": round(precision_operating_margin, 4) if precision_operating_margin is not None else None,
        "specificity_margin": round(specificity_margin, 4) if specificity_margin is not None else None,
        "auc_detection": round(auc, 4) if auc is not None else None,
        "auc_detection_margin": round(auc_margin, 4) if auc_margin is not None else None,
        "fpr_by_profile": fpr_by_profile,
        "avg_latency_ms": eval_result["avg_latency_ms"],
        "p95_latency_ms": eval_result["p95_latency_ms"],
        "n_test_cases": len(test_v),
        "n_test_distractors": len(test_d),
        "all_zero_test_cases": sum(1 for r in test_v if r["all_zero"]),
        "by_transformation": matrix,
    }


# --------------------------------------------------------------------------- #
# Significancia G vs E (pareada sobre casos de TEST)
# --------------------------------------------------------------------------- #
def compare_methods_significance(eval_g: Dict[str, Any], eval_e: Dict[str, Any],
                                 test_families: set, bootstrap_iters: int, seed: int) -> Dict[str, Any]:
    g, e = eval_g["variant_records"], eval_e["variant_records"]
    keys = [k for k in g if k in e and g[k]["family"] in test_families]

    g_hit = [1 if g[k]["top1"] else 0 for k in keys]
    e_hit = [1 if e[k]["top1"] else 0 for k in keys]
    g_rr = [g[k]["reciprocal_rank"] for k in keys]
    e_rr = [e[k]["reciprocal_rank"] for k in keys]

    # McNemar exacto sobre discordancias de Recall@1.
    b = sum(1 for gh, eh in zip(g_hit, e_hit) if gh == 1 and eh == 0)  # G acierta, E no
    c = sum(1 for gh, eh in zip(g_hit, e_hit) if gh == 0 and eh == 1)  # E acierta, G no
    mcnemar_p = None
    if _SCIPY and (b + c) > 0:
        mcnemar_p = float(binomtest(min(b, c), b + c, 0.5, alternative="two-sided").pvalue)

    # Wilcoxon signed-rank sobre reciprocal rank pareado.
    wilcoxon_p = None
    if _SCIPY and any(gr != er for gr, er in zip(g_rr, e_rr)):
        try:
            wilcoxon_p = float(wilcoxon(g_rr, e_rr, zero_method="wilcox").pvalue)
        except Exception:
            wilcoxon_p = None

    # IC bootstrap de la diferencia de Recall@1 (G - E), pareado por caso.
    diff = [gh - eh for gh, eh in zip(g_hit, e_hit)]
    d_point, d_lo, d_hi = _bootstrap_ci(
        [float(x) for x in diff], lambda v: float(np.mean(v)) if v else 0.0, bootstrap_iters, seed
    )

    return {
        "comparison": f"{eval_g['method']} (G) vs {eval_e['method']} (E)",
        "n_paired_cases": len(keys),
        "mcnemar_b_G_hits_E_miss": b,
        "mcnemar_c_E_hits_G_miss": c,
        "mcnemar_p_value": round(mcnemar_p, 6) if mcnemar_p is not None else None,
        "wilcoxon_p_value": round(wilcoxon_p, 6) if wilcoxon_p is not None else None,
        "recall_at_1_diff_G_minus_E": d_point,
        "recall_at_1_diff_ci": [d_lo, d_hi],
    }


# --------------------------------------------------------------------------- #
# Grid search de pesos (solo grid_search mode), sobre TRAIN
# --------------------------------------------------------------------------- #
def _recall_at_1_for_weights(cases, references, wt, wl, wp, use_hybrid_text) -> float:
    if not cases:
        return 0.0
    hits = 0
    for c in cases:
        matches = match_all_references(
            query_fingerprint=c["fingerprint"],
            w_text=wt, w_layout=wl, w_pii=wp, use_hybrid_text=use_hybrid_text,
        )
        if matches and matches[0]["document_id"] == c["ground_truth_document_id"]:
            hits += 1
    return hits / len(cases)


def grid_search_weights(corpus, train_families: set, step: float = 0.1) -> Dict[str, float]:
    references = corpus["references"]
    train_cases = [c for c in corpus["variant_cases"] if c["family"] in train_families]
    grid = [round(i * step, 4) for i in range(1, int(1 / step))]
    best, best_r = {"w_text": _W["text"], "w_layout": _W["layout"], "w_pii": _W["pii"]}, -1.0
    for wp in grid:
        for wt in grid:
            wl = round(1.0 - wp - wt, 4)
            if wl <= 0 or wl >= 1:
                continue
            r = _recall_at_1_for_weights(train_cases, references, wt, wl, wp, True)
            if r > best_r:
                best_r, best = r, {"w_text": wt, "w_layout": wl, "w_pii": wp}
    best["_train_recall_at_1"] = round(best_r, 4)
    return best


# --------------------------------------------------------------------------- #
# Orquestador
# --------------------------------------------------------------------------- #
DEFAULT_CONFIG = {
    "n_legit": 50,
    "n_distractors": 20,        # ~40% de n_legit (decisión B1)
    "seed": 42,
    "weight_mode": "fixed",     # "fixed" | "grid_search"
    "test_fraction": 0.2,
    "val_fraction": 0.2,
    "bootstrap_iters": 1000,
    "top_k": 5,
    "transformations": None,    # None -> TRANSFORMATION_TYPES (T1-T8 + combined)
}


def run_full_evaluation(**kwargs) -> Dict[str, Any]:
    cfg = {**DEFAULT_CONFIG, **kwargs}
    transformations = cfg["transformations"] or list(TRANSFORMATION_TYPES)

    corpus = prepare_corpus(
        cfg["n_legit"],
        cfg["n_distractors"],
        cfg["seed"],
        transformations,
        decouple_visual_seed=cfg.get("decouple_visual_seed", False),
        distractor_profiles=cfg.get("distractor_profiles"),
    )

    ref_ids = [r["document_id"] for r in corpus["references"]]
    splits = family_split(ref_ids, cfg["test_fraction"], cfg["val_fraction"], cfg["seed"])
    dist_splits = _split_distractors(
        corpus["distractor_queries"],
        cfg["test_fraction"],
        cfg["seed"],
    )

    methods = build_methods()

    # Grid search de pesos del método propuesto (si aplica), sobre TRAIN.
    tuned_weights = None
    if cfg["weight_mode"] == "grid_search":
        tuned_weights = grid_search_weights(corpus, splits["train"])
        methods[PROPOSED_METHOD]["w_text"] = tuned_weights["w_text"]
        methods[PROPOSED_METHOD]["w_layout"] = tuned_weights["w_layout"]
        methods[PROPOSED_METHOD]["w_pii"] = tuned_weights["w_pii"]

    # Evaluar cada método sobre todas las queries.
    raw = {name: evaluate_method(name, m, corpus, cfg["top_k"]) for name, m in methods.items()}

    # Resumir sobre test con IC + umbral Youden por método.
    summary = {}
    for i, (name, ev) in enumerate(raw.items()):
        summary[name] = summarize_method(ev, splits, dist_splits, cfg["bootstrap_iters"], cfg["seed"] + 10 * i)

    # Significancia G vs E.
    significance = compare_methods_significance(
        raw[PROPOSED_METHOD], raw[NO_LAYOUT_METHOD], splits["test"], cfg["bootstrap_iters"], cfg["seed"] + 999
    )

    return {
        "config": cfg,
        "environment": {
            "sklearn": _SKLEARN, "scipy": _SCIPY, "tlsh": _TLSH,
            "semantic_model": "paraphrase-multilingual-MiniLM-L12-v2 (384d; protocolo §4.1 sugiere BGE-m3/e5-large 1024d)",
        },
        "split_sizes": {
            "train_families": len(splits["train"]), "val_families": len(splits["val"]),
            "test_families": len(splits["test"]),
            "test_distractors": len(dist_splits["test"]), "dev_distractors": len(dist_splits["dev"]),
        },
        "tuned_weights": tuned_weights,
        "proposed_method": PROPOSED_METHOD,
        "no_layout_method": NO_LAYOUT_METHOD,
        "proposed_operating_point": {
            "method": PROPOSED_METHOD,
            "threshold": summary[PROPOSED_METHOD].get("threshold"),
            "threshold_margin": summary[PROPOSED_METHOD].get("threshold_margin"),
            "threshold_policy": summary[PROPOSED_METHOD].get("threshold_policy"),
            "threshold_source": summary[PROPOSED_METHOD].get("threshold_source"),
            "confusion_matrix": summary[PROPOSED_METHOD].get("confusion_matrix"),
            "confusion_matrix_margin": summary[PROPOSED_METHOD].get("confusion_matrix_margin"),
            "auc_detection": summary[PROPOSED_METHOD].get("auc_detection"),
            "auc_detection_margin": summary[PROPOSED_METHOD].get("auc_detection_margin"),
            "detection_rate": summary[PROPOSED_METHOD].get("detection_rate"),
            "fpr": summary[PROPOSED_METHOD].get("fpr"),
            "precision_operating": summary[PROPOSED_METHOD].get("precision_operating"),
            "specificity": summary[PROPOSED_METHOD].get("specificity"),
            "detection_rate_margin": summary[PROPOSED_METHOD].get("detection_rate_margin"),
            "fpr_margin": summary[PROPOSED_METHOD].get("fpr_margin"),
            "precision_operating_margin": summary[PROPOSED_METHOD].get("precision_operating_margin"),
            "specificity_margin": summary[PROPOSED_METHOD].get("specificity_margin"),
            "fpr_by_profile": summary[PROPOSED_METHOD].get("fpr_by_profile"),
            "note": "El umbral operativo se calibra en validaci?n y se aplica congelado en test; Recall@k y MRR son m?tricas de ranking independientes del umbral. Se reporta max_score como punto operativo primario y margin_score Top-1 menos Top-2 como confianza alternativa frente a distractores.",
        },
        "summary": summary,
        "significance_G_vs_E": significance,
    }


def save_evaluation(result: Dict[str, Any]) -> str:
    results_dir = Path(__file__).resolve().parents[2] / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = results_dir / f"evaluation_{timestamp}.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return str(out)


# === FORENSIQ_EVALUATION_M1_M10_PATCH ===
# Lista final alineada al protocolo: 8 simples + 10 m?ltiples = 18 variantes por documento.

TRANSFORMATION_TYPES = [
    "format_change",
    "binary_recode",
    "whitespace",
    "ocr_reocr",
    "case_punct",
    "drop_fields",
    "reorder_blocks",
    "mask_pii",
    "combo_format_noise",
    "combo_ocr_noise",
    "combo_ocr_mask",
    "combo_reorder_mask",
    "combo_noise_drop",
    "combo_reorder_noise",
    "combo_drop_case",
    "combo_noise_reorder_mask",
    "combo_drop_reorder_mask",
    "combo_strong",
]

PROTOCOL_TRANSFORMATION_MAP.update({
    "combo_format_noise": "M1",
    "combo_ocr_noise": "M2",
    "combo_ocr_mask": "M3",
    "combo_reorder_mask": "M4",
    "combo_noise_drop": "M5",
    "combo_reorder_noise": "M6",
    "combo_drop_case": "M7",
    "combo_noise_reorder_mask": "M8",
    "combo_drop_reorder_mask": "M9",
    "combo_strong": "M10",
})


# === FORENSIQ_API_EVALUATION_WRAPPERS_PATCH ===
# Backward-compatible wrappers expected by app.main.
# These wrappers keep the web API working after replacing evaluation.py with
# the notebook-oriented experimental evaluation module.

from pathlib import Path as _ApiPath
from datetime import datetime as _ApiDatetime


API_DEMO_CONFIG = {
    "n_legit": 20,
    "n_distractors": 8,
    "seed": 42,
    "weight_mode": "fixed",
    "test_fraction": 0.2,
    "val_fraction": 0.2,
    "bootstrap_iters": 200,
    "top_k": 5,
    "transformations": None,
}


API_VISUAL_DEMO_CONFIG = {
    "n_legit": 50,
    "n_distractors": 20,
    "seed": 42,
    "weight_mode": "fixed",
    "test_fraction": 0.2,
    "val_fraction": 0.2,
    "bootstrap_iters": 200,
    "top_k": 5,
    "transformations": [
        "visual_redacted",
        "visual_redacted_reorder",
        "visual_noise_redacted",
        "visual_strong",
    ],
}


def _run_full_evaluation_compat(config: dict):
    """Calls run_full_evaluation with flexible signature support."""
    try:
        return run_full_evaluation(**config)
    except TypeError:
        try:
            return run_full_evaluation(config)
        except TypeError:
            return run_full_evaluation()


def run_evaluation():
    """API demo evaluation. Uses a small configuration to avoid freezing UI."""
    result = _run_full_evaluation_compat(API_DEMO_CONFIG)
    return result


def run_evaluation_summary_only():
    """Returns a compact summary for the web app."""
    result = _run_full_evaluation_compat(API_DEMO_CONFIG)

    return {
        "config": result.get("config"),
        "split_sizes": result.get("split_sizes"),
        "environment": result.get("environment"),
        "proposed_method": result.get("proposed_method"),
        "no_layout_method": result.get("no_layout_method"),
        "summary": result.get("summary"),
        "significance_G_vs_E": result.get("significance_G_vs_E"),
        "note": "API demo evaluation. For paper results, use the notebook JSON generated with the full protocol.",
    }


def save_evaluation_summary_to_file():
    """Runs the small API evaluation and saves it under backend/results."""
    result = run_evaluation_summary_only()

    results_dir = _ApiPath(__file__).resolve().parents[2] / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    output_path = results_dir / f"api_evaluation_summary_{_ApiDatetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    try:
        save_evaluation(result, output_path)
    except TypeError:
        import json
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "saved": True,
        "path": str(output_path),
        "summary": result,
    }


def run_visual_evaluation_summary_only():
    """Optional visual enriched demo evaluation for the web app."""
    result = _run_full_evaluation_compat(API_VISUAL_DEMO_CONFIG)
    return {
        "config": result.get("config"),
        "split_sizes": result.get("split_sizes"),
        "environment": result.get("environment"),
        "summary": result.get("summary"),
        "significance_G_vs_E": result.get("significance_G_vs_E"),
        "note": "Visual enriched API demo. For final paper values, use the notebook JSON with n_legit=250.",
    }

