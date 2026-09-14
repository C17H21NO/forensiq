from __future__ import annotations

import argparse
import getpass
import subprocess
import sys
from pathlib import Path

import httpx
from sqlalchemy.engine import make_url


BACKEND_ROOT = Path(__file__).resolve().parents[1]

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


from app.config import settings
from app.database import SessionLocal
from app.models import ReferenceDocumentDB


BASE_URL = "http://127.0.0.1:8000"

EXPECTED_REFERENCE_COUNT = 21
EXPECTED_CONTRACT_VERSION = "oe3_production_v1"
EXPECTED_RANKING_MODEL = "lexical_text_similarity_v1"

EXPECTED_SCORE_KEYS = {
    "ranking_score",
    "text_score",
    "layout_score",
    "pii_context_score",
    "ranking_model",
}


class Regression:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(
        self,
        name: str,
        condition: bool,
        detail: str = "",
    ) -> bool:
        if condition:
            self.passed += 1
            print(
                f"[PASS] {name}"
                + (f" — {detail}" if detail else "")
            )
            return True

        self.failed += 1
        print(
            f"[FAIL] {name}"
            + (f" — {detail}" if detail else "")
        )
        return False

    @property
    def total(self) -> int:
        return self.passed + self.failed


def get_json(
    client: httpx.Client,
    path: str,
    headers: dict | None = None,
):
    response = client.get(
        f"{BASE_URL}{path}",
        headers=headers,
    )

    return response, (
        response.json()
        if response.content
        else {}
    )


def login_admin(
    client: httpx.Client,
    username: str,
    password: str,
):
    response = client.post(
        f"{BASE_URL}/auth/login",
        json={
            "username": username,
            "password": password,
        },
    )

    if response.status_code != 200:
        return None, response

    token = response.json().get("access_token")

    if not token:
        return None, response

    return token, response


def check_database(regression: Regression):
    print("\n=== DATABASE ===")

    db = SessionLocal()

    try:
        docs = db.query(ReferenceDocumentDB).all()

        regression.check(
            "Corpus contiene 21 referencias",
            len(docs) == EXPECTED_REFERENCE_COUNT,
            f"{len(docs)}/{EXPECTED_REFERENCE_COUNT}",
        )

        storage_count = sum(
            bool(doc.storage_key)
            for doc in docs
        )

        regression.check(
            "Todas las referencias tienen storage_key",
            storage_count == len(docs),
            f"{storage_count}/{len(docs)}",
        )

        sha_count = sum(
            bool(doc.sha256)
            for doc in docs
        )

        regression.check(
            "Todas las referencias tienen SHA-256",
            sha_count == len(docs),
            f"{sha_count}/{len(docs)}",
        )

        size_count = sum(
            doc.size_bytes is not None
            for doc in docs
        )

        regression.check(
            "Todas las referencias tienen size_bytes",
            size_count == len(docs),
            f"{size_count}/{len(docs)}",
        )

        mime_count = sum(
            bool(doc.mime_type)
            for doc in docs
        )

        regression.check(
            "Todas las referencias tienen MIME type",
            mime_count == len(docs),
            f"{mime_count}/{len(docs)}",
        )

    finally:
        db.close()


