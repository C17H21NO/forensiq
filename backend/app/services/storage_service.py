from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

import hashlib

from fastapi import UploadFile

from app.config import settings


@dataclass(frozen=True)
class StoredObject:
    storage_key: str
    stored_filename: str
    absolute_path: Path
    size_bytes: int
    sha256: str


class LocalStorageService:
    """
    Implementación local del almacenamiento de ForensiQ.

    El resto del backend trabajará con storage_key en lugar
    de construir directamente rutas del sistema operativo.

    En desarrollo:
        storage_key -> archivo dentro de settings.upload_dir

    En producción, esta interfaz podrá reemplazarse por un
    backend S3/object-storage sin modificar el pipeline.
    """

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir.resolve()

        self.root_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    def _validate_namespace(
        self,
        namespace: str,
    ) -> str:
        clean = namespace.strip().lower()

        allowed = {
            "references",
            "analysis",
            "temporary",
        }

        if clean not in allowed:
            raise ValueError(
                f"Namespace de almacenamiento no permitido: "
                f"{namespace}"
            )

        return clean

    def _resolve_key(
        self,
        storage_key: str,
    ) -> Path:
        """
        Resuelve una storage_key evitando path traversal.
        """

        clean_key = storage_key.replace(
            "\\",
            "/",
        ).lstrip("/")

        candidate = (
            self.root_dir / clean_key
        ).resolve()

        try:
            candidate.relative_to(
                self.root_dir
            )

        except ValueError as exc:
            raise ValueError(
                "Storage key fuera del directorio permitido."
            ) from exc

        return candidate

    @staticmethod
    def _extension_from_filename(
        filename: str | None,
    ) -> str:
        if not filename:
            return ""

        return Path(
            filename
        ).suffix.lower()

    @staticmethod
    def _hash_file(
        file_handle: BinaryIO,
    ) -> tuple[int, str]:
        sha256 = hashlib.sha256()
        size_bytes = 0

        while True:
            chunk = file_handle.read(
                1024 * 1024
            )

            if not chunk:
                break

            size_bytes += len(chunk)

            sha256.update(chunk)

        return (
            size_bytes,
            sha256.hexdigest(),
        )

    def save_upload(
        self,
        upload: UploadFile,
        namespace: str,
    ) -> StoredObject:
        namespace = self._validate_namespace(
            namespace
        )

        extension = self._extension_from_filename(
            upload.filename
        )

        stored_filename = (
            f"{uuid4().hex}{extension}"
        )

        storage_key = (
            f"{namespace}/{stored_filename}"
        )

        destination = self._resolve_key(
            storage_key
        )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        upload.file.seek(0)

        sha256 = hashlib.sha256()
        size_bytes = 0

        try:
            with destination.open(
                "wb"
            ) as output:
                while True:
                    chunk = upload.file.read(
                        1024 * 1024
                    )

                    if not chunk:
                        break

                    output.write(chunk)

                    sha256.update(chunk)

                    size_bytes += len(chunk)

        except Exception:
            destination.unlink(
                missing_ok=True
            )

            raise

        finally:
            upload.file.seek(0)

        return StoredObject(
            storage_key=storage_key,
            stored_filename=stored_filename,
            absolute_path=destination,
            size_bytes=size_bytes,
            sha256=sha256.hexdigest(),
        )
    def save_local_file(
        self,
        source_path: str | Path,
        namespace: str,
    ) -> StoredObject:
        """
        Incorpora al almacenamiento administrado un archivo
        que ya existe localmente.

        Se utiliza, por ejemplo, para documentos generados
        internamente por herramientas experimentales.
        """

        namespace = self._validate_namespace(
            namespace
        )

        source = Path(
            source_path
        ).resolve()

        if not source.is_file():
            raise FileNotFoundError(
                f"Archivo fuente no encontrado: {source}"
            )

        extension = source.suffix.lower()

        stored_filename = (
            f"{uuid4().hex}{extension}"
        )

        storage_key = (
            f"{namespace}/{stored_filename}"
        )

        destination = self._resolve_key(
            storage_key
        )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        sha256 = hashlib.sha256()
        size_bytes = 0

        try:
            with source.open("rb") as input_file:
                with destination.open("wb") as output_file:
                    while True:
                        chunk = input_file.read(
                            1024 * 1024
                        )

                        if not chunk:
                            break

                        output_file.write(
                            chunk
                        )

                        sha256.update(
                            chunk
                        )

                        size_bytes += len(
                            chunk
                        )

        except Exception:
            destination.unlink(
                missing_ok=True
            )

            raise

        return StoredObject(
            storage_key=storage_key,
            stored_filename=stored_filename,
            absolute_path=destination,
            size_bytes=size_bytes,
            sha256=sha256.hexdigest(),
        )
    def delete(
        self,
        storage_key: str,
    ) -> bool:
        path = self._resolve_key(
            storage_key
        )

        if not path.exists():
            return False

        if not path.is_file():
            raise ValueError(
                "La storage key no corresponde "
                "a un archivo."
            )

        path.unlink()

        return True

    def exists(
        self,
        storage_key: str,
    ) -> bool:
        return self._resolve_key(
            storage_key
        ).is_file()

    def resolve(
        self,
        storage_key: str,
    ) -> Path:
        """
        Solo debe utilizarse internamente cuando una librería
        necesita una ruta local real (PyMuPDF, OCR, etc.).
        """

        return self._resolve_key(
            storage_key
        )


storage = LocalStorageService(
    settings.upload_dir
)