import argparse
import csv
import json
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def summarize(name, samples, wall_time_s=None):
    latencies = [s["latency_ms"] for s in samples if s["ok"]]
    errors = [s for s in samples if not s["ok"]]
    total = len(samples)
    throughput = round(total / wall_time_s, 2) if wall_time_s and wall_time_s > 0 else None
    return {
        "scenario": name,
        "requests": total,
        "success": len(latencies),
        "errors": len(errors),
        "error_rate": round(len(errors) / total, 4) if total else None,
        "throughput_req_s": throughput,
        "mean_ms": round(statistics.mean(latencies), 2) if latencies else None,
        "median_ms": round(statistics.median(latencies), 2) if latencies else None,
        "min_ms": round(min(latencies), 2) if latencies else None,
        "max_ms": round(max(latencies), 2) if latencies else None,
        "p50_ms": round(percentile(latencies, 50), 2) if latencies else None,
        "p95_ms": round(percentile(latencies, 95), 2) if latencies else None,
        "p99_ms": round(percentile(latencies, 99), 2) if latencies else None,
    }


def request_timed(method, url, token=None, timeout=180, **kwargs):
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    t0 = time.perf_counter()
    try:
        response = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
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
        }
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": latency_ms,
            "detail": repr(exc)[:500],
        }


def login(base_url, username, password):
    result = request_timed(
        "POST",
        f"{base_url}/auth/login",
        json={"username": username, "password": password},
    )
    if not result["ok"]:
        raise RuntimeError(f"No se pudo iniciar sesión con {username}: {result['detail']}")
    response = requests.post(f"{base_url}/auth/login", json={"username": username, "password": password}, timeout=60)
    response.raise_for_status()
    return response.json()["access_token"]


def prepare_backend(base_url, bootstrap_n):
    health = request_timed("GET", f"{base_url}/")
    if not health["ok"]:
        raise RuntimeError("El backend no responde. Levanta primero: uvicorn app.main:app --reload")

    admin_token = login(base_url, "admin@forensiq.local", "Admin123!")
    analyst_token = login(base_url, "analyst@forensiq.local", "Analyst123!")
    dpo_token = login(base_url, "dpo@forensiq.local", "Dpo123!")

    if bootstrap_n and bootstrap_n > 0:
        print(f"Preparando índice sintético n={bootstrap_n}...")
        boot = request_timed(
            "POST",
            f"{base_url}/references/bootstrap-synthetic",
            token=admin_token,
            params={"n": bootstrap_n, "clear_existing": "true"},
        )
        if not boot["ok"]:
            raise RuntimeError(f"Falló bootstrap: {boot['detail']}")

    refs_resp = requests.get(
        f"{base_url}/references",
        headers={"Authorization": f"Bearer {analyst_token}"},
        timeout=60,
    )
    refs_resp.raise_for_status()
    refs = refs_resp.json().get("documents", [])
    if not refs:
        raise RuntimeError("No hay referencias cargadas para ejecutar matching.")

    document_id = refs[0]["document_id"]
    return {
        "admin_token": admin_token,
        "analyst_token": analyst_token,
        "dpo_token": dpo_token,
        "document_id": document_id,
    }


