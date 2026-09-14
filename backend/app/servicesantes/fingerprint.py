import re
import unicodedata
from collections import Counter
from math import sqrt
from typing import Dict, List, Any
from app.services.semantic_encoder import build_semantic_embedding, cosine_similarity_dense


# Líneas de plantilla compartidas por TODOS los documentos (cabecera/pie del
# generador sintético y de las variantes). En coseno léxico inflan la similitud
# entre documentos no relacionados -> suben FPR y bajan discriminación. Se
# eliminan ANTES de construir cualquier representación de texto, de forma
# simétrica en índice y query (incluye el código de documento, que además es
# un identity-leak). Hallazgo #4.
_BOILERPLATE_PREFIXES = (
    "c?digo de documento:",
    "codigo de documento:",
    "c?digo de documento:",
    "tipo documental:",
    "fuente simulada:",
    "transformaci?n:",
    "transformacion:",
    "transformaci?n:",
    "source:",
)

_BOILERPLATE_SUBSTRINGS = (
    "entidad financiera sint?tica",
    "entidad financiera sintetica",
    "entidad financiera sint?tica",
    "documento sint?tico generado autom?ticamente",
    "documento sintetico generado automaticamente",
    "documento sint?tico generado autom?ticamente",
    "uso exclusivo para evaluaci?n experimental",
    "uso exclusivo para evaluacion experimental",
    "uso exclusivo para evaluaci?n experimental",
    "sin validez legal",
    "documento sospechoso alterado",
)

# Identificadores internos del corpus. Deben quedar en metadata/ground truth,
# no en la rama textual de la huella.
_DOC_CODE_RE = re.compile(r"\b(?:DOC|DIST)-\d{4}\b", re.IGNORECASE)

# Marcas visuales sint?ticas: pertenecen al descriptor de layout, no al texto.
_SYN_CODE_RE = re.compile(r"\bSYN-\d{3,}\b", re.IGNORECASE)

_VISUAL_TEXT_ARTIFACTS = (
    "control documental",
    "copia sintetica",
    "copia sint?tica",
    "documento sintetico",
    "documento sint?tico",
    "validacion sintetica",
    "validaci?n sint?tica",
    "validacion sint?tica",
    "validado",
    "no valido",
    "no v?lido",
    "firma autorizada simulada",
    "banco sintetico",
    "banco sint?tico",
    "synbank",
    "bs operaciones documentarias",
    "corpus financiero sintetico",
    "corpus financiero sint?tico",
    "documento financiero sintetico",
    "documento financiero sint?tico",
    "entidad financiera sint?tica - per?",
    "entidad financiera sintetica - peru",
    "entidad financiera sint?tica - per?",
    "control visual sintetico",
    "control visual sint?tico",
    "uso exclusivo para evaluaci?n experimental",
    "uso exclusivo para evaluacion experimental",
    "uso exclusivo para evaluaci?n experimental",
    "uso: investigacion sintetica",
    "uso: investigaci?n sint?tica",
    "uso: investigacion sint?tica",
)

def _normalize_ascii(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.lower()


def _remove_visual_text_artifacts(line: str) -> str:
    cleaned = _SYN_CODE_RE.sub(" ", line)

    # Etiqueta visual gen?rica. No se usa para el matching textual.
    cleaned = re.sub(
        r"\b(?:codigo|c.digo)\s*:\s*",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )

    # Artefactos visuales/sint?ticos que deben pertenecer a layout, no a texto.
    # Se usa "." en posiciones cr?ticas para tolerar tildes o encoding irregular.
    direct_patterns = [
        r"BANCO\s+SINT.TICO",
        r"SYNBANK",
        r"BS\s+OPERACIONES\s+DOCUMENTARIAS",
        r"CONTROL\s+VISUAL\s+SINT.TICO",
        r"DOCUMENTO\s+FINANCIERO\s+SINT.TICO",
        r"DOCUMENTO\s+SINT.TICO",
        r"COPIA\s+SINT.TICA",
        r"VALIDACI.N\s+SINT.TICA",
        r"CONTROL\s+DOCUMENTAL",
        r"VALIDADO",
        r"NO\s+V.LIDO",
        r"FIRMA\s+AUTORIZADA\s+SIMULADA",
        r"USO\s+EXCLUSIVO\s+PARA\s+EVALUACI.N\s+EXPERIMENTAL",
        r"ENTIDAD\s+FINANCIERA\s+SINT.TICA\s*-\s*PER.",
        r"CORPUS\s+FINANCIERO\s+SINT.TICO",
        r"USO\s+INVESTIGACI.N\s+SINT.TICA",
        r"USO\s*:?\s*INVESTIGACI.N",
        r"\bBANCO\b",
        r"\bSINT.TICO\b",
        r"\bSINT.TICA\b",
    ]

    for pattern in direct_patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)

    return " ".join(cleaned.split())

