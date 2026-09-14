import hashlib
import json
from datetime import datetime
from pathlib import Path
from time import perf_counter

import numpy as np
from sentence_transformers import SentenceTransformer

from app.services.evaluation import (
    prepare_corpus,
    family_split,
    _split_distractors,
    summarize_method,
)
from app.services.fingerprint import strip_boilerplate


# ---------------------------------------------------------------------------
# Frozen camera-ready protocol
# ---------------------------------------------------------------------------
CONFIG = {
    "n_legit": 100,
    "n_distractors": 200,
    "seed": 42,
    "test_fraction": 0.2,
    "val_fraction": 0.2,
    "bootstrap_iters": 1000,
    "top_k": 5,
    "transformations": [
        "drop_fields",      # T6
        "mask_pii",         # T8
        "combo_strong",     # M10
        "visual_strong",    # V4
    ],
    "decouple_visual_seed": True,
    "distractor_profiles": [
        "random_different_identity",
        "same_type_different_identity",
        "same_identity_different_document",
        "same_identity_same_type_modified_context",
    ],
}

# Pin the exact Hugging Face revision used for the camera-ready baseline.
MODEL_NAME = "BAAI/bge-m3"
MODEL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
MODEL_MAX_LENGTH = 8192
BATCH_SIZE = 8

# If BGE-M3 were appended after the existing evaluation methods, this fixed
# bootstrap seed keeps its confidence intervals deterministic.
BGE_BOOTSTRAP_SEED = 152


def clean_text(text: str) -> str:
    """Use the same boilerplate removal as the existing ForensiQ text channel."""
    cleaned = strip_boilerplate(text or "")
    cleaned = " ".join(cleaned.split())
    return cleaned or "Documento vacío o sin texto reconocible."


def tie_break(document_id: str) -> str:
    """Same deterministic tie-break principle used by matcher.py."""
    return hashlib.md5(str(document_id).encode("utf-8")).hexdigest()


def ranked_indices(scores: np.ndarray, reference_ids: list[str]) -> list[int]:
    """Descending cosine score, deterministic ID hash for exact ties."""
    return sorted(
        range(len(reference_ids)),
        key=lambda i: (-float(scores[i]), tie_break(reference_ids[i])),
    )