def run_concurrent_scenario(name, total, concurrency, fn):
    print(f"\nEscenario: {name} | total={total} | concurrencia={concurrency}")
    samples = []
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(fn, i + 1) for i in range(total)]
        for j, fut in enumerate(as_completed(futures), start=1):
            sample = fut.result()
            sample["scenario"] = name
            sample["request"] = j
            samples.append(sample)
            if j % max(1, total // 10) == 0 or j == total:
                ok_count = sum(1 for s in samples if s["ok"])
                err_count = len(samples) - ok_count
                print(f"  completadas={j}/{total} ok={ok_count} errores={err_count}")
    wall = time.perf_counter() - t0
    summary = summarize(name, samples, wall_time_s=wall)
    print("  resumen:", json.dumps(summary, ensure_ascii=False))
    return samples, summary


def main():
    parser = argparse.ArgumentParser(description="Prueba de carga/estrés controlada para backend ForensiQ TP1.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--total", type=int, default=60, help="Solicitudes por escenario.")
    parser.add_argument("--concurrency", type=int, default=5, help="Hilos concurrentes por escenario.")
    parser.add_argument("--bootstrap-n", type=int, default=30, help="Referencias sintéticas para preparar índice. Use 0 para no regenerar.")
    parser.add_argument("--out-dir", default="load_test_tp1_results")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Base URL:", base_url)
    print("Total por escenario:", args.total)
    print("Concurrencia:", args.concurrency)
    print("Bootstrap n:", args.bootstrap_n)

    ctx = prepare_backend(base_url, args.bootstrap_n)
    analyst_token = ctx["analyst_token"]
    dpo_token = ctx["dpo_token"]
    document_id = ctx["document_id"]

    all_samples = []
    all_summary = []

    # 1) Carga concurrente ligera: endpoint informativo
    samples, summary = run_concurrent_scenario(
        "load_system_capabilities",
        args.total,
        args.concurrency,
        lambda i: request_timed("GET", f"{base_url}/system/capabilities", token=analyst_token),
    )
    all_samples += samples
    all_summary.append(summary)

    # 2) Carga concurrente de lectura de índice
    samples, summary = run_concurrent_scenario(
        "load_references_list",
        args.total,
        args.concurrency,
        lambda i: request_timed("GET", f"{base_url}/references", token=analyst_token),
    )
    all_samples += samples
    all_summary.append(summary)

    # 3) Carga concurrente pesada: variante + matching top-k
    samples, summary = run_concurrent_scenario(
        "stress_variant_and_match_top5",
        args.total,
        args.concurrency,
        lambda i: request_timed(
            "POST",
            f"{base_url}/references/{document_id}/variant-and-match",
            token=analyst_token,
            params={"transformation_type": "combined", "top_k": 5},
        ),
    )
    all_samples += samples
    all_summary.append(summary)

    # 4) Carga mixta: simula usuarios leyendo referencias, ejecutando matching e historial.
    def mixed_request(i):
        r = random.random()
        if r < 0.45:
            return request_timed("GET", f"{base_url}/references", token=analyst_token)
        if r < 0.85:
            return request_timed(
                "POST",
                f"{base_url}/references/{document_id}/variant-and-match",
                token=analyst_token,
                params={"transformation_type": "combined", "top_k": 5},
            )
        return request_timed("GET", f"{base_url}/analysis/history", token=dpo_token)

    samples, summary = run_concurrent_scenario(
        "mixed_workload_references_matching_history",
        args.total,
        args.concurrency,
        mixed_request,
    )
    all_samples += samples
    all_summary.append(summary)

    detail_path = out_dir / "load_test_tp1_detail.csv"
    with detail_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["scenario", "request", "ok", "status_code", "latency_ms", "detail"],
        )
        writer.writeheader()
        for sample in all_samples:
            writer.writerow({
                "scenario": sample.get("scenario"),
                "request": sample.get("request"),
                "ok": sample.get("ok"),
                "status_code": sample.get("status_code"),
                "latency_ms": round(sample.get("latency_ms", 0), 2),
                "detail": sample.get("detail", ""),
            })

    summary_path = out_dir / "load_test_tp1_summary.json"
    summary_path.write_text(json.dumps(all_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nArchivos generados:")
    print(" -", detail_path)
    print(" -", summary_path)
    print("\nInterpretación rápida:")
    print(" - Si error_rate <= 0.01 y p95 del flujo pesado es aceptable, el backend soporta carga concurrente piloto.")
    print(" - Si aparecen errores o p95 muy alto, repita con menor concurrencia o revise cuellos de botella.")
    print(" - Reporte esto como prueba de carga/estrés controlada local, no como certificación de producción.")


if __name__ == "__main__":
    main()
