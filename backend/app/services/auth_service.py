import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Dict, Optional

from app.config import settings


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_DIGEST = "sha256"
PASSWORD_SALT_BYTES = 16
PASSWORD_DKLEN = 32


def _b64encode(raw: bytes) -> str:
    return (
        base64.urlsafe_b64encode(raw)
        .decode("utf-8")
        .rstrip("=")
    )


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)

    return base64.urlsafe_b64decode(
        (value + padding).encode("utf-8")
    )


# =============================================================================
# Password hashing - PBKDF2
# =============================================================================

def _derive_pbkdf2(
    password: str,
    salt: bytes,
    iterations: int,
) -> bytes:
    return hashlib.pbkdf2_hmac(
        PASSWORD_DIGEST,
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=PASSWORD_DKLEN,
    )


def hash_password(
    password: str,
    _legacy_salt: Optional[str] = None,
) -> str:
    """
    Genera hashes nuevos mediante PBKDF2-HMAC-SHA256.

    El segundo parámetro se conserva temporalmente para compatibilidad
    con llamadas antiguas como:

        hash_password(password, username)

    pero ya NO se utiliza como salt.

    Cada contraseña recibe un salt criptográficamente aleatorio.
    """

    if not password:
        raise ValueError(
            "La contraseña no puede estar vacía."
        )

    salt = secrets.token_bytes(
        PASSWORD_SALT_BYTES
    )

    iterations = settings.pbkdf2_iterations

    derived = _derive_pbkdf2(
        password=password,
        salt=salt,
        iterations=iterations,
    )

    return (
        f"{PASSWORD_SCHEME}"
        f"${iterations}"
        f"${_b64encode(salt)}"
        f"${_b64encode(derived)}"
    )


def _verify_pbkdf2_password(
    password: str,
    password_hash: str,
) -> bool:
    try:
        (
            scheme,
            iterations_raw,
            salt_encoded,
            expected_encoded,
        ) = password_hash.split("$", 3)

        if scheme != PASSWORD_SCHEME:
            return False

        iterations = int(iterations_raw)

        if iterations < 1:
            return False

        salt = _b64decode(
            salt_encoded
        )

        expected = _b64decode(
            expected_encoded
        )

        actual = _derive_pbkdf2(
            password=password,
            salt=salt,
            iterations=iterations,
        )

        return hmac.compare_digest(
            actual,
            expected,
        )

    except (
        ValueError,
        TypeError,
        base64.binascii.Error,
    ):
        return False


# =============================================================================
# Compatibilidad con hashes TP1
# =============================================================================

def _legacy_hash_password(
    password: str,
    legacy_salt: str,
) -> str:
    """
    Reproduce únicamente el algoritmo antiguo:

        SHA256(username:password:legacy_secret)

    Se utiliza para migrar usuarios existentes.

    NO se utiliza para crear usuarios nuevos.
    """

    message = (
        f"{legacy_salt}:"
        f"{password}:"
        f"{settings.legacy_password_secret}"
    ).encode("utf-8")

    return hashlib.sha256(
        message
    ).hexdigest()


def _looks_like_legacy_hash(
    password_hash: str,
) -> bool:
    if not password_hash:
        return False

    if len(password_hash) != 64:
        return False

    try:
        int(password_hash, 16)
        return True

    except ValueError:
        return False


def verify_password(
    password: str,
    legacy_salt: str,
    password_hash: str,
) -> bool:
    """
    Verifica tanto hashes modernos PBKDF2 como hashes TP1.

    El parámetro legacy_salt actualmente corresponde al username
    y solo se utiliza para hashes históricos.
    """

    if not password_hash:
        return False

    if password_hash.startswith(
        f"{PASSWORD_SCHEME}$"
    ):
        return _verify_pbkdf2_password(
            password,
            password_hash,
        )

    if (
        settings.allow_legacy_password_hashes
        and _looks_like_legacy_hash(password_hash)
    ):
        expected = _legacy_hash_password(
            password=password,
            legacy_salt=legacy_salt,
        )

        return hmac.compare_digest(
            expected,
            password_hash,
        )

    return False


def password_hash_needs_upgrade(
    password_hash: str,
) -> bool:
    """
    Determina si un hash debe migrarse.

    Casos:
    - hash TP1 -> sí
    - PBKDF2 con menos iteraciones que la configuración actual -> sí
    """

    if not password_hash:
        return True

    if _looks_like_legacy_hash(
        password_hash
    ):
        return True

    if not password_hash.startswith(
        f"{PASSWORD_SCHEME}$"
    ):
        return True

    try:
        _, iterations_raw, _, _ = (
            password_hash.split("$", 3)
        )

        stored_iterations = int(
            iterations_raw
        )

        return (
            stored_iterations
            < settings.pbkdf2_iterations
        )

    except (
        ValueError,
        TypeError,
    ):
        return True


# =============================================================================
# Tokens
# =============================================================================

def create_access_token(
    payload: Dict[str, str],
    ttl_seconds: Optional[int] = None,
) -> str:
    """
    Crea un token firmado mediante HMAC-SHA256.

    El secreto del token es independiente del sistema de passwords.
    """

    effective_ttl = (
        ttl_seconds
        if ttl_seconds is not None
        else settings.token_ttl_seconds
    )

    now = int(
        time.time()
    )

    token_payload = {
        **payload,
        "iat": now,
        "exp": now + effective_ttl,
        "ver": 1,
    }

    body = _b64encode(
        json.dumps(
            token_payload,
            separators=(",", ":"),
        ).encode("utf-8")
    )

    signature = hmac.new(
        settings.token_signing_secret.encode(
            "utf-8"
        ),
        body.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    return (
        f"{body}."
        f"{_b64encode(signature)}"
    )


def decode_access_token(
    token: str,
) -> Optional[Dict[str, str]]:
    """
    Valida firma y expiración del token.
    """

    try:
        body, signature = token.split(
            ".",
            1,
        )

        expected_signature = hmac.new(
            settings.token_signing_secret.encode(
                "utf-8"
            ),
            body.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        if not hmac.compare_digest(
            _b64encode(expected_signature),
            signature,
        ):
            return None

        payload = json.loads(
            _b64decode(body).decode(
                "utf-8"
            )
        )

        now = int(
            time.time()
        )

        exp = int(
            payload.get("exp", 0)
        )

        iat = int(
            payload.get("iat", 0)
        )

        if exp <= now:
            return None

        if iat > now + 60:
            return None

        if not payload.get("sub"):
            return None

        return payload

    except (
        ValueError,
        TypeError,
        json.JSONDecodeError,
        base64.binascii.Error,
    ):
        return None