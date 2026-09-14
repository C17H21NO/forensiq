import json
from pathlib import Path
from typing import Dict, Any, List

from sqlalchemy.orm import Session

from app.models import AnalysisHistoryDB


def infer_file_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower().replace(".", "")
    return suffix.upper() if suffix else "UNKNOWN"


def _sanitize_production_scores(
    scores: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Conserva únicamente los campos que pertenecen al contrato
    productivo OE3.

    Se eliminan aliases legacy como:
    - final_score
    - selected_text_score
    - semantic_text_score
    - hybrid_text_score
    - pii_score

    Esos campos pueden seguir existiendo temporalmente en la respuesta
    de matching para compatibilidad con el frontend TP1, pero no deben
    formar parte del historial productivo nuevo.
    """

    return {
        "ranking_score": scores.get("ranking_score"),
        "text_score": scores.get("text_score"),
        "layout_score": scores.get("layout_score"),
        "pii_context_score": scores.get("pii_context_score"),
        "ranking_model": scores.get("ranking_model"),
    }


def _sanitize_production_explanation(
    explanation: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Conserva la explicación válida para OE3.
    """

    if not explanation:
        return {}

    return {
        "ranking_basis": explanation.get("ranking_basis"),
        "ranking_score": explanation.get("ranking_score"),
        "similarity_level": explanation.get("similarity_level"),
        "explanation": explanation.get("explanation"),
        "auxiliary_evidence": explanation.get(
            "auxiliary_evidence",
            {},
        ),
        "auxiliary_note": explanation.get("auxiliary_note"),
    }


def _sanitize_production_match(
    match: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Genera la representación de un candidato que puede persistirse
    en el historial OE3.
    """

    return {
        "document_id": match.get("document_id"),
        "filename": match.get("filename"),
        "scores": _sanitize_production_scores(
            match.get("scores", {})
        ),
        "analyst_explanation": _sanitize_production_explanation(
            match.get("analyst_explanation", {})
        ),
    }


def save_analysis_history_db(
    db: Session,
    result: Dict[str, Any],
    latency_ms: float | None = None,
) -> AnalysisHistoryDB:
    """
    Guarda una ejecución del flujo productivo OE3.

    El mejor resultado se registra utilizando ranking_score,
    no el antiguo final_score multimodal.
    """

    raw_matches = result.get("matches", [])

    production_matches = [
        _sanitize_production_match(match)
        for match in raw_matches
    ]

    best_match = (
        production_matches[0]
        if production_matches
        else {}
    )

    best_scores = (
        best_match.get("scores", {})
        if best_match
        else {}
    )

    best_ranking_score = best_scores.get("ranking_score")

    row = AnalysisHistoryDB(
        filename=result.get(
            "filename",
            "documento_sospechoso",
        ),

        file_type=infer_file_type(
            result.get("filename", "")
        ),

        pii_count=result.get("pii_count", 0),

        latency_ms=(
            str(round(latency_ms, 2))
            if latency_ms is not None
            else None
        ),

        best_match_document_id=best_match.get(
            "document_id"
        ),

        best_match_filename=best_match.get(
            "filename"
        ),

        # La columna conserva su nombre histórico en SQLite,
        # pero desde OE3 almacena ranking_score.
        best_match_score=(
            str(best_ranking_score)
            if best_ranking_score is not None
            else None
        ),

        matches_json=json.dumps(
            production_matches,
            ensure_ascii=False,
        ),
    )

    db.add(row)
    db.commit()
    db.refresh(row)

    return row


def list_analysis_history_db(
    db: Session,
) -> List[Dict[str, Any]]:
    """
    Devuelve tanto registros históricos TP1 como registros nuevos OE3
    sin reinterpretar silenciosamente los resultados antiguos.
    """

    rows = (
        db.query(AnalysisHistoryDB)
        .order_by(AnalysisHistoryDB.created_at.desc())
        .all()
    )

    results = []

    for row in rows:
        try:
            matches = json.loads(
                row.matches_json or "[]"
            )
        except (TypeError, json.JSONDecodeError):
            matches = []

        # Los registros nuevos OE3 contienen ranking_score.
        is_oe3_record = bool(
            matches
            and isinstance(matches[0], dict)
            and "ranking_score"
            in matches[0].get("scores", {})
        )

        if is_oe3_record:
            clean_matches = [
                _sanitize_production_match(match)
                for match in matches
            ]

            best_match_ranking_score = (
                row.best_match_score
            )

            contract_version = "oe3_production_v1"

        else:
            # No transformamos los registros TP1 porque su
            # final_score representaba otra formulación.
            clean_matches = matches

            best_match_ranking_score = None
            contract_version = "legacy_tp1"

        results.append(
            {
                "id": row.id,
                "filename": row.filename,
                "file_type": row.file_type,
                "pii_count": row.pii_count,
                "latency_ms": row.latency_ms,

                "best_match_document_id": (
                    row.best_match_document_id
                ),

                "best_match_filename": (
                    row.best_match_filename
                ),

                # Campo correcto para registros OE3.
                "best_match_ranking_score": (
                    best_match_ranking_score
                ),

                # Alias histórico temporal.
                # Lo retiraremos cuando migremos completamente
                # el frontend.
                "best_match_score": row.best_match_score,

                "contract_version": contract_version,

                "matches": clean_matches,

                "created_at": (
                    row.created_at.isoformat()
                    if row.created_at
                    else None
                ),
            }
        )

    return results


def clear_analysis_history_db(
    db: Session,
) -> int:
    count = db.query(AnalysisHistoryDB).count()

    db.query(AnalysisHistoryDB).delete()
    db.commit()

    return count