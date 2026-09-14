from pathlib import Path
import sys
import json
from datetime import datetime

# Permite ejecutar el script desde backend/ o desde la raíz del proyecto.
CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.evaluation import run_evaluation_summary_only


def main():
    print("=== ForensiQ - Evaluación del modelo ===")
    print("Ejecutando evaluación experimental...")
    print()

    result = run_evaluation_summary_only()

    output_dir = BACKEND_DIR / "results"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"model_evaluation_{timestamp}.json"

    with output_file.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("Evaluación finalizada.")
    print(f"Resultado guardado en: {output_file}")
    print()

    if "summary" in result:
        print("Resumen de métricas:")
        for row in result["summary"]:
            print(
                f"- {row['method']}: "
                f"Recall@1={row.get('recall_at_1')}, "
                f"Recall@5={row.get('recall_at_5')}, "
                f"MRR={row.get('mrr')}, "
                f"FPR={row.get('fpr')}, "
                f"AUC={row.get('auc_roc')}"
            )
    else:
        print("No se encontró summary en el resultado.")
        print(result)


if __name__ == "__main__":
    main()