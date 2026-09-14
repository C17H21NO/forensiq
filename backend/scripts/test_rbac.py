import os
from getpass import getpass

import requests


BASE_URL = os.getenv(
    "FORENSIQ_BASE_URL",
    "http://127.0.0.1:8000",
).rstrip("/")


USERS = {
    "ADMIN": "admin@forensiq.local",
    "ANALYST": "analyst@forensiq.local",
    "DPO": "dpo@forensiq.local",
}


EXPECTED = {
    "ADMIN": {
        "references": {200},
        "history": {200},
        "users": {200},
        "capabilities": {200},
        "analyze": {415},
        "match": {400},
        "reference_upload": {415},
        "reference_delete": {404},
        "experiment": {200, 400, 404},
    },

    "ANALYST": {
        "references": {200},
        "history": {403},
        "users": {403},
        "capabilities": {200},
        "analyze": {415},
        "match": {400},
        "reference_upload": {403},
        "reference_delete": {403},
        "experiment": {403},
    },

    "DPO": {
        "references": {403},
        "history": {200},
        "users": {403},
        "capabilities": {200},
        "analyze": {415},
        "match": {403},
        "reference_upload": {403},
        "reference_delete": {403},
        "experiment": {403},
    },
}


def login(username: str, password: str) -> str:
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={
            "username": username,
            "password": password,
        },
        timeout=15,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Login falló para {username}: "
            f"HTTP {response.status_code} - {response.text}"
        )

    token = response.json().get("access_token")

    if not token:
        raise RuntimeError(
            f"El login de {username} no devolvió access_token."
        )

    return token


def probe_file():
    """
    Archivo deliberadamente no soportado.

    Si el rol tiene permiso para entrar al endpoint,
    esperamos HTTP 415.

    Si no tiene permiso,
    esperamos HTTP 403 antes del procesamiento.
    """
    return {
        "file": (
            "rbac_probe.txt",
            b"ForensiQ RBAC probe",
            "text/plain",
        )
    }


def execute_probe(name: str, headers: dict):
    if name == "references":
        return requests.get(
            f"{BASE_URL}/references",
            headers=headers,
            timeout=15,
        )

    if name == "history":
        return requests.get(
            f"{BASE_URL}/analysis/history",
            headers=headers,
            timeout=15,
        )

    if name == "users":
        return requests.get(
            f"{BASE_URL}/users",
            headers=headers,
            timeout=15,
        )

    if name == "capabilities":
        return requests.get(
            f"{BASE_URL}/system/capabilities",
            headers=headers,
            timeout=15,
        )

    if name == "analyze":
        return requests.post(
            f"{BASE_URL}/documents/analyze",
            headers=headers,
            files=probe_file(),
            timeout=15,
        )

    if name == "match":
        # top_k=0 es deliberadamente inválido.
        #
        # ADMIN/ANALYST:
        #   pasan autorización -> HTTP 400
        #
        # DPO:
        #   falla autorización -> HTTP 403
        #
        # No se ejecuta matching ni se guarda historial.
        return requests.post(
            f"{BASE_URL}/documents/match",
            headers=headers,
            params={
                "top_k": 0,
            },
            files=probe_file(),
            timeout=15,
        )

    if name == "reference_upload":
        # ADMIN llega hasta validación de archivo -> 415.
        # Otros roles deben detenerse con 403.
        return requests.post(
            f"{BASE_URL}/references/upload",
            headers=headers,
            files=probe_file(),
            timeout=15,
        )

    if name == "reference_delete":
        # ID inexistente para no borrar absolutamente nada.
        return requests.delete(
            f"{BASE_URL}/references/"
            "__FORENSIQ_RBAC_PROBE_DOES_NOT_EXIST__.pdf",
            headers=headers,
            timeout=15,
        )

    if name == "experiment":
        # Documento inexistente:
        #
        # ADMIN pasa RBAC y llegará al control de documento inexistente.
        # ANALYST/DPO deben recibir 403.
        #
        # No se genera ninguna variante.
        return requests.post(
            f"{BASE_URL}/references/"
            "__FORENSIQ_RBAC_PROBE_DOES_NOT_EXIST__.pdf/"
            "variant-and-match",
            headers=headers,
            params={
                "transformation_type": "combined",
                "top_k": 1,
            },
            timeout=15,
        )

    raise ValueError(
        f"Probe desconocido: {name}"
    )


def response_detail(response) -> str:
    try:
        body = response.json()

        if isinstance(body, dict):
            detail = body.get("detail")

            if detail:
                return str(detail)

    except Exception:
        pass

    return response.text[:120].replace("\n", " ")


def main():
    print("=" * 72)
    print("ForensiQ - RBAC regression test")
    print(f"Backend: {BASE_URL}")
    print("=" * 72)

    passwords = {}

    for role, username in USERS.items():
        passwords[role] = getpass(
            f"Password para {role} ({username}): "
        )

    print()
    print("Ejecutando pruebas...")
    print()

    total_tests = 0
    passed_tests = 0

    failures = []

    for role, username in USERS.items():
        print(f"[{role}]")

        try:
            token = login(
                username,
                passwords[role],
            )

        except Exception as exc:
            print(f"  LOGIN              FAIL  {exc}")
            failures.append(
                f"{role}: login"
            )
            print()
            continue

        print("  LOGIN              PASS  HTTP 200")

        headers = {
            "Authorization": f"Bearer {token}"
        }

        for probe_name, expected_statuses in EXPECTED[role].items():
            total_tests += 1

            try:
                response = execute_probe(
                    probe_name,
                    headers,
                )

                status = response.status_code

                passed = (
                    status in expected_statuses
                )

                if passed:
                    passed_tests += 1
                    state = "PASS"
                else:
                    state = "FAIL"

                    failures.append(
                        f"{role}: {probe_name} "
                        f"(HTTP {status}, "
                        f"esperado {sorted(expected_statuses)})"
                    )

                expected_text = "/".join(
                    str(value)
                    for value in sorted(expected_statuses)
                )

                print(
                    f"  {probe_name:<18} "
                    f"{state:<4}  "
                    f"HTTP {status:<3} "
                    f"(esperado {expected_text})"
                )

                if not passed:
                    print(
                        "      ↳ "
                        + response_detail(response)
                    )

            except Exception as exc:
                failures.append(
                    f"{role}: {probe_name} ({exc})"
                )

                print(
                    f"  {probe_name:<18} "
                    f"FAIL  {exc}"
                )

        print()

    print("=" * 72)

    if not failures:
        print(
            f"RESULTADO: PASS — "
            f"{passed_tests}/{total_tests} "
            "controles RBAC aprobados."
        )

        print()
        print("Matriz validada:")
        print()
        print(
            "                ADMIN   ANALYST   DPO"
        )
        print(
            "References       YES      YES      NO"
        )
        print(
            "History          YES      NO       YES"
        )
        print(
            "Users            YES      NO       NO"
        )
        print(
            "Capabilities     YES      YES      YES"
        )
        print(
            "Analyze          YES      YES      YES"
        )
        print(
            "Top-k            YES      YES      NO"
        )
        print(
            "Ref. management  YES      NO       NO"
        )
        print(
            "Experiments      YES      NO       NO"
        )

    else:
        print(
            f"RESULTADO: FAIL — "
            f"{passed_tests}/{total_tests} "
            "controles aprobados."
        )

        print()
        print("Revisar:")

        for failure in failures:
            print(
                f"  - {failure}"
            )

    print("=" * 72)


if __name__ == "__main__":
    main()