def check_alembic(regression: Regression):
    print("\n=== ALEMBIC ===")

    current = subprocess.run(
        ["alembic", "current"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
    )

    regression.check(
        "alembic current",
        (
            current.returncode == 0
            and "(head)" in current.stdout
        ),
        current.stdout.strip().splitlines()[-1]
        if current.stdout.strip()
        else "sin salida",
    )

    check = subprocess.run(
        ["alembic", "check"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
    )

    output = (
        check.stdout
        + "\n"
        + check.stderr
    )

    regression.check(
        "alembic check limpio",
        (
            check.returncode == 0
            and "No new upgrade operations detected"
            in output
        ),
    )


def check_api(
    regression: Regression,
    client: httpx.Client,
):
    print("\n=== HEALTH ===")

    response, data = get_json(
        client,
        "/health/live",
    )

    regression.check(
        "/health/live",
        (
            response.status_code == 200
            and data.get("status") == "alive"
        ),
        f"HTTP {response.status_code}",
    )

    response, data = get_json(
        client,
        "/health/ready",
    )

    regression.check(
        "/health/ready",
        (
            response.status_code == 200
            and data.get("status") == "ready"
        ),
        f"HTTP {response.status_code}",
    )


def check_capabilities(
    regression: Regression,
    client: httpx.Client,
    headers: dict,
):
    print("\n=== PRODUCTION CONTRACT ===")

    response, data = get_json(
        client,
        "/system/capabilities",
        headers=headers,
    )

    regression.check(
        "/system/capabilities HTTP 200",
        response.status_code == 200,
    )

    if response.status_code != 200:
        return

    pipeline = data.get(
        "production_pipeline",
        {},
    )

    regression.check(
        "Ranking model lexical",
        pipeline.get("ranking_model")
        == EXPECTED_RANKING_MODEL,
    )

    regression.check(
        "Ranking basado en texto",
        pipeline.get("ranking_basis")
        == "text",
    )

    regression.check(
        "Layout es evidencia auxiliar",
        pipeline.get("layout_role")
        == "auxiliary_evidence",
    )

    regression.check(
        "PII es context_only",
        pipeline.get("pii_role")
        == "context_only",
    )

    regression.check(
        "Embeddings semánticos desactivados",
        pipeline.get(
            "semantic_embeddings_used"
        )
        is False,
    )

    regression.check(
        "Fusión multimodal desactivada",
        pipeline.get(
            "weighted_multimodal_fusion_used"
        )
        is False,
    )

    regression.check(
        "Sin decisión automática",
        pipeline.get(
            "automatic_match_decision"
        )
        is False,
    )

    regression.check(
        "Salida Top-k",
        pipeline.get("output_type")
        == "top_k_candidate_ranking",
    )


def check_references(
    regression: Regression,
    client: httpx.Client,
    headers: dict,
):
    print("\n=== REFERENCES API ===")

    response, data = get_json(
        client,
        "/references",
        headers=headers,
    )

    regression.check(
        "/references HTTP 200",
        response.status_code == 200,
    )

    if response.status_code != 200:
        return

    items = data.get(
        "items",
        data.get(
            "references",
            [],
        ),
    )

    total = data.get(
        "total",
        len(items),
    )

    regression.check(
        "API reporta 21 referencias",
        total == EXPECTED_REFERENCE_COUNT,
        f"{total}/{EXPECTED_REFERENCE_COUNT}",
    )

    if items:
        available = sum(
            item.get(
                "file_available",
                False,
            )
            is True
            for item in items
        )

        regression.check(
            "Referencias disponibles físicamente",
            available == len(items),
            f"{available}/{len(items)}",
        )

        storage_resolved = sum(
            item.get(
                "resolved_via",
            )
            == "storage_key"
            for item in items
        )

        regression.check(
            "Referencias resueltas por storage_key",
            storage_resolved == len(items),
            f"{storage_resolved}/{len(items)}",
        )


def run_controlled_match(
    regression: Regression,
    client: httpx.Client,
    headers: dict,
    sample_path: Path,
    expected_filename: str | None,
):
    print("\n=== CONTROLLED TOP-K MATCH ===")

    if not sample_path.exists():
        regression.check(
            "Archivo de regresión existe",
            False,
            str(sample_path),
        )
        return

    with sample_path.open("rb") as handle:
        response = client.post(
            f"{BASE_URL}/documents/match",
            params={
                "top_k": 5,
            },
            headers=headers,
            files={
                "file": (
                    sample_path.name,
                    handle,
                    "application/pdf",
                ),
            },
        )

    regression.check(
        "/documents/match HTTP 200",
        response.status_code == 200,
        f"HTTP {response.status_code}",
    )

    if response.status_code != 200:
        print(response.text)
        return

    data = response.json()

    regression.check(
        "ranking_model correcto",
        data.get("ranking_model")
        == EXPECTED_RANKING_MODEL,
    )

    regression.check(
        "top_k = 5",
        data.get("top_k") == 5,
    )

    regression.check(
        "returned_candidates = 5",
        data.get("returned_candidates")
        == 5,
    )

    matches = data.get(
        "matches",
        [],
    )

    regression.check(
        "Existen resultados Top-k",
        len(matches) > 0,
    )

    if not matches:
        return

    top1 = matches[0]

    if expected_filename:
        regression.check(
            "Top-1 esperado",
            top1.get("filename")
            == expected_filename,
            str(top1.get("filename")),
        )

    scores = top1.get(
        "scores",
        {},
    )

    regression.check(
        "Contrato público de scores limpio",
        set(scores.keys())
        == EXPECTED_SCORE_KEYS,
        str(sorted(scores.keys())),
    )

    ranking_score = scores.get(
        "ranking_score"
    )

    text_score = scores.get(
        "text_score"
    )

    regression.check(
        "ranking_score == text_score",
        ranking_score == text_score,
        (
            f"{ranking_score} == "
            f"{text_score}"
        ),
    )

    regression.check(
        "Score declara ranking lexical",
        scores.get("ranking_model")
        == EXPECTED_RANKING_MODEL,
    )

    forbidden_keys = {
        "final_score",
        "selected_text_score",
        "semantic_text_score",
        "hybrid_text_score",
        "pii_score",
    }

    regression.check(
        "No se exponen aliases históricos",
        not (
            forbidden_keys
            & set(scores.keys())
        ),
    )


def check_latest_history(
    regression: Regression,
    client: httpx.Client,
    headers: dict,
):
    print("\n=== ANALYSIS HISTORY ===")

    response, data = get_json(
        client,
        "/analysis/history",
        headers=headers,
    )

    regression.check(
        "/analysis/history HTTP 200",
        response.status_code == 200,
    )

    if response.status_code != 200:
        return

    items = data.get(
        "items",
        [],
    )

    regression.check(
        "Historial no vacío",
        len(items) > 0,
    )

    if not items:
        return

    latest = items[0]

    regression.check(
        "Contrato del historial OE3",
        latest.get("contract_version")
        == EXPECTED_CONTRACT_VERSION,
    )

    matches = latest.get(
        "matches",
        [],
    )

    if not matches:
        regression.check(
            "Historial contiene matches",
            False,
        )
        return

    scores = matches[0].get(
        "scores",
        {},
    )

    regression.check(
        "Historial usa ranking lexical",
        scores.get("ranking_model")
        == EXPECTED_RANKING_MODEL,
    )

    regression.check(
        "Historial ranking_score == text_score",
        scores.get("ranking_score")
        == scores.get("text_score"),
    )


def run_rbac(
    regression: Regression,
):
    print("\n=== RBAC ===")
    print(
        "Se ejecutará scripts/test_rbac.py."
    )
    print(
        "Te solicitará las contraseñas "
        "ADMIN, ANALYST y DPO."
    )
    print()

    result = subprocess.run(
        [
            sys.executable,
            str(
                BACKEND_ROOT
                / "scripts"
                / "test_rbac.py"
            ),
        ],
        cwd=BACKEND_ROOT,
    )

    regression.check(
        "RBAC regression",
        result.returncode == 0,
        (
            "test_rbac.py terminó "
            f"con código {result.returncode}"
        ),
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Regresión final no destructiva "
            "del backend ForensiQ."
        )
    )

    parser.add_argument(
        "--sample",
        type=Path,
        help=(
            "PDF ya existente en el corpus "
            "para validar matching Top-k."
        ),
    )

    parser.add_argument(
        "--expected-filename",
        help=(
            "Nombre lógico esperado como "
            "Top-1 para --sample."
        ),
    )

    parser.add_argument(
        "--skip-rbac",
        action="store_true",
        help="Omite test_rbac.py.",
    )

    args = parser.parse_args()

    regression = Regression()

    print("=" * 72)
    print(
        "FORENSIQ — FINAL BACKEND REGRESSION"
    )
    print("=" * 72)

    print(
        "DATABASE:",
        make_url(
            settings.database_url
        ).render_as_string(
            hide_password=True
        ),
    )

    print(
        "UPLOAD_DIR:",
        settings.upload_dir,
    )

    check_database(
        regression
    )

    check_alembic(
        regression
    )

    with httpx.Client(
        timeout=60.0,
    ) as client:
        check_api(
            regression,
            client,
        )

        print("\n=== ADMIN AUTH ===")

        username = input(
            "ADMIN username "
            "[admin@forensiq.local]: "
        ).strip()

        if not username:
            username = (
                "admin@forensiq.local"
            )

        password = getpass.getpass(
            "ADMIN password: "
        )

        token, response = login_admin(
            client,
            username,
            password,
        )

        regression.check(
            "ADMIN login",
            token is not None,
            f"HTTP {response.status_code}",
        )

        if token:
            headers = {
                "Authorization":
                    f"Bearer {token}"
            }

            check_capabilities(
                regression,
                client,
                headers,
            )

            check_references(
                regression,
                client,
                headers,
            )

            if args.sample:
                run_controlled_match(
                    regression,
                    client,
                    headers,
                    args.sample,
                    args.expected_filename,
                )

            check_latest_history(
                regression,
                client,
                headers,
            )

    if not args.skip_rbac:
        run_rbac(
            regression
        )

    print()
    print("=" * 72)
    print(
        "RESULTADO FINAL"
    )
    print("=" * 72)

    print(
        f"PASS: {regression.passed}"
    )

    print(
        f"FAIL: {regression.failed}"
    )

    print(
        f"TOTAL: {regression.total}"
    )

    if regression.failed == 0:
        print()
        print(
            "BACKEND REGRESSION: PASS"
        )
        print(
            "Backend apto para permanecer "
            "congelado en esta etapa."
        )
        sys.exit(0)

    print()
    print(
        "BACKEND REGRESSION: FAIL"
    )
    print(
        "Revisar los controles marcados "
        "como FAIL antes de continuar."
    )
    sys.exit(1)


if __name__ == "__main__":
    main()