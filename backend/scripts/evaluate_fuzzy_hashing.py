from pathlib import Path
import json
import re
import subprocess
from statistics import mean

import tlsh


PROJECT_ROOT = Path("/mnt/c/Users/Malik/forensiq")
LEGITIMATE_DIR = PROJECT_ROOT / "synthetic_data" / "legitimate"
SUSPICIOUS_DIR = PROJECT_ROOT / "synthetic_data" / "suspicious"
RESULTS_DIR = PROJECT_ROOT / "backend" / "results"


def extract_doc_code(filename: str):
    match = re.search(r"DOC-\d{4}", filename)
    return match.group(0) if match else None


def reciprocal_rank(matches, target_doc_code):
    for index, match in enumerate(matches, start=1):
        if match["doc_code"] == target_doc_code:
            return 1.0 / index
    return 0.0


def rank_position(matches, target_doc_code):
    for index, match in enumerate(matches, start=1):
        if match["doc_code"] == target_doc_code:
            return index
    return None


def summarize(cases):
    total = len(cases)

    if total == 0:
        return {
            "recall_at_1": 0.0,
            "recall_at_5": 0.0,
            "mrr": 0.0,
            "total_cases": 0,
        }

    recall_at_1 = sum(1 for case in cases if case["top_1_hit"]) / total
    recall_at_5 = sum(1 for case in cases if case["top_5_hit"]) / total
    mrr = mean(case["reciprocal_rank"] for case in cases)

    return {
        "recall_at_1": round(recall_at_1, 4),
        "recall_at_5": round(recall_at_5, 4),
        "mrr": round(mrr, 4),
        "total_cases": total,
    }


def get_references():
    references = []

    for path in sorted(LEGITIMATE_DIR.glob("*.pdf")):
        doc_code = extract_doc_code(path.name)

        if doc_code:
            references.append({
                "doc_code": doc_code,
                "filename": path.name,
                "path": str(path),
            })

    return references


def get_variants():
    variants = []

    for path in sorted(SUSPICIOUS_DIR.glob("*.pdf")):
        doc_code = extract_doc_code(path.name)

        if doc_code:
            variants.append({
                "ground_truth_doc_code": doc_code,
                "filename": path.name,
                "path": str(path),
            })

    return variants


def compute_ssdeep_hash(path: str):
    try:
        result = subprocess.run(
            ["ssdeep", "-b", path],
            capture_output=True,
            text=True,
            check=True,
        )

        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]

        # ssdeep output:
        # ssdeep,1.1--blocksize:hash:hash,filename
        # 384:abc:def,/path/file.pdf
        for line in lines:
            if line.startswith("ssdeep"):
                continue

            return line.split(",", 1)[0]

        return None
    except Exception:
        return None


def compare_ssdeep_hashes(hash_a: str, hash_b: str) -> float:
    if not hash_a or not hash_b:
        return 0.0

    try:
        result = subprocess.run(
            ["ssdeep", "-k", hash_a, hash_b],
            capture_output=True,
            text=True,
        )

        # Si no funciona -k en alguna versión, devolvemos 0.
        # En varias instalaciones ssdeep no compara hashes directos cómodamente,
        # por eso usaremos alternativa por archivos en evaluate_ssdeep.
        return 0.0
    except Exception:
        return 0.0


def compare_ssdeep_files(path_a: str, path_b: str) -> float:
    try:
        result = subprocess.run(
            ["ssdeep", "-b", "-d", path_a, path_b],
            capture_output=True,
            text=True,
        )

        output = result.stdout.strip()

        # ssdeep -d suele imprimir líneas cuando detecta similitud.
        # Ejemplo aproximado:
        # fileA matches fileB (88)
        match = re.search(r"\((\d+)\)", output)

        if match:
            return int(match.group(1)) / 100.0

        return 0.0
    except Exception:
        return 0.0


def evaluate_ssdeep(references, variants):
    cases = []

    for variant in variants:
        matches = []

        for ref in references:
            score = compare_ssdeep_files(variant["path"], ref["path"])

            matches.append({
                "doc_code": ref["doc_code"],
                "filename": ref["filename"],
                "score": round(score, 4),
            })

        matches.sort(key=lambda item: item["score"], reverse=True)

        if matches and matches[0]["score"] == 0.0:
            position = None
            rr = 0.0
            top_1_hit = False
            top_5_hit = False
        else:
            position = rank_position(matches, variant["ground_truth_doc_code"])
            rr = reciprocal_rank(matches, variant["ground_truth_doc_code"])
            top_1_hit = position == 1
            top_5_hit = position is not None and position <= 5

        cases.append({
            "variant_filename": variant["filename"],
            "ground_truth_doc_code": variant["ground_truth_doc_code"],
            "rank_position": position,
            "top_1_hit": top_1_hit,
            "top_5_hit": top_5_hit,
            "reciprocal_rank": round(rr, 4),
            "top_matches": matches[:5],
        })

    return {
        "method": "ssdeep",
        **summarize(cases),
        "cases": cases,
    }


def compute_tlsh_hash(path: str):
    try:
        data = Path(path).read_bytes()
        result = tlsh.hash(data)

        if result in (None, "", "TNULL"):
            return None

        return result
    except Exception:
        return None


def tlsh_distance_to_similarity(distance: int) -> float:
    return 1.0 / (1.0 + float(distance))


def evaluate_tlsh(references, variants):
    reference_hashes = []

    for ref in references:
        reference_hashes.append({
            **ref,
            "hash": compute_tlsh_hash(ref["path"]),
        })

    cases = []

    for variant in variants:
        query_hash = compute_tlsh_hash(variant["path"])
        matches = []

        for ref in reference_hashes:
            if query_hash and ref["hash"]:
                try:
                    distance = tlsh.diff(query_hash, ref["hash"])
                    score = tlsh_distance_to_similarity(distance)
                except Exception:
                    score = 0.0
            else:
                score = 0.0

            matches.append({
                "doc_code": ref["doc_code"],
                "filename": ref["filename"],
                "score": round(score, 4),
            })

        matches.sort(key=lambda item: item["score"], reverse=True)

        if matches and matches[0]["score"] == 0.0:
            position = None
            rr = 0.0
            top_1_hit = False
            top_5_hit = False
        else:
            position = rank_position(matches, variant["ground_truth_doc_code"])
            rr = reciprocal_rank(matches, variant["ground_truth_doc_code"])
            top_1_hit = position == 1
            top_5_hit = position is not None and position <= 5

        cases.append({
            "variant_filename": variant["filename"],
            "ground_truth_doc_code": variant["ground_truth_doc_code"],
            "rank_position": position,
            "top_1_hit": top_1_hit,
            "top_5_hit": top_5_hit,
            "reciprocal_rank": round(rr, 4),
            "top_matches": matches[:5],
        })

    return {
        "method": "tlsh",
        **summarize(cases),
        "cases": cases,
    }


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    references = get_references()
    variants = get_variants()

    print(f"References: {len(references)}")
    print(f"Variants: {len(variants)}")

    if not references:
        raise RuntimeError("No legitimate PDFs found.")

    if not variants:
        raise RuntimeError("No suspicious PDFs found.")

    results = [
        evaluate_ssdeep(references, variants),
        evaluate_tlsh(references, variants),
    ]

    summary = [
        {
            "method": result["method"],
            "recall_at_1": result["recall_at_1"],
            "recall_at_5": result["recall_at_5"],
            "mrr": result["mrr"],
            "total_cases": result["total_cases"],
        }
        for result in results
    ]

    output = {
        "total_reference_documents": len(references),
        "total_variants": len(variants),
        "summary": summary,
        "details": results,
    }

    output_path = RESULTS_DIR / "fuzzy_hashing_results.json"

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Saved to: {output_path}")


if __name__ == "__main__":
    main()
