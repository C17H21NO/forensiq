from typing import List, Dict, Any

_SPACY_MODEL = None
_SPACY_LOAD_ATTEMPTED = False


def get_spacy_model():
    global _SPACY_MODEL, _SPACY_LOAD_ATTEMPTED

    if _SPACY_LOAD_ATTEMPTED:
        return _SPACY_MODEL

    _SPACY_LOAD_ATTEMPTED = True

    try:
        import spacy

        _SPACY_MODEL = spacy.load("es_core_news_sm")
        return _SPACY_MODEL

    except Exception as exc:
        print(f"[spaCy] Modelo no disponible: {exc}")
        _SPACY_MODEL = None
        return None


def is_spacy_available() -> bool:
    return get_spacy_model() is not None


def detect_spacy_entities(text: str, max_entities: int = 80) -> List[Dict[str, Any]]:
    """
    Detecta entidades generales con spaCy.
    No reemplaza al detector PII por reglas; lo complementa.
    """

    nlp = get_spacy_model()

    if nlp is None or not text or not text.strip():
        return []

    try:
        doc = nlp(text[:15000])
    except Exception as exc:
        print(f"[spaCy] Error procesando texto: {exc}")
        return []

    entities = []

    for ent in doc.ents[:max_entities]:
        value = ent.text.strip()

        if not value:
            continue

        entities.append({
            "type": f"SPACY_{ent.label_}",
            "value": value,
            "start": ent.start_char,
            "end": ent.end_char,
            "source": "spacy",
        })

    return entities