import os

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import ReferenceDocumentDB
from app.services.matcher import (
    list_reference_documents,
)
from app.services.storage_service import storage


def check_database(
    db: Session,
) -> bool:
    try:
        db.execute(
            text("SELECT 1")
        )

        return True

    except Exception:
        return False


def check_storage() -> bool:
    try:
        # Desarrollo local
        root = getattr(
            storage,
            "root_dir",
            None,
        )

        if root is not None:
            return (
                root.exists()
                and root.is_dir()
                and os.access(
                    root,
                    os.R_OK | os.W_OK,
                )
            )

        # Deployment con S3 / Supabase Storage
        client = getattr(
            storage,
            "client",
            None,
        )
        bucket_name = getattr(
            storage,
            "bucket_name",
            None,
        )

        if client is not None and bucket_name:
            client.list_objects_v2(
                Bucket=bucket_name,
                MaxKeys=1,
            )
            return True

        return False

    except Exception:
        return False


def check_reference_index(
    db: Session,
) -> dict:
    try:
        db_count = (
            db.query(
                ReferenceDocumentDB
            )
            .count()
        )

        memory_count = len(
            list_reference_documents()
        )

        return {
            "ok": (
                db_count
                == memory_count
            ),

            "database_count": (
                db_count
            ),

            "memory_count": (
                memory_count
            ),
        }

    except Exception:
        return {
            "ok": False,
            "database_count": None,
            "memory_count": None,
        }


def run_readiness_checks(
    db: Session,
) -> dict:
    database_ok = check_database(
        db
    )

    storage_ok = check_storage()

    reference_index = (
        check_reference_index(
            db
        )
    )

    ready = (
        database_ok
        and storage_ok
        and reference_index["ok"]
    )

    return {
        "ready": ready,

        "database": database_ok,
        "storage": storage_ok,

        "reference_index": (
            reference_index
        ),
    }