def strip_boilerplate(text: str) -> str:
    kept = []
    for line in text.splitlines():
        raw_line = line.strip()
        norm = raw_line.lower()

        if not norm:
            continue

        if any(norm.startswith(p) for p in _BOILERPLATE_PREFIXES):
            continue

        if any(s in norm for s in _BOILERPLATE_SUBSTRINGS):
            continue

        if _DOC_CODE_RE.search(raw_line):
            continue

        cleaned_line = _remove_visual_text_artifacts(raw_line)

        if cleaned_line:
            kept.append(cleaned_line)

    return "\n".join(kept)

def normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def tokenize(text: str) -> List[str]:
    cleaned = normalize_text(text)
    tokens = []

    for token in cleaned.split():
        token = token.strip(".,;:()[]{}¡!¿?\"'")
        if len(token) >= 3:
            tokens.append(token)

    return tokens


def build_text_vector(text: str) -> Dict[str, float]:
    tokens = tokenize(text)
    counts = Counter(tokens)
    total = sum(counts.values()) or 1

    return {token: count / total for token, count in counts.items()}


def cosine_similarity(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    if not vec_a or not vec_b:
        return 0.0

    common_keys = set(vec_a.keys()) & set(vec_b.keys())
    dot_product = sum(vec_a[key] * vec_b[key] for key in common_keys)

    norm_a = sqrt(sum(value * value for value in vec_a.values()))
    norm_b = sqrt(sum(value * value for value in vec_b.values()))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def build_layout_features(text: str, layout_blocks: List[Dict[str, Any]] | None = None) -> Dict[str, float]:
    if layout_blocks:
        total_blocks = len(layout_blocks)
        total_area = sum(block.get("area", 0.0) for block in layout_blocks)
        avg_area = total_area / total_blocks if total_blocks else 0.0

        digit_blocks = sum(1 for block in layout_blocks if block.get("has_digits"))
        colon_blocks = sum(1 for block in layout_blocks if block.get("has_colon"))

        top_blocks = sum(1 for block in layout_blocks if block.get("y0", 0.0) < 0.33)
        middle_blocks = sum(
            1 for block in layout_blocks
            if 0.33 <= block.get("y0", 0.0) < 0.66
        )
        bottom_blocks = sum(1 for block in layout_blocks if block.get("y0", 0.0) >= 0.66)

        left_blocks = sum(1 for block in layout_blocks if block.get("x0", 0.0) < 0.33)
        center_blocks = sum(
            1 for block in layout_blocks
            if 0.33 <= block.get("x0", 0.0) < 0.66
        )
        right_blocks = sum(1 for block in layout_blocks if block.get("x0", 0.0) >= 0.66)

        wide_blocks = sum(1 for block in layout_blocks if block.get("width", 0.0) > 0.60)
        tall_blocks = sum(1 for block in layout_blocks if block.get("height", 0.0) > 0.08)

        avg_x0 = sum(block.get("x0", 0.0) for block in layout_blocks) / total_blocks
        avg_y0 = sum(block.get("y0", 0.0) for block in layout_blocks) / total_blocks
        avg_width = sum(block.get("width", 0.0) for block in layout_blocks) / total_blocks
        avg_height = sum(block.get("height", 0.0) for block in layout_blocks) / total_blocks
        avg_text_length = (
            sum(block.get("text_length", 0.0) for block in layout_blocks) / total_blocks
        )

        return {
            "block_count": float(total_blocks),
            "total_area": float(total_area),
            "avg_area": float(avg_area),
            "digit_block_ratio": digit_blocks / total_blocks,
            "colon_block_ratio": colon_blocks / total_blocks,
            "top_block_ratio": top_blocks / total_blocks,
            "middle_block_ratio": middle_blocks / total_blocks,
            "bottom_block_ratio": bottom_blocks / total_blocks,
            "left_block_ratio": left_blocks / total_blocks,
            "center_block_ratio": center_blocks / total_blocks,
            "right_block_ratio": right_blocks / total_blocks,
            "wide_block_ratio": wide_blocks / total_blocks,
            "tall_block_ratio": tall_blocks / total_blocks,
            "avg_x0": float(avg_x0),
            "avg_y0": float(avg_y0),
            "avg_width": float(avg_width),
            "avg_height": float(avg_height),
            "avg_text_length": float(avg_text_length),
        }

    # Fallback para DOCX u otros formatos sin coordenadas.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    total_lines = len(lines)
    total_chars = len(text)

    colon_lines = sum(1 for line in lines if ":" in line)
    numeric_lines = sum(1 for line in lines if any(char.isdigit() for char in line))
    long_lines = sum(1 for line in lines if len(line) > 60)

    avg_line_length = total_chars / total_lines if total_lines else 0

    return {
        "total_lines": float(total_lines),
        "total_chars": float(total_chars),
        "colon_lines": float(colon_lines),
        "numeric_lines": float(numeric_lines),
        "long_lines": float(long_lines),
        "avg_line_length": float(avg_line_length),
    }


def normalize_feature_vector(features: Dict[str, float]) -> Dict[str, float]:
    norm = sqrt(sum(value * value for value in features.values()))

    if norm == 0:
        return features

    return {key: value / norm for key, value in features.items()}


def build_pii_features(pii_entities: List[Dict[str, Any]]) -> Dict[str, float]:
    features = {}

    # Rasgos por cantidad de tipo de PII
    counts = Counter(entity["type"] for entity in pii_entities)

    for pii_type in ["dni", "ruc", "email", "phone", "bank_account"]:
        features[f"count:{pii_type}"] = float(counts.get(pii_type, 0))

    # Rasgos por valor específico detectado
    # Esto ayuda a distinguir documentos que tienen la misma estructura,
    # pero diferentes DNI, RUC, emails o cuentas.
    for entity in pii_entities:
        pii_type = entity.get("type", "").lower()
        value = str(entity.get("value", "")).lower().strip()

        if pii_type and value:
            features[f"value:{pii_type}:{value}"] = 1.0

    return features


def build_fingerprint(
    text: str,
    pii_entities: List[Dict[str, Any]],
    layout_blocks: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    # Limpieza de boilerplate ANTES de ambas representaciones de texto (léxica
    # y semántica), simétrica en índice y query. Hallazgo #4.
    clean_text = strip_boilerplate(text)

    text_vector = build_text_vector(clean_text)
    semantic_text_vector = build_semantic_embedding(clean_text)
    layout_features = normalize_feature_vector(
        build_layout_features(text, layout_blocks)
    )
    pii_features = normalize_feature_vector(build_pii_features(pii_entities))
    return {
        "text_vector": text_vector,
        "layout_features": layout_features,
        "pii_features": pii_features,
        "semantic_text_vector": semantic_text_vector,
        "summary": {
            "text_tokens": len(text_vector),
            "layout_feature_count": len(layout_features),
            "layout_block_count": len(layout_blocks) if layout_blocks else 0,
            "semantic_embedding_dimensions": len(semantic_text_vector),
            "pii_feature_count": len(pii_features),
        },
    }


def compare_fingerprints(
    query_fp: Dict[str, Any],
    candidate_fp: Dict[str, Any],
    w_text: float = 0.35,
    w_layout: float = 0.20,
    w_pii: float = 0.45,
    use_semantic_text: bool = False,
    use_hybrid_text: bool = False,
    hybrid_lexical_weight: float = 0.70,
    hybrid_semantic_weight: float = 0.30,
) -> Dict[str, float]:
    text_score = cosine_similarity(
        query_fp["text_vector"],
        candidate_fp["text_vector"],
    )

    semantic_text_score = cosine_similarity_dense(
        query_fp.get("semantic_text_vector", []),
        candidate_fp.get("semantic_text_vector", []),
    )

    layout_score = cosine_similarity(
        query_fp["layout_features"],
        candidate_fp["layout_features"],
    )

    pii_score = cosine_similarity(
        query_fp["pii_features"],
        candidate_fp["pii_features"],
    )

    hybrid_text_score = (
        hybrid_lexical_weight * text_score
        + hybrid_semantic_weight * semantic_text_score
    )

    if use_hybrid_text:
        selected_text_score = hybrid_text_score
    elif use_semantic_text:
        selected_text_score = semantic_text_score
    else:
        selected_text_score = text_score

    final_score = (
        w_text * selected_text_score
        + w_layout * layout_score
        + w_pii * pii_score
    )

    return {
        "final_score": round(final_score, 4),
        "text_score": round(text_score, 4),
        "semantic_text_score": round(semantic_text_score, 4),
        "hybrid_text_score": round(hybrid_text_score, 4),
        "selected_text_score": round(selected_text_score, 4),
        "layout_score": round(layout_score, 4),
        "pii_score": round(pii_score, 4),
    }


# === FORENSIQ_VISUAL_LAYOUT_FEATURES_PATCH ===
# Layout descriptor enriched with text block geometry and visual graphic density.

def build_layout_features(text: str, layout_blocks: List[Dict[str, Any]] | None = None) -> Dict[str, float]:
    if layout_blocks:
        total_blocks = len(layout_blocks)
        text_blocks = [b for b in layout_blocks if b.get("block_type", "text") == "text"]
        graphic_blocks = [b for b in layout_blocks if b.get("block_type") == "graphic"]
        image_blocks = [b for b in layout_blocks if b.get("block_type") == "image"]
        visual_blocks = graphic_blocks + image_blocks

        total_area = sum(block.get("area", 0.0) for block in layout_blocks)
        avg_area = total_area / total_blocks if total_blocks else 0.0

        base_blocks = text_blocks if text_blocks else layout_blocks
        base_count = len(base_blocks) if base_blocks else 1

        digit_blocks = sum(1 for block in base_blocks if block.get("has_digits"))
        colon_blocks = sum(1 for block in base_blocks if block.get("has_colon"))

        top_blocks = sum(1 for block in base_blocks if block.get("y0", 0.0) < 0.33)
        middle_blocks = sum(1 for block in base_blocks if 0.33 <= block.get("y0", 0.0) < 0.66)
        bottom_blocks = sum(1 for block in base_blocks if block.get("y0", 0.0) >= 0.66)

        left_blocks = sum(1 for block in base_blocks if block.get("x0", 0.0) < 0.33)
        center_blocks = sum(1 for block in base_blocks if 0.33 <= block.get("x0", 0.0) < 0.66)
        right_blocks = sum(1 for block in base_blocks if block.get("x0", 0.0) >= 0.66)

        wide_blocks = sum(1 for block in base_blocks if block.get("width", 0.0) > 0.60)
        tall_blocks = sum(1 for block in base_blocks if block.get("height", 0.0) > 0.08)

        avg_x0 = sum(block.get("x0", 0.0) for block in base_blocks) / base_count
        avg_y0 = sum(block.get("y0", 0.0) for block in base_blocks) / base_count
        avg_width = sum(block.get("width", 0.0) for block in base_blocks) / base_count
        avg_height = sum(block.get("height", 0.0) for block in base_blocks) / base_count
        avg_text_length = sum(block.get("text_length", 0.0) for block in base_blocks) / base_count

        visual_count = len(visual_blocks)
        graphic_count = len(graphic_blocks)
        image_count = len(image_blocks)
        visual_area = sum(block.get("area", 0.0) for block in visual_blocks)
        avg_visual_area = visual_area / visual_count if visual_count else 0.0

        filled_visual = sum(1 for block in visual_blocks if block.get("has_fill"))
        visual_items = sum(float(block.get("drawing_items", 0.0)) for block in visual_blocks)
        visual_stroke = sum(float(block.get("stroke_width", 0.0)) for block in visual_blocks)

        visual_top = sum(1 for block in visual_blocks if block.get("y0", 0.0) < 0.33)
        visual_middle = sum(1 for block in visual_blocks if 0.33 <= block.get("y0", 0.0) < 0.66)
        visual_bottom = sum(1 for block in visual_blocks if block.get("y0", 0.0) >= 0.66)

        visual_left = sum(1 for block in visual_blocks if block.get("x0", 0.0) < 0.33)
        visual_center = sum(1 for block in visual_blocks if 0.33 <= block.get("x0", 0.0) < 0.66)
        visual_right = sum(1 for block in visual_blocks if block.get("x0", 0.0) >= 0.66)

        features = {
            "block_count": float(total_blocks),
            "text_block_count": float(len(text_blocks)),
            "graphic_block_count": float(graphic_count),
            "image_block_count": float(image_count),
            "visual_block_count": float(visual_count),
            "total_area": float(total_area),
            "avg_area": float(avg_area),

            "digit_block_ratio": digit_blocks / base_count,
            "colon_block_ratio": colon_blocks / base_count,
            "top_block_ratio": top_blocks / base_count,
            "middle_block_ratio": middle_blocks / base_count,
            "bottom_block_ratio": bottom_blocks / base_count,
            "left_block_ratio": left_blocks / base_count,
            "center_block_ratio": center_blocks / base_count,
            "right_block_ratio": right_blocks / base_count,
            "wide_block_ratio": wide_blocks / base_count,
            "tall_block_ratio": tall_blocks / base_count,

            "avg_x0": float(avg_x0),
            "avg_y0": float(avg_y0),
            "avg_width": float(avg_width),
            "avg_height": float(avg_height),
            "avg_text_length": float(avg_text_length),

            "visual_area": float(visual_area),
            "avg_visual_area": float(avg_visual_area),
            "visual_to_text_ratio": float(visual_count / max(len(text_blocks), 1)),
            "filled_visual_ratio": float(filled_visual / visual_count) if visual_count else 0.0,
            "visual_items_total": float(visual_items),
            "visual_stroke_total": float(visual_stroke),

            "visual_top_ratio": visual_top / visual_count if visual_count else 0.0,
            "visual_middle_ratio": visual_middle / visual_count if visual_count else 0.0,
            "visual_bottom_ratio": visual_bottom / visual_count if visual_count else 0.0,
            "visual_left_ratio": visual_left / visual_count if visual_count else 0.0,
            "visual_center_ratio": visual_center / visual_count if visual_count else 0.0,
            "visual_right_ratio": visual_right / visual_count if visual_count else 0.0,
        }

        # 3x3 visual density grid. Useful for pseudo-QR, stamp, signature and watermark regions.
        for row in range(3):
            for col in range(3):
                count = 0
                for block in visual_blocks:
                    x = block.get("x0", 0.0)
                    y = block.get("y0", 0.0)
                    if row / 3 <= y < (row + 1) / 3 and col / 3 <= x < (col + 1) / 3:
                        count += 1
                features[f"visual_grid_{row}_{col}"] = count / visual_count if visual_count else 0.0

        return features

    # Fallback for DOCX or formats without coordinates.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    total_lines = len(lines)
    total_chars = len(text)

    colon_lines = sum(1 for line in lines if ":" in line)
    numeric_lines = sum(1 for line in lines if any(char.isdigit() for char in line))
    long_lines = sum(1 for line in lines if len(line) > 60)

    avg_line_length = total_chars / total_lines if total_lines else 0

    return {
        "total_lines": float(total_lines),
        "total_chars": float(total_chars),
        "colon_lines": float(colon_lines),
        "numeric_lines": float(numeric_lines),
        "long_lines": float(long_lines),
        "avg_line_length": float(avg_line_length),
    }

