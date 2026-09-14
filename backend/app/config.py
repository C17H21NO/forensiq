import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR / ".env"

load_dotenv(ENV_FILE)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)

    if value is None:
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(
            f"La variable {name} debe contener un número entero."
        ) from exc


def _env_list(
    name: str,
    default: List[str],
) -> List[str]:
    raw_value = os.getenv(name)

    if not raw_value:
        return default

    return [
        item.strip()
        for item in raw_value.split(",")
        if item.strip()
    ]


@dataclass(frozen=True)
class Settings:
    # Entorno
    app_env: str

    # API
    app_name: str
    app_version: str
    log_level: str

    # Tokens
    token_signing_secret: str
    token_ttl_seconds: int

    # Passwords
    legacy_password_secret: str
    allow_legacy_password_hashes: bool
    pbkdf2_iterations: int

    # Usuarios demo
    enable_demo_users: bool

    # CORS
    cors_origins: List[str]

    # Persistencia
    database_url: str

    # Archivos
    upload_dir: Path
    max_upload_mb: int
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


def build_settings() -> Settings:
    app_env = os.getenv(
        "FORENSIQ_ENV",
        "development",
    ).strip().lower()

    default_database_path = (
        BACKEND_DIR / "forensiq.sqlite3"
    )

    database_url = os.getenv(
        "FORENSIQ_DATABASE_URL",
        f"sqlite:///{default_database_path}",
    )

    upload_dir = Path(
        os.getenv(
            "FORENSIQ_UPLOAD_DIR",
            str(BACKEND_DIR / "app" / "uploads"),
        )
    ).resolve()

    # -------------------------------------------------------------------------
    # Token signing
    #
    # Este secreto sirve EXCLUSIVAMENTE para firmar tokens.
    # Ya no interviene en passwords.
    # -------------------------------------------------------------------------
    token_signing_secret = os.getenv(
        "FORENSIQ_TOKEN_SIGNING_SECRET",
        "forensiq-development-token-secret-change-me",
    )
    # -------------------------------------------------------------------------
    # Compatibilidad con hashes antiguos
    #
    # Este es el secreto utilizado por la versión TP1 para:
    # SHA256(username:password:SECRET)
    #
    # Solo existe para permitir migración transparente.
    # -------------------------------------------------------------------------
    legacy_password_secret = os.getenv(
        "FORENSIQ_LEGACY_PASSWORD_SECRET",
        "",
    )
    
    log_level=os.getenv(
        "FORENSIQ_LOG_LEVEL",
        "INFO",
    ).upper(),

    settings = Settings(
        app_env=app_env,

        app_name=os.getenv(
            "FORENSIQ_APP_NAME",
            "ForensiQ Fingerprint API",
        ),

        app_version=os.getenv(
            "FORENSIQ_APP_VERSION",
            "0.2.0",
        ),
        log_level=os.getenv(
            "FORENSIQ_LOG_LEVEL",
            "INFO",
        ).strip().upper(),

        token_signing_secret=token_signing_secret,

        token_ttl_seconds=_env_int(
            "FORENSIQ_TOKEN_TTL_SECONDS",
            60 * 60 * 8,
        ),

        legacy_password_secret=legacy_password_secret,

        allow_legacy_password_hashes=_env_bool(
            "FORENSIQ_ALLOW_LEGACY_PASSWORD_HASHES",
            default=False,
        ),

        # PBKDF2-HMAC-SHA256
        pbkdf2_iterations=_env_int(
            "FORENSIQ_PBKDF2_ITERATIONS",
            600_000,
        ),

        enable_demo_users=_env_bool(
            "FORENSIQ_ENABLE_DEMO_USERS",
            default=False,
        ),

        cors_origins=_env_list(
            "FORENSIQ_CORS_ORIGINS",
            [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:5174",
                "http://127.0.0.1:5174",
            ],
        ),

        database_url=database_url,

        upload_dir=upload_dir,

        max_upload_mb=_env_int(
            "FORENSIQ_MAX_UPLOAD_MB",
            20,
        ),
    )

    if settings.pbkdf2_iterations < 100_000:
        raise RuntimeError(
            "FORENSIQ_PBKDF2_ITERATIONS no debe ser menor "
            "a 100000."
        )
    if (
        settings.allow_legacy_password_hashes
        and not settings.legacy_password_secret
    ):
        raise RuntimeError(
            "FORENSIQ_LEGACY_PASSWORD_SECRET es obligatorio "
            "cuando se habilitan hashes legacy."
        )
    # -------------------------------------------------------------------------
    # Reglas estrictas para producción
    # -------------------------------------------------------------------------
    if settings.is_production:
        if (
            not settings.token_signing_secret
            or settings.token_signing_secret
            == "forensiq-development-token-secret-change-me"
        ):
            raise RuntimeError(
                "FORENSIQ_TOKEN_SIGNING_SECRET debe configurarse "
                "explícitamente en producción."
            )

        if len(settings.token_signing_secret) < 32:
            raise RuntimeError(
                "FORENSIQ_TOKEN_SIGNING_SECRET debe tener al menos "
                "32 caracteres."
            )

        if settings.enable_demo_users:
            raise RuntimeError(
                "Los usuarios demo no pueden estar habilitados "
                "en producción."
            )
        if settings.allow_legacy_password_hashes:
            raise RuntimeError(
                "Los hashes legacy no pueden habilitarse "
                "en producción."
            )
    settings.upload_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return settings


settings = build_settings()