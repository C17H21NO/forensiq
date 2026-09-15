from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

import hashlib
import os

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
    Almacenamiento local utilizado durante desarrollo.
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
                f"Namespace de almacenamiento no permitido: {namespace}"
            )

        return clean

    def _resolve_key(
        self,
        storage_key: str,
    ) -> Path:
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

        return Path(filename).suffix.lower()

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
            with destination.open("wb") as output:
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

                        output_file.write(chunk)
                        sha256.update(chunk)
                        size_bytes += len(chunk)

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
                "La storage key no corresponde a un archivo."
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
        return self._resolve_key(
            storage_key
        )


class S3StorageService:
    """
    Storage persistente compatible con S3.

    En deployment-qa se utiliza con Supabase Storage.

    Los archivos originales permanecen en S3.
    Cuando alguna librería necesita una ruta física
    (PyMuPDF, OCR, etc.), el objeto se descarga a un
    cache local temporal.
    """

    def __init__(
        self,
        endpoint_url: str,
        region_name: str,
        bucket_name: str,
        access_key: str,
        secret_key: str,
        cache_dir: Path,
    ):
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise RuntimeError(
                "El backend S3 requiere boto3."
            ) from exc

        self.bucket_name = bucket_name

        self.cache_dir = cache_dir.resolve()
        self.cache_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(
                signature_version="s3v4",
                s3={
                    "addressing_style": "path",
                },
            ),
        )

    @staticmethod
    def _validate_namespace(
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
                f"Namespace de almacenamiento no permitido: {namespace}"
            )

        return clean

    @staticmethod
    def _extension_from_filename(
        filename: str | None,
    ) -> str:
        if not filename:
            return ""

        return Path(filename).suffix.lower()

    def _validate_storage_key(
        self,
        storage_key: str,
    ) -> str:
        clean = storage_key.replace(
            "\\",
            "/",
        ).lstrip("/")

        if not clean:
            raise ValueError(
                "Storage key vacía."
            )

        parts = Path(clean).parts

        if ".." in parts:
            raise ValueError(
                "Storage key inválida."
            )

        namespace = parts[0]

        if namespace not in {
            "references",
            "analysis",
            "temporary",
        }:
            raise ValueError(
                "Namespace de storage key no permitido."
            )

        return clean

    def _cache_path(
        self,
        storage_key: str,
    ) -> Path:
        clean = self._validate_storage_key(
            storage_key
        )

        candidate = (
            self.cache_dir / clean
        ).resolve()

        try:
            candidate.relative_to(
                self.cache_dir
            )

        except ValueError as exc:
            raise ValueError(
                "Storage key fuera del cache permitido."
            ) from exc

        return candidate

    @staticmethod
    def _hash_path(
        path: Path,
    ) -> tuple[int, str]:
        sha256 = hashlib.sha256()
        size_bytes = 0

        with path.open("rb") as file_handle:
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

    def _upload_path(
        self,
        path: Path,
        storage_key: str,
    ) -> None:
        with path.open("rb") as file_handle:
            self.client.upload_fileobj(
                file_handle,
                self.bucket_name,
                storage_key,
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

        cache_path = self._cache_path(
            storage_key
        )

        cache_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        upload.file.seek(0)

        try:
            with cache_path.open("wb") as output:
                while True:
                    chunk = upload.file.read(
                        1024 * 1024
                    )

                    if not chunk:
                        break

                    output.write(chunk)

            size_bytes, sha256 = self._hash_path(
                cache_path
            )

            self._upload_path(
                cache_path,
                storage_key,
            )

        except Exception:
            cache_path.unlink(
                missing_ok=True
            )
            raise

        finally:
            upload.file.seek(0)

        return StoredObject(
            storage_key=storage_key,
            stored_filename=stored_filename,
            absolute_path=cache_path,
            size_bytes=size_bytes,
            sha256=sha256,
        )

    def save_local_file(
        self,
        source_path: str | Path,
        namespace: str,
    ) -> StoredObject:
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

        cache_path = self._cache_path(
            storage_key
        )

        cache_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        try:
            with source.open("rb") as input_file:
                with cache_path.open("wb") as output_file:
                    while True:
                        chunk = input_file.read(
                            1024 * 1024
                        )

                        if not chunk:
                            break

                        output_file.write(chunk)

            size_bytes, sha256 = self._hash_path(
                cache_path
            )

            self._upload_path(
                cache_path,
                storage_key,
            )

        except Exception:
            cache_path.unlink(
                missing_ok=True
            )
            raise

        return StoredObject(
            storage_key=storage_key,
            stored_filename=stored_filename,
            absolute_path=cache_path,
            size_bytes=size_bytes,
            sha256=sha256,
        )

    def delete(
        self,
        storage_key: str,
    ) -> bool:
        clean = self._validate_storage_key(
            storage_key
        )

        existed = self.exists(
            clean
        )

        if not existed:
            return False

        self.client.delete_object(
            Bucket=self.bucket_name,
            Key=clean,
        )

        self._cache_path(
            clean
        ).unlink(
            missing_ok=True
        )

        return True

    def exists(
        self,
        storage_key: str,
    ) -> bool:
        clean = self._validate_storage_key(
            storage_key
        )

        try:
            self.client.head_object(
                Bucket=self.bucket_name,
                Key=clean,
            )
            return True

        except Exception as exc:
            response = getattr(
                exc,
                "response",
                {},
            )

            status = (
                response
                .get("ResponseMetadata", {})
                .get("HTTPStatusCode")
            )

            if status == 404:
                return False

            error_code = (
                response
                .get("Error", {})
                .get("Code")
            )

            if error_code in {
                "404",
                "NoSuchKey",
                "NotFound",
            }:
                return False

            raise

    def resolve(
        self,
        storage_key: str,
    ) -> Path:
        clean = self._validate_storage_key(
            storage_key
        )

        cache_path = self._cache_path(
            clean
        )

        if cache_path.is_file():
            return cache_path

        cache_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        try:
            self.client.download_file(
                self.bucket_name,
                clean,
                str(cache_path),
            )

        except Exception:
            cache_path.unlink(
                missing_ok=True
            )
            raise FileNotFoundError(
                f"No se encontró el objeto S3: {clean}"
            )

        return cache_path


def build_storage_service():
    backend = os.getenv(
        "FORENSIQ_STORAGE_BACKEND",
        "local",
    ).strip().lower()

    if backend == "local":
        return LocalStorageService(
            settings.upload_dir
        )

    if backend == "s3":
        required = {
            "FORENSIQ_S3_ENDPOINT":
                os.getenv("FORENSIQ_S3_ENDPOINT"),
            "FORENSIQ_S3_REGION":
                os.getenv("FORENSIQ_S3_REGION"),
            "FORENSIQ_S3_BUCKET":
                os.getenv("FORENSIQ_S3_BUCKET"),
            "FORENSIQ_S3_ACCESS_KEY":
                os.getenv("FORENSIQ_S3_ACCESS_KEY"),
            "FORENSIQ_S3_SECRET_KEY":
                os.getenv("FORENSIQ_S3_SECRET_KEY"),
        }

        missing = [
            key
            for key, value in required.items()
            if not value
        ]

        if missing:
            raise RuntimeError(
                "Configuración S3 incompleta. Faltan: "
                + ", ".join(missing)
            )

        cache_dir = Path(
            os.getenv(
                "FORENSIQ_STORAGE_CACHE_DIR",
                str(settings.upload_dir / "_s3_cache"),
            )
        )

        return S3StorageService(
            endpoint_url=required[
                "FORENSIQ_S3_ENDPOINT"
            ],
            region_name=required[
                "FORENSIQ_S3_REGION"
            ],
            bucket_name=required[
                "FORENSIQ_S3_BUCKET"
            ],
            access_key=required[
                "FORENSIQ_S3_ACCESS_KEY"
            ],
            secret_key=required[
                "FORENSIQ_S3_SECRET_KEY"
            ],
            cache_dir=cache_dir,
        )

    raise RuntimeError(
        f"FORENSIQ_STORAGE_BACKEND no soportado: {backend}"
    )


storage = build_storage_service()