def corpus_signature(corpus: dict) -> str:
    """
    Content-level signature that intentionally ignores random physical filenames
    for distractors. It fingerprints the scientific content and labels.
    """
    payload = {
        "references": [
            {
                "document_id": r["document_id"],
                "text": clean_text(r["text"]),
            }
            for r in corpus["references"]
        ],
        "variants": [
            {
                "case_key": c["case_key"],
                "family": c["family"],
                "ground_truth_document_id": c["ground_truth_document_id"],
                "transformation_type": c["transformation_type"],
                "text": clean_text(c["text"]),
            }
            for c in corpus["variant_cases"]
        ],
        "distractors": [
            {
                "profile": d["profile"],
                "source_parent_document_id": d.get("source_parent_document_id"),
                "document_type": d.get("document_type"),
                "text": clean_text(d["text"]),
            }
            for d in corpus["distractor_queries"]
        ],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def evaluate_bge(corpus: dict, model: SentenceTransformer) -> dict:
    references = corpus["references"]
    variants = corpus["variant_cases"]
    distractors = corpus["distractor_queries"]

    reference_ids = [r["document_id"] for r in references]

    ref_texts = [clean_text(r["text"]) for r in references]
    variant_texts = [clean_text(c["text"]) for c in variants]
    distractor_texts = [clean_text(d["text"]) for d in distractors]

    print("Encoding references with BGE-M3...")
    ref_embeddings = model.encode(
        ref_texts,
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    ).astype(np.float32)

    print("Encoding positive queries with BGE-M3...")
    variant_embeddings = model.encode(
        variant_texts,
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    ).astype(np.float32)

    print("Encoding distractors with BGE-M3...")
    distractor_embeddings = model.encode(
        distractor_texts,
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    ).astype(np.float32)

    variant_records = {}
    latencies_ms = []

    for case, q_emb in zip(variants, variant_embeddings):
        t0 = perf_counter()
        # Embeddings are L2-normalized, so dot product equals cosine similarity.
        scores = ref_embeddings @ q_emb
        order = ranked_indices(scores, reference_ids)
        latencies_ms.append((perf_counter() - t0) * 1000.0)

        max_score = float(scores[order[0]]) if order else 0.0
        second_score = float(scores[order[1]]) if len(order) > 1 else 0.0

        target = case["ground_truth_document_id"]
        pos = None
        for rank, idx in enumerate(order, start=1):
            if reference_ids[idx] == target:
                pos = rank
                break

        variant_records[case["case_key"]] = {
            "family": case["family"],
            "transformation_type": case["transformation_type"],
            "protocol_id": case["protocol_id"],
            "rank_position": pos,
            "top1": pos == 1,
            "top5": pos is not None and pos <= CONFIG["top_k"],
            "reciprocal_rank": (1.0 / pos) if pos else 0.0,
            "max_score": max_score,
            "second_score": second_score,
            "margin_score": max_score - second_score,
            "all_zero": max_score == 0.0,
        }

    distractor_max = {}
    distractor_margin = {}
    distractor_profile = {}

    for d, q_emb in zip(distractors, distractor_embeddings):
        scores = ref_embeddings @ q_emb
        order = ranked_indices(scores, reference_ids)

        max_score = float(scores[order[0]]) if order else 0.0
        second_score = float(scores[order[1]]) if len(order) > 1 else 0.0

        did = d["distractor_id"]
        distractor_max[did] = max_score
        distractor_margin[did] = max_score - second_score
        distractor_profile[did] = d.get("profile", "unknown")

    return {
        "method": "bge_m3_dense_text",
        "description": "External neural retrieval baseline: BAAI/bge-m3 dense text-only cosine retrieval.",
        "variant_records": variant_records,
        "distractor_max": distractor_max,
        "distractor_margin": distractor_margin,
        "distractor_profile": distractor_profile,
        # Comparable with existing evaluate_method(): ranking only, embeddings
        # were precomputed before timing.
        "avg_latency_ms": round(float(np.mean(latencies_ms)), 2) if latencies_ms else 0.0,
        "p95_latency_ms": round(float(np.percentile(latencies_ms, 95)), 2) if latencies_ms else 0.0,
    }


def main():
    print("Preparing the frozen deterministic ForensiQ corpus...")
    corpus = prepare_corpus(
        CONFIG["n_legit"],
        CONFIG["n_distractors"],
        CONFIG["seed"],
        CONFIG["transformations"],
        decouple_visual_seed=CONFIG["decouple_visual_seed"],
        distractor_profiles=CONFIG["distractor_profiles"],
    )

    reference_ids = [r["document_id"] for r in corpus["references"]]
    splits = family_split(
        reference_ids,
        CONFIG["test_fraction"],
        CONFIG["val_fraction"],
        CONFIG["seed"],
    )
    dist_splits = _split_distractors(
        corpus["distractor_queries"],
        CONFIG["test_fraction"],
        CONFIG["seed"],
    )

    signature = corpus_signature(corpus)
    print("Corpus signature:", signature)

    print("Loading pinned BGE-M3 model...")
    model = SentenceTransformer(
        MODEL_NAME,
        revision=MODEL_REVISION,
    )
    model.max_seq_length = MODEL_MAX_LENGTH

    raw = evaluate_bge(corpus, model)

    summary = summarize_method(
        raw,
        splits,
        dist_splits,
        CONFIG["bootstrap_iters"],
        BGE_BOOTSTRAP_SEED,
    )

    result = {
        "baseline": "bge_m3_dense_text",
        "model": {
            "name": MODEL_NAME,
            "revision": MODEL_REVISION,
            "embedding_dimension": 1024,
            "max_sequence_length": MODEL_MAX_LENGTH,
            "normalize_embeddings": True,
            "similarity": "cosine_via_dot_product_of_L2_normalized_embeddings",
            "query_instruction": None,
        },
        "config": CONFIG,
        "corpus_signature": signature,
        "split_sizes": {
            "train_families": len(splits["train"]),
            "val_families": len(splits["val"]),
            "test_families": len(splits["test"]),
            "dev_distractors": len(dist_splits["dev"]),
            "test_distractors": len(dist_splits["test"]),
        },
        "summary": summary,
    }

    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    output = results_dir / f"bge_m3_baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\nBGE-M3 BASELINE RESULT")
    print("R@1:", summary["recall_at_1"], summary["recall_at_1_ci"])
    print("R@5:", summary["recall_at_5"], summary["recall_at_5_ci"])
    print("MRR :", summary["mrr"], summary["mrr_ci"])
    print("AUC :", summary["auc_detection"])
    print("Threshold:", summary["threshold"])
    print("FPR:", summary["fpr"])
    print("Confusion matrix:", summary["confusion_matrix"])
    print("\nSaved to:", output)


if __name__ == "__main__":
    main()
