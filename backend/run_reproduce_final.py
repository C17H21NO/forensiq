import json

from app.services.evaluation import run_full_evaluation, save_evaluation
from app.services.evaluation import prepare_corpus
from run_bge_m3_baseline import corpus_signature

corpus = prepare_corpus(
    n_legit=100,
    n_distractors=200,
    seed=42,
    transformations=[
        "drop_fields",
        "mask_pii",
        "combo_strong",
        "visual_strong",
    ],
    decouple_visual_seed=True,
    distractor_profiles=[
        "random_different_identity",
        "same_type_different_identity",
        "same_identity_different_document",
        "same_identity_same_type_modified_context",
    ],
)

signature = corpus_signature(corpus)

print("\nCORPUS SIGNATURE:")
print(signature)

result = run_full_evaluation(
    n_legit=100,
    n_distractors=200,
    seed=42,
    weight_mode="grid_search",
    test_fraction=0.2,
    val_fraction=0.2,
    bootstrap_iters=1000,
    top_k=5,
    transformations=[
        "drop_fields",
        "mask_pii",
        "combo_strong",
        "visual_strong",
    ],
    decouple_visual_seed=True,
    distractor_profiles=[
        "random_different_identity",
        "same_type_different_identity",
        "same_identity_different_document",
        "same_identity_same_type_modified_context",
    ],
)

output = save_evaluation(result)

print("\nRESULTADO GUARDADO EN:")
print(output)

print("\nPESOS CALIBRADOS:")
print(json.dumps(result.get("tuned_weights"), indent=2))

print("\nRESULTADOS CLAVE:")
for method in [
    "text_only",
    "text_layout",
    "text_pii",
    "multimodal",
]:
    s = result["summary"][method]
    print(
        method,
        "R@1 =", s["recall_at_1"],
        "R@5 =", s["recall_at_5"],
        "MRR =", s["mrr"],
        "AUC =", s["auc_detection"],
    )

print("\nSIGNIFICANCIA G VS E:")
print(json.dumps(result["significance_G_vs_E"], indent=2))