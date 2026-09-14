import re
from typing import Any, Dict, List, Optional


# =============================================================================
# Evidencia contextual ForensiQ - OE3
# =============================================================================
#
# Este módulo extrae información descriptiva útil para la revisión humana.
#
# IMPORTANTE:
# - Nada de lo producido aquí participa en ranking_score.
# - PII se expone enmascarada.
# - La información financiera se presenta únicamente como contexto.
# =============================================================================


DOCUMENT_TYPE_PATTERN = re.compile(
    r"Tipo\s+documental\s*:\s*([^\n\r]+)",
    re.IGNORECASE,
)

AMOUNT_PATTERN = re.compile(
    r"(?:S\/\.?|PEN)\s*"
    r"(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})|\d+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)

DATE_PATTERN = re.compile(
    r"\b"
    r"(20\d{2}|19\d{2})"
    r"[-/]"
    r"(0[1-9]|1[0-2])"
    r"[-/]"
    r"(0[1-9]|[12]\d|3[01])"
    r"\b"
)

OPERATION_CODE_PATTERN = re.compile(
    r"\bOP-\d+\b",
    re.IGNORECASE,
)
LABELED_PERSON_NAME_PATTERN = re.compile(
    r"(?im)^"
    r"(?:Nombre\s+completo|Nombre\s+del\s+cliente|Nombre\s+del\s+titular)"
    r"[ \t]*:[ \t]*"
    r"(?:\r?\n[ \t]*)?"
    r"("
    r"[A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’-]+"
    r"(?:[ \t]+[A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’-]+){1,5}"
    r")"
    r"[ \t]*$"
)

PII_LABELS = {
    "person_name": "Nombre completo",
    "dni": "DNI",
    "ruc": "RUC",
    "email": "Correo electrónico",
    "phone": "Teléfono",
    "bank_account": "Cuenta bancaria",
}


def _normalize_amount(raw_value: str) -> Optional[float]:
    try:
        return float(raw_value.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _unique_preserving_order(values: List[Any]) -> List[Any]:
    seen = set()
    result = []

    for value in values:
        key = str(value)

        if key in seen:
            continue

        seen.add(key)
        result.append(value)

    return result
def _mask_person_name(value: str) -> str:
    """
    Enmascara nombres conservando únicamente los dos primeros
    caracteres de cada componente.
    """

    masked_parts = []

    for part in value.split():
        if len(part) <= 2:
            masked_parts.append(
                part[0] + "*" * (len(part) - 1)
            )
        else:
            masked_parts.append(
                part[:2] + "*" * (len(part) - 2)
            )

    return " ".join(masked_parts)


def _extract_labeled_person_names(
    text: str,
) -> List[Dict[str, Any]]:
    """
    Detecta nombres únicamente cuando aparecen asociados a una
    etiqueta documental explícita.

    Ejemplo:
        Nombre completo:
        Albano Llopis Hierro

    Se limita deliberadamente a campos etiquetados para evitar
    clasificar palabras arbitrarias como nombres personales.
    """

    entities = []

    for match in LABELED_PERSON_NAME_PATTERN.finditer(text or ""):
        value = match.group(1).strip()
        start, end = match.span(1)

        entities.append(
            {
                "type": "person_name",
                "value": value,
                "masked_value": _mask_person_name(value),
                "start": start,
                "end": end,
            }
        )

    return entities


def _build_contextual_pii_entities(
    text: str,
    pii_entities: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Combina la PII regex histórica con campos personales
    detectados únicamente para la capa productiva/contextual.
    """

    combined = list(pii_entities or [])

    combined.extend(
        _extract_labeled_person_names(text)
    )

    unique = []
    seen = set()

    for entity in combined:
        key = (
            entity.get("type"),
            entity.get("start"),
            entity.get("end"),
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(entity)

    return unique

def _safe_masked_pii(
    pii_entities: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Genera la representación de PII que puede enviarse al frontend.

    Deliberadamente NO expone el campo raw 'value'.
    """

    safe_entities = []

    for entity in pii_entities or []:
        pii_type = entity.get("type", "unknown")
        masked_value = entity.get("masked_value")

        if not masked_value:
            continue

        safe_entities.append(
            {
                "type": pii_type,
                "label": PII_LABELS.get(
                    pii_type,
                    pii_type.replace("_", " ").title(),
                ),
                "masked_value": masked_value,
            }
        )

    return safe_entities


def _extract_document_type(text: str) -> Optional[str]:
    match = DOCUMENT_TYPE_PATTERN.search(text or "")

    if not match:
        return None

    return match.group(1).strip()


def _extract_amounts(text: str) -> List[Dict[str, Any]]:
    amounts = []

    for match in AMOUNT_PATTERN.finditer(text or ""):
        raw_number = match.group(1)
        numeric_value = _normalize_amount(raw_number)

        amounts.append(
            {
                "currency": "PEN",
                "display_value": f"S/ {raw_number}",
                "numeric_value": numeric_value,
            }
        )

    # Evita repetir montos exactamente iguales.
    unique = []
    seen = set()

    for amount in amounts:
        key = (
            amount["currency"],
            amount["display_value"],
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(amount)

    return unique


def _extract_dates(text: str) -> List[str]:
    dates = []

    for match in DATE_PATTERN.finditer(text or ""):
        dates.append(match.group(0))

    return _unique_preserving_order(dates)


def _extract_operation_codes(text: str) -> List[str]:
    codes = [
        match.group(0).upper()
        for match in OPERATION_CODE_PATTERN.finditer(text or "")
    ]

    return _unique_preserving_order(codes)
def mask_text_for_response(
    text: str,
    pii_entities: List[Dict[str, Any]],
) -> str:
    """
    Devuelve una copia segura del texto para respuestas de API / frontend.

    Las PII detectadas se reemplazan por su versión enmascarada.
    Además, se aplica una sanitización defensiva sobre campos sensibles
    etiquetados que podrían no haber sido reconocidos por el detector
    general de PII.

    Esta función no modifica el texto utilizado internamente para
    fingerprinting, ranking ni evaluación.
    """

    if not text:
        return ""

    masked_text = text

    # ------------------------------------------------------------------
    # 1. Enmascarado de PII detectada normalmente.
    # ------------------------------------------------------------------
    entities = sorted(
        _build_contextual_pii_entities(
            text,
            pii_entities,
        ),
        key=lambda entity: entity.get("start", 0),
        reverse=True,
    )

    for entity in entities:
        start = entity.get("start")
        end = entity.get("end")
        masked_value = entity.get("masked_value")

        if (
            start is None
            or end is None
            or not masked_value
        ):
            continue

        masked_text = (
            masked_text[:start]
            + masked_value
            + masked_text[end:]
        )

    # ------------------------------------------------------------------
    # 2. Sanitización defensiva de direcciones etiquetadas.
    #
    # Cubre, por ejemplo:
    #
    # Dirección:
    # Av. Ejemplo 123, Lima
    #
    # y:
    #
    # Dirección: Av. Ejemplo 123, Lima
    #
    # Se aplica solamente sobre la copia destinada a respuesta pública.
    # ------------------------------------------------------------------

    address_multiline_pattern = re.compile(
        r"(?im)"
        r"(^[ \t]*(?:Direcci[oó]n|Domicilio)"
        r"[ \t]*:[ \t]*\r?\n)"
        r"([^\r\n]+)"
    )

    masked_text = address_multiline_pattern.sub(
        lambda match: (
            match.group(1)
            + "[DIRECCION_ENMASCARADA]"
        ),
        masked_text,
    )

    address_inline_pattern = re.compile(
        r"(?im)"
        r"(^[ \t]*(?:Direcci[oó]n|Domicilio)"
        r"[ \t]*:[ \t]*)"
        r"([^\r\n]+)$"
    )

    masked_text = address_inline_pattern.sub(
        lambda match: (
            match.group(1)
            + "[DIRECCION_ENMASCARADA]"
        ),
        masked_text,
    )

    return masked_text

def build_contextual_evidence(
    text: str,
    pii_entities: List[Dict[str, Any]],
    nlp_entities: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Construye evidencia contextual descriptiva para el analista.

    Ninguno de estos campos modifica ranking_score.
    """

    contextual_pii_entities = _build_contextual_pii_entities(
        text,
        pii_entities,
    )

    safe_pii = _safe_masked_pii(
        contextual_pii_entities
    )

    pii_types = _unique_preserving_order(
        [
            entity["type"]
            for entity in safe_pii
        ]
    )

    bank_accounts = [
        entity["masked_value"]
        for entity in safe_pii
        if entity["type"] == "bank_account"
    ]

    financial_information = {
        "document_type": _extract_document_type(text),
        "currency": (
            "PEN"
            if re.search(r"S\/\.?|\bPEN\b", text or "", re.IGNORECASE)
            else None
        ),
        "amounts": _extract_amounts(text),
        "dates": _extract_dates(text),
        "operation_codes": _extract_operation_codes(text),

        # Las cuentas bancarias son también PII:
        # se muestran únicamente enmascaradas.
        "bank_account_references": bank_accounts,

        "affects_ranking": False,
        "role": "descriptive_context",
    }

    contextual_evidence = {
        "pii": {
            "detected": safe_pii,
            "count": len(safe_pii),
            "types_detected": pii_types,
            "affects_ranking": False,
            "role": "identity_context",
        },

        "financial_information": financial_information,

        "general_entities": {
            "detected": nlp_entities or [],
            "count": len(nlp_entities or []),
            "affects_ranking": False,
            "role": "descriptive_context",
        },

        "ranking_relationship": {
            "affects_ranking": False,
            "statement": (
                "La evidencia contextual se presenta como apoyo a la "
                "revisión humana y no modifica la posición de los "
                "candidatos en el ranking Top-k."
            ),
        },
    }

    return contextual_evidence