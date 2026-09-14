import hashlib
from typing import Dict, Any, List

from app.services.fingerprint import compare_fingerprints


REFERENCE_INDEX: List[Dict[str, Any]] = []


def add_reference_document(document: Dict[str, Any]) -> Dict[str, Any]:
    REFERENCE_INDEX.append(document)
    return document


def list_reference_documents() -> List[Dict[str, Any]]:
    return REFERENCE_INDEX


def clear_reference_index() -> None:
    REFERENCE_INDEX.clear()


def _tiebreak_key(document_id: str) -> str:
    # Desempate determinista e INSESGADO respecto al orden de inserción
    # (hallazgo #5). Antes, el sort estable favorecía al documento insertado
    # primero; bajo transformaciones duras donde el padre cae a score ~0 y
    # empata con muchos, su rank se volvía posicional. Un hash estable del id
    # reparte los empates de forma reproducible sin privilegiar la posición.
    return hashlib.md5(str(document_id).encode("utf-8")).hexdigest()


def match_against_references(
    query_fingerprint: Dict[str, Any],
    top_k: int = 5,
    w_text: float = 0.35,
    w_layout: float = 0.20,
    w_pii: float = 0.45,
    use_semantic_text: bool = False,
    use_hybrid_text: bool = False,
) -> List[Dict[str, Any]]:
    results = []

    for ref in REFERENCE_INDEX:
        scores = compare_fingerprints(
            query_fingerprint,
            ref["fingerprint"],
            w_text=w_text,
            w_layout=w_layout,
            w_pii=w_pii,
            use_semantic_text=use_semantic_text,
            use_hybrid_text=use_hybrid_text,
        )

        results.append({
            "document_id": ref["document_id"],
            "filename": ref["filename"],
            "scores": scores,
        })

    # Orden por score descendente; empates resueltos por hash del id, NO por
    # orden de inserción.
    results.sort(
        key=lambda item: (-item["scores"]["final_score"], _tiebreak_key(item["document_id"]))
    )

    return results[:top_k]


def match_all_references(
    query_fingerprint: Dict[str, Any],
    w_text: float = 0.35,
    w_layout: float = 0.20,
    w_pii: float = 0.45,
    use_semantic_text: bool = False,
    use_hybrid_text: bool = False,
) -> List[Dict[str, Any]]:
    return match_against_references(
        query_fingerprint=query_fingerprint,
        top_k=len(REFERENCE_INDEX),
        w_text=w_text,
        w_layout=w_layout,
        w_pii=w_pii,
        use_semantic_text=use_semantic_text,
        use_hybrid_text=use_hybrid_text,
    )


def get_reference_document_by_id(document_id: str):
    for ref in REFERENCE_INDEX:
        if ref["document_id"] == document_id:
            return ref
    return None
