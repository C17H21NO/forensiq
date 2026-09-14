import argparse
import hashlib
import mimetypes
import shutil
import sys
from pathlib import Path


# =============================================================================
# Permitir ejecutar este script directamente desde backend/scripts
# =============================================================================

BACKEND_ROOT = Path(__file__).resolve().parents[1]

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(BACKEND_ROOT),
    )


from app.config import BACKEND_DIR, settings
from app.database import SessionLocal
from app.models import ReferenceDocumentDB
from app.services.storage_service import storage

CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file_handle:
        while True:
            chunk = file_handle.read(CHUNK_SIZE)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def resolve_legacy_path(
    stored_path: str,
) -> Path | None:
    """
    Intenta resolver rutas antiguas absolutas o relativas.
    """

    if not stored_path:
        return None

    raw = Path(stored_path)

    candidates = []

    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.extend(
            [
                settings.upload_dir / raw,
                BACKEND_DIR / raw,
                Path.cwd() / raw,
            ]
        )

    for candidate in candidates:
        try:
            resolved = candidate.resolve()

            if resolved.is_file():
                return resolved

        except OSError:
            continue

    return None


def build_storage_key(
    document: ReferenceDocumentDB,
    source: Path,
) -> str:
    """
    Genera una clave estable utilizando document_id.

    No se utiliza el filename original directamente para
    evitar problemas con caracteres o directorios.
    """

    safe_document_id = Path(
        str(document.document_id)
    ).name

    if not safe_document_id:
        raise ValueError(
            f"document_id inválido para registro {document.id}"
        )

    # Si document_id no tiene extensión, conservamos
    # la extensión del archivo original.
    if not Path(safe_document_id).suffix:
        safe_document_id += source.suffix.lower()

    return f"references/{safe_document_id}"


def detect_mime_type(
    document: ReferenceDocumentDB,
    source: Path,
) -> str:
    filename = (
        document.filename
        or source.name
    )

    mime_type, _ = mimetypes.guess_type(
        filename
    )

    return (
        mime_type
        or "application/octet-stream"
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Backfill de metadatos de almacenamiento "
            "para referencias ForensiQ."
        )
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Valida y muestra cambios sin modificar "
            "archivos ni base de datos."
        ),
    )

    args = parser.parse_args()

    db = SessionLocal()

    stats = {
        "total": 0,
        "ready": 0,
        "migrated": 0,
        "already_migrated": 0,
        "missing": 0,
        "conflicts": 0,
        "errors": 0,
    }

    print("=" * 76)
    print("ForensiQ - Reference Storage Backfill")

    if args.dry_run:
        print("MODO: DRY-RUN — no se modificará nada")
    else:
        print("MODO: EJECUCIÓN REAL")

    print(f"Storage root: {storage.root_dir}")
    print("=" * 76)

    try:
        documents = (
            db.query(ReferenceDocumentDB)
            .order_by(ReferenceDocumentDB.id.asc())
            .all()
        )

        stats["total"] = len(documents)

        for document in documents:
            print()
            print(
                f"[{document.id}] "
                f"{document.document_id} "
                f"| {document.filename}"
            )

            # -------------------------------------------------------------
            # Ya migrado
            # -------------------------------------------------------------
            if (
                document.storage_key
                and document.sha256
                and document.size_bytes is not None
                and document.mime_type
            ):
                try:
                    existing_path = storage.resolve(
                        document.storage_key
                    )

                    if existing_path.is_file():
                        print(
                            "  STATUS: ya migrado"
                        )

                        print(
                            f"  storage_key: "
                            f"{document.storage_key}"
                        )

                        stats[
                            "already_migrated"
                        ] += 1

                        continue

                except Exception:
                    # Si los metadatos existen pero el archivo
                    # no está presente, intentamos reconstruirlo
                    # desde stored_path.
                    pass

            # -------------------------------------------------------------
            # Resolver archivo antiguo
            # -------------------------------------------------------------
            source = resolve_legacy_path(
                document.stored_path
            )

            if source is None:
                print(
                    "  ERROR: archivo original "
                    "no encontrado"
                )

                print(
                    f"  stored_path: "
                    f"{document.stored_path}"
                )

                stats["missing"] += 1

                continue

            try:
                source_hash = sha256_file(
                    source
                )

                size_bytes = source.stat().st_size

                mime_type = detect_mime_type(
                    document,
                    source,
                )

                storage_key = build_storage_key(
                    document,
                    source,
                )

                destination = storage.resolve(
                    storage_key
                )

                print(
                    f"  source:      {source}"
                )

                print(
                    f"  storage_key: {storage_key}"
                )

                print(
                    f"  size_bytes:  {size_bytes}"
                )

                print(
                    f"  mime_type:   {mime_type}"
                )

                print(
                    f"  sha256:      {source_hash}"
                )

                # ---------------------------------------------------------
                # Verificar posibles conflictos
                # ---------------------------------------------------------
                copy_required = True

                if destination.exists():
                    destination_hash = sha256_file(
                        destination
                    )

                    if destination_hash != source_hash:
                        print(
                            "  ERROR: existe un archivo "
                            "diferente en el destino."
                        )

                        stats["conflicts"] += 1

                        continue

                    print(
                        "  destino ya existe con "
                        "el mismo SHA-256"
                    )

                    copy_required = False

                elif (
                    source.resolve()
                    == destination.resolve()
                ):
                    copy_required = False

                stats["ready"] += 1

                if args.dry_run:
                    print(
                        "  STATUS: listo para migrar"
                    )

                    continue

                # ---------------------------------------------------------
                # Copiar de forma no destructiva
                # ---------------------------------------------------------
                destination.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                created_destination = False

                if copy_required:
                    shutil.copy2(
                        source,
                        destination,
                    )

                    created_destination = True

                # ---------------------------------------------------------
                # Verificación posterior a copia
                # ---------------------------------------------------------
                final_hash = sha256_file(
                    destination
                )

                if final_hash != source_hash:
                    if created_destination:
                        destination.unlink(
                            missing_ok=True
                        )

                    raise RuntimeError(
                        "La verificación SHA-256 "
                        "posterior a la copia falló."
                    )

                # ---------------------------------------------------------
                # Actualizar BD
                #
                # stored_path NO se elimina todavía.
                # ---------------------------------------------------------
                document.storage_key = storage_key
                document.sha256 = source_hash
                document.size_bytes = size_bytes
                document.mime_type = mime_type

                db.add(document)
                db.commit()
                db.refresh(document)

                stats["migrated"] += 1

                print(
                    "  STATUS: migrado correctamente"
                )

            except Exception as exc:
                db.rollback()

                stats["errors"] += 1

                print(
                    f"  ERROR: {type(exc).__name__}: "
                    f"{exc}"
                )

    finally:
        db.close()

    print()
    print("=" * 76)
    print("RESUMEN")
    print("=" * 76)

    for key, value in stats.items():
        print(
            f"{key:<20}: {value}"
        )

    problems = (
        stats["missing"]
        + stats["conflicts"]
        + stats["errors"]
    )

    if problems:
        print()
        print(
            "RESULTADO: FAIL — existen referencias "
            "que requieren revisión."
        )

        sys.exit(1)

    if args.dry_run:
        print()
        print(
            "RESULTADO: PASS — dry-run completado. "
            "No se modificó ningún dato."
        )
    else:
        print()
        print(
            "RESULTADO: PASS — backfill completado."
        )


if __name__ == "__main__":
    main()