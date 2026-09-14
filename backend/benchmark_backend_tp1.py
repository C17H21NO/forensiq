import argparse
import csv
import json
import statistics
import time
from pathlib import Path

import requests


def percentile(values, pct):
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    k = (len(values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def summarize(name, samples):
    latencies = [s["latency_ms"] for s in samples if s["ok"]]
    errors = [s for s in samples if not s["ok"]]
    if not samples:
        return {
            "scenario": name,
            "runs": 0,
            "success": 0,
            "errors": 0,
            "error_rate": None,
        }
    return {
        "scenario": name,
        "runs": len(samples),
        "success": len(latencies),
        "errors": len(errors),
        "error_rate": round(len(errors) / len(samples), 4),
        "mean_ms": round(statistics.mean(latencies), 2) if latencies else None,
        "median_ms": round(statistics.median(latencies), 2) if latencies else None,
        "min_ms": round(min(latencies), 2) if latencies else None,
        "max_ms": round(max(latencies), 2) if latencies else None,
        "p50_ms": round(percentile(latencies, 50), 2) if latencies else None,
        "p95_ms": round(percentile(latencies, 95), 2) if latencies else None,
        "p99_ms": round(percentile(latencies, 99), 2) if latencies else None,
    }


def request_timed(method, url, token=None, **kwargs):
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    t0 = time.perf_counter()
    try:
        response = requests.request(method, url, headers=headers, timeout=180, **kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000
        ok = 200 <= response.status_code < 300
        detail = ""
        if not ok:
            try:
                detail = json.dumps(response.json(), ensure_ascii=False)[:500]
            except Exception:
                detail = response.text[:500]
        return {
            "ok": ok,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "detail": detail,
            "json": response.json() if ok and response.text else None,
        }
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": latency_ms,
            "detail": repr(exc),
            "json": None,
        }


def login(base_url, username, password):
    result = request_timed(
        "POST",
        f"{base_url}/auth/login",
        json={"username": username, "password": password},
    )
    if not result["ok"]:
        raise RuntimeError(f"No se pudo iniciar sesión con {username}: {result['detail']}")
    return result["json"]["access_token"]


def run_scenario(name, runs, fn, pause=0.2):
    samples = []
    print(f"\nEjecutando {name} ({runs} corridas)...")
    for i in range(1, runs + 1):
        sample = fn()
        sample["scenario"] = name
        sample["run"] = i
        samples.append(sample)
        status = "OK" if sample["ok"] else "ERROR"
        print(f"  {i:02d}/{runs} {status} {sample['latency_ms']:.2f} ms")
        time.sleep(pause)
    return samples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--bootstrap-n", type=int, default=20)
    parser.add_argument("--out-dir", default="benchmark_tp1_results")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Base URL:", base_url)
    print("Runs por escenario:", args.runs)
    print("Referencias sintéticas para bootstrap:", args.bootstrap_n)

    # 1) Health check
    health = request_timed("GET", f"{base_url}/")
    if not health["ok"]:
        raise RuntimeError(
            "El backend no responde. Levanta primero: uvicorn app.main:app --reload"
        )

    # 2) Login tokens
    admin_token = login(base_url, "admin@forensiq.local", "Admin123!")
    analyst_token = login(base_url, "analyst@forensiq.local", "Analyst123!")
    dpo_token = login(base_url, "dpo@forensiq.local", "Dpo123!")

    all_samples = []

    # 3) Escenarios ligeros
    all_samples += run_scenario(
        "auth_login_analyst",
        args.runs,
        lambda: request_timed(
            "POST",
            f"{base_url}/auth/login",
            json={"username": "analyst@forensiq.local", "password": "Analyst123!"},
        ),
    )

    all_samples += run_scenario(
        "system_capabilities",
        args.runs,
        lambda: request_timed("GET", f"{base_url}/system/capabilities", token=analyst_token),
    )

    # 4) Preparación del índice sintético. Se mide una vez porque incluye generación/carga del corpus.
    print("\nPreparando índice sintético...")
    bootstrap = request_timed(
        "POST",
        f"{base_url}/references/bootstrap-synthetic",
        token=admin_token,
        params={"n": args.bootstrap_n, "clear_existing": "true"},
    )
    bootstrap["scenario"] = f"bootstrap_synthetic_{args.bootstrap_n}"
    bootstrap["run"] = 1
    all_samples.append(bootstrap)
    if not bootstrap["ok"]:
        raise RuntimeError(f"Falló bootstrap: {bootstrap['detail']}")

    references = request_timed("GET", f"{base_url}/references", token=analyst_token)
    if not references["ok"] or not references["json"]["documents"]:
        raise RuntimeError("No hay referencias cargadas para ejecutar matching.")

    document_id = references["json"]["documents"][0]["document_id"]
    print("Documento base para variant-and-match:", document_id)

    all_samples += run_scenario(
        "references_list",
        args.runs,
        lambda: request_timed("GET", f"{base_url}/references", token=analyst_token),
    )

    # 5) Escenario pesado end-to-end: variante + extracción + huella + matching Top-k
    all_samples += run_scenario(
        "variant_and_match_end_to_end_top5",
        args.runs,
        lambda: request_timed(
            "POST",
            f"{base_url}/references/{document_id}/variant-and-match",
            token=analyst_token,
            params={"transformation_type": "combined", "top_k": 5},
        ),
        pause=0.5,
    )

    all_samples += run_scenario(
        "analysis_history_dpo",
        args.runs,
        lambda: request_timed("GET", f"{base_url}/analysis/history", token=dpo_token),
    )

    # Guardar detalle
    detail_path = out_dir / "benchmark_tp1_detail.csv"
    with detail_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["scenario", "run", "ok", "status_code", "latency_ms", "detail"],
        )
        writer.writeheader()
        for sample in all_samples:
            writer.writerow({
                "scenario": sample.get("scenario"),
                "run": sample.get("run"),
                "ok": sample.get("ok"),
                "status_code": sample.get("status_code"),
                "latency_ms": round(sample.get("latency_ms", 0), 2),
                "detail": sample.get("detail", ""),
            })

    # Guardar resumen
    scenarios = sorted({s["scenario"] for s in all_samples})
    summary = [summarize(s, [x for x in all_samples if x["scenario"] == s]) for s in scenarios]
    summary_path = out_dir / "benchmark_tp1_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nRESUMEN")
    for row in summary:
        print(json.dumps(row, ensure_ascii=False))

    print("\nArchivos generados:")
    print(" -", detail_path)
    print(" -", summary_path)


if __name__ == "__main__":
    main()
