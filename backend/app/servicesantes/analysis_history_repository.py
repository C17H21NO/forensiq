import json
from pathlib import Path
from typing import Dict, Any, List

from sqlalchemy.orm import Session

from app.models import AnalysisHistoryDB


def infer_file_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower().replace(".", "")
    return suffix.upper() if suffix else "UNKNOWN"


def save_analysis_history_db(
    db: Session,
    result: Dict[str, Any],
    latency_ms: float | None = None,
) -> AnalysisHistoryDB:
    matches = result.get("matches", [])
    best_match = matches[0] if matches else {}

    best_scores = best_match.get("scores", {}) if best_match else {}

    row = AnalysisHistoryDB(
        filename=result.get("filename", "documento_sospechoso"),
        file_type=infer_file_type(result.get("filename", "")),
        pii_count=result.get("pii_count", 0),
        latency_ms=str(round(latency_ms, 2)) if latency_ms is not None else None,
        best_match_document_id=best_match.get("document_id"),
        best_match_filename=best_match.get("filename"),
        best_match_score=str(best_scores.get("final_score")) if best_scores else None,
        matches_json=json.dumps(matches, ensure_ascii=False),
    )

    db.add(row)
    db.commit()
    db.refresh(row)

    return row


def list_analysis_history_db(db: Session) -> List[Dict[str, Any]]:
    rows = (
        db.query(AnalysisHistoryDB)
        .order_by(AnalysisHistoryDB.created_at.desc())
        .all()
    )

    results = []

    for row in rows:
        results.append({
            "id": row.id,
            "filename": row.filename,
            "file_type": row.file_type,
            "pii_count": row.pii_count,
            "latency_ms": row.latency_ms,
            "best_match_document_id": row.best_match_document_id,
            "best_match_filename": row.best_match_filename,
            "best_match_score": row.best_match_score,
            "matches": json.loads(row.matches_json or "[]"),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })

    return results


def clear_analysis_history_db(db: Session) -> int:
    count = db.query(AnalysisHistoryDB).count()
    db.query(AnalysisHistoryDB).delete()
    db.commit()
    return count