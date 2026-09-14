import json
from pathlib import Path

from app.services.weight_sensitivity import run_sensitivity

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

reports = {}

for channel in ["lexical", "semantic", "hybrid"]:
    print(f"\n{'=' * 70}")
    print(f"RUNNING DETERMINISTIC WEIGHT SENSITIVITY: {channel.upper()}")
    print(f"{'=' * 70}")

    prefix = RESULTS_DIR / "camera_ready_sensitivity"
    report = run_sensitivity(
        n_legit=100,
        n_distractors=200,
        seed=42,
        step=0.05,
        text_channel=channel,
        out_prefix=str(prefix),
    )
    reports[channel] = report

combined_path = RESULTS_DIR / "camera_ready_sensitivity_combined.json"
combined_path.write_text(
    json.dumps(reports, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print("\n\nCOMBINED REPORT:")
print(combined_path)

for channel, report in reports.items():
    plateau = report["ranking_plateau"]
    best_det = report["best_for_detection"]
    corners = {row["config"]: row for row in report["corners"]}

    print(f"\n[{channel.upper()}]")
    print("Best R@1:", plateau["best_recall_at_1"])
    print(
        "Near-optimal:",
        f'{plateau["n_near_optimal_configs"]}/{plateau["n_total_configs"]}',
    )
    print("Weight ranges:", plateau["weight_ranges_in_plateau"])
    print(
        "Best detection AUC:",
        best_det.get("detection_auc"),
        "weights=",
        (
            best_det.get("w_text"),
            best_det.get("w_layout"),
            best_det.get("w_pii"),
        ),
    )
    print(
        "Text+layout corner AUC:",
        corners["text_layout(no_pii)"]["detection_auc"],
    )
    print(
        "Text+PII corner AUC:",
        corners["text_pii(no_layout)"]["detection_auc"],
    )
