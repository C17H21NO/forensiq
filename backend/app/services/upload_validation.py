from pathlib import Path
from typing import Dict, Any

from fastapi import HTTPException, UploadFile


# =============================================================================
# Validación de archivos ForensiQ
# =============================================================================

MAX_UPLOAD_MB = 20
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
}


def _has_valid_signature(extension: str, header: bytes) -> bool:
    """
    Validación básica de firma/magic bytes.

    No se confía únicamente en la extensión proporcionada por el usuario.
    """

    if extension == ".pdf":
        return header.startswith(b"%PDF-")

    if extension == ".docx":
        # DOCX es internamente un archivo ZIP.
        return header.startswith(b"PK")

    if extension == ".png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")

    if extension in {".jpg", ".jpeg"}:
        return header.startswith(b"\xff\xd8\xff")

    if extension in {".tif", ".tiff"}:
        return (
            header.startswith(b"II*\x00")
            or header.startswith(b"MM\x00*")
        )

    if extension == ".bmp":
        return header.startswith(b"BM")

    if extension == ".webp":
        return (
            len(header) >= 12
            and header[:4] == b"RIFF"
            and header[8:12] == b"WEBP"
        )

    return False


def validate_upload_file(
    file: UploadFile,
) -> Dict[str, Any]:
    """
    Valida un archivo antes de almacenarlo o procesarlo.

    Comprueba:
    - nombre existente;
    - extensión permitida;
    - archivo no vacío;
    - tamaño máximo;
    - firma básica coherente con su extensión.
    """

    original_filename = (file.filename or "").strip()

    if not original_filename:
        raise HTTPException(
            status_code=400,
            detail="El archivo no tiene un nombre válido.",
        )

    extension = Path(original_filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                "Formato de archivo no soportado. "
                "Formatos permitidos: PDF, DOCX, PNG, JPG, JPEG, "
                "TIF, TIFF, BMP y WEBP."
            ),
        )

    # -------------------------------------------------------------------------
    # Tamaño
    # -------------------------------------------------------------------------
    try:
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="No fue posible determinar el tamaño del archivo.",
        )

    if file_size <= 0:
        raise HTTPException(
            status_code=400,
            detail="El archivo está vacío.",
        )

    if file_size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"El archivo supera el tamaño máximo permitido "
                f"de {MAX_UPLOAD_MB} MB."
            ),
        )

    # -------------------------------------------------------------------------
    # Firma / magic bytes
    # -------------------------------------------------------------------------
    try:
        header = file.file.read(16)
        file.file.seek(0)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="No fue posible leer el archivo.",
        )

    if not _has_valid_signature(extension, header):
        raise HTTPException(
            status_code=415,
            detail=(
                "El contenido del archivo no coincide con el formato "
                "declarado por su extensión."
            ),
        )

    return {
        "original_filename": original_filename,
        "extension": extension,
        "size_bytes": file_size,
        "size_mb": round(file_size / (1024 * 1024), 3),
    }