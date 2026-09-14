from pathlib import Path

from app.config import BACKEND_DIR, settings
from app.models import ReferenceDocumentDB
from app.services.storage_service import storage


def _resolve_legacy_path(
    stored_path: str | None,
) -> Path | None:
    """
    Compatibilidad temporal con referencias creadas antes
    de la introducción de storage_key.
    """

    if not stored_path:
        return None

    raw_path = Path(stored_path)

    if raw_path.is_absolute():
        candidates = [raw_path]
    else:
        candidates = [
            settings.upload_dir / raw_path,
            BACKEND_DIR / raw_path,
            Path.cwd() / raw_path,
        ]

    for candidate in candidates:
        try:
            resolved = candidate.resolve()

            if resolved.is_file():
                return resolved

        except OSError:
            continue

    return None


def resolve_reference_file(
    document: ReferenceDocumentDB,
) -> tuple[Path, str]:
    """
    Fuente única para resolver el archivo físico de una referencia.

    Prioridad:
        1. storage_key
        2. stored_path legacy

    Returns:
        (path, source)
    """

    if document.storage_key:
        try:
            storage_path = storage.resolve(
                document.storage_key
            )

            if storage_path.is_file():
                return (
                    storage_path,
                    "storage_key",
                )

        except ValueError:
            # Una storage_key inválida nunca se utiliza.
            # Todavía permitimos fallback legacy durante
            # el período de transición.
            pass

    legacy_path = _resolve_legacy_path(
        document.stored_path
    )

    if legacy_path is not None:
        return (
            legacy_path,
            "stored_path_legacy",
        )

    raise FileNotFoundError(
        "No se encontró el archivo físico para "
        f"la referencia {document.document_id}."
    )


def reference_file_exists(
    document: ReferenceDocumentDB,
) -> bool:
    try:
        resolve_reference_file(
            document
        )

        return True

    except FileNotFoundError:
        return False


def reference_storage_status(
    document: ReferenceDocumentDB,
) -> dict:
    """
    Información segura para API.

    No expone rutas absolutas del servidor.
    """

    try:
        _, source = resolve_reference_file(
            document
        )

        available = True

    except FileNotFoundError:
        source = None
        available = False

    return {
        "storage_key": document.storage_key,
        "sha256": document.sha256,
        "size_bytes": document.size_bytes,
        "mime_type": document.mime_type,
        "file_available": available,
        "resolved_via": source,
    }


def delete_reference_file(
    document: ReferenceDocumentDB,
) -> dict:
    """
    Elimina el archivo administrado por ForensiQ.

    Si existe storage_key, SIEMPRE es la fuente preferida.
    stored_path se utiliza únicamente para referencias legacy.
    """

    if document.storage_key:
        try:
            deleted = storage.delete(
                document.storage_key
            )

            if deleted:
                return {
                    "deleted": True,
                    "source": "storage_key",
                }

        except ValueError:
            pass

    legacy_path = _resolve_legacy_path(
        document.stored_path
    )

    if legacy_path is not None:
        legacy_path.unlink(
            missing_ok=True
        )

        return {
            "deleted": True,
            "source": "stored_path_legacy",
        }

    return {
        "deleted": False,
        "source": None,
    }