import json
from typing import Dict, Any, List

from sqlalchemy.orm import Session

from app.models import ReferenceDocumentDB


def save_reference_document_db(
    db: Session,
    document: Dict[str, Any],
) -> ReferenceDocumentDB:
    existing = (
        db.query(ReferenceDocumentDB)
        .filter(ReferenceDocumentDB.document_id == document["document_id"])
        .first()
    )

    pii_entities = document.get("pii_entities", [])
    fingerprint = document.get("fingerprint", {})

    if existing:
        existing.filename = document["filename"]
        existing.stored_path = document["stored_path"]
        existing.text = document.get("text", "")
        existing.pii_entities_json = json.dumps(pii_entities, ensure_ascii=False)
        existing.fingerprint_json = json.dumps(fingerprint, ensure_ascii=False)
        db.commit()
        db.refresh(existing)
        return existing

    db_document = ReferenceDocumentDB(
        document_id=document["document_id"],
        filename=document["filename"],
        stored_path=document["stored_path"],
        text=document.get("text", ""),
        pii_entities_json=json.dumps(pii_entities, ensure_ascii=False),
        fingerprint_json=json.dumps(fingerprint, ensure_ascii=False),
    )

    db.add(db_document)
    db.commit()
    db.refresh(db_document)

    return db_document


def list_reference_documents_db(db: Session) -> List[Dict[str, Any]]:
    rows = db.query(ReferenceDocumentDB).order_by(ReferenceDocumentDB.id.asc()).all()

    documents = []

    for row in rows:
        documents.append({
            "document_id": row.document_id,
            "filename": row.filename,
            "stored_path": row.stored_path,
            "text": row.text,
            "pii_entities": json.loads(row.pii_entities_json or "[]"),
            "fingerprint": json.loads(row.fingerprint_json),
        })

    return documents


def clear_reference_documents_db(db: Session) -> int:
    count = db.query(ReferenceDocumentDB).count()
    db.query(ReferenceDocumentDB).delete()
    db.commit()
    return count
def delete_reference_document_db(
    db: Session,
    document_id: str,
) -> Dict[str, Any] | None:
    """
    Elimina una única referencia de SQLite.

    Devuelve información mínima del registro eliminado para permitir
    limpiar también el archivo físico si corresponde.
    """

    row = (
        db.query(ReferenceDocumentDB)
        .filter(
            ReferenceDocumentDB.document_id == document_id
        )
        .first()
    )

    if row is None:
        return None

    deleted_document = {
        "document_id": row.document_id,
        "filename": row.filename,
        "stored_path": row.stored_path,
    }

    db.delete(row)
    db.commit()

    return deleted_document
def get_reference_document_db(
    db: Session,
    document_id: str,
):
    return (
        db.query(ReferenceDocumentDB)
        .filter(
            ReferenceDocumentDB.document_id
            == document_id
        )
        .first()
    )


def update_reference_storage_metadata_db(
    db: Session,
    document_id: str,
    storage_key: str,
    sha256: str,
    size_bytes: int,
    mime_type: str,
):
    document = get_reference_document_db(
        db,
        document_id,
    )

    if document is None:
        return None

    document.storage_key = storage_key
    document.sha256 = sha256
    document.size_bytes = size_bytes
    document.mime_type = mime_type

    db.add(document)
    db.commit()
    db.refresh(document)

    return document