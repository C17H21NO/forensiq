import re
from collections import defaultdict


PII_PATTERNS = {
    "dni": r"\b\d{8}\b",
    "ruc": r"\b10\d{9}\b|\b20\d{9}\b",
    "email": r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b",
    "phone": r"\b9\d{8}\b",
    "bank_account": r"\b\d{3}-\d{12}-\d{2}\b",
}


def mask_value(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)

    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def detect_pii(text: str) -> dict:
    results = defaultdict(list)

    for pii_type, pattern in PII_PATTERNS.items():
        matches = re.findall(pattern, text)

        for match in matches:
            if match not in results[pii_type]:
                results[pii_type].append(match)

    return dict(results)


def detect_pii_masked(text: str) -> list[dict]:
    entities = []

    for pii_type, pattern in PII_PATTERNS.items():
        for match in re.finditer(pattern, text):
            value = match.group(0)
            entities.append({
                "type": pii_type,
                "value": value,
                "masked_value": mask_value(value),
                "start": match.start(),
                "end": match.end(),
            })

    return entities