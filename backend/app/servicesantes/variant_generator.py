# =============================================================================
# variant_generator.py  ·  versión data-driven (preserva layout)
# -----------------------------------------------------------------------------
# CAMBIO DE FONDO (decisión D1 = opción A):
#   La versión anterior renderizaba TODA variante a un PDF plano genérico
#   ("Documento sospechoso alterado"), de modo que el layout de cualquier
#   variante era idéntico entre sí e independiente del legítimo padre. Eso
#   invalidaba la rama de layout (layout_only ~ azar) y hacía la ablación de
#   layout un artefacto del harness, no del método.
#
#   Ahora las transformaciones operan sobre los DATOS ESTRUCTURADOS del legítimo
#   (cargados desde el sidecar .meta.json) y la variante se RE-RENDERIZA con el
#   MISMO renderer del tipo documental. La variante hereda el `doc_seed` del
#   padre, así que difiere de él SOLO en los campos transformados: el layout
#   pertenece a la misma familia visual y vuelve a ser discriminativo.
#
# TRAZABILIDAD AL THREAT MODEL (protocolo §2 / matriz §5.2):
#   format_change -> T1 | binary_recode -> T2 | whitespace -> T3
#   ocr_reocr -> T4    | case_punct -> T5    | drop_fields -> T6
#   reorder_blocks -> T7 (reordenamiento fiel vía modelo declarativo de bloques
#                         en synthetic_generator: reordena grupos sección+contenido
#                         preservando estilo, cambiando orden y posiciones)
#   mask_pii -> T8 (anonimización parcial)   | combined -> 2-3 combinadas
#
#   paraphrase_full queda FUERA del threat model (nivel 3, §2.2). Se conserva
#   como stress-test reportable aparte, NO en la matriz principal T1-T8.
# =============================================================================

import io
import random
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import fitz
import pytesseract
from PIL import Image, ImageFilter, ImageOps

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

try:
    from docx import Document as DocxDocument
    _DOCX_AVAILABLE = True
except Exception:  # python-docx ausente
    _DOCX_AVAILABLE = False

from app.services.extractor import extract_text
from app.services.synthetic_generator import (
    render_document_from_data,
    load_document_metadata,
)

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "synthetic_data" / "suspicious"

# Transformaciones DENTRO del threat model declarado (matriz principal §5.2).
# T7 (reorder_blocks) omitida a propósito (ver cabecera).
TRANSFORMATION_TYPES = [
    "format_change",   # T1
    "binary_recode",   # T2
    "whitespace",      # T3
    "ocr_reocr",       # T4
    "case_punct",      # T5
    "drop_fields",     # T6
    "reorder_blocks",  # T7
    "mask_pii",        # T8
    "combined",        # 2-3 combinadas
]

# Mapeo explícito para construir la matriz transformación x métrica de forma
# trazable al protocolo (resuelve la divergencia de nombres con §5.2).
PROTOCOL_TRANSFORMATION_MAP = {
    "format_change": "T1",
    "binary_recode": "T2",
    "whitespace": "T3",
    "ocr_reocr": "T4",
    "case_punct": "T5",
    "drop_fields": "T6",
    "reorder_blocks": "T7",
    "mask_pii": "T8",
    "combined": "combinadas",
}

# Transformaciones FUERA del threat model (nivel 3). Reportar por separado.
BEYOND_THREAT_MODEL = ["paraphrase_full"]

# Campos del registro estructurado que son PII (para enmascarado/eliminación).
PII_FIELDS = ["name", "dni", "ruc", "phone", "account", "email", "address", "operation_code"]

# Orden y etiquetas para el render DOCX (T1 cambio de formato).
FIELD_LABELS = [
    ("name", "Nombre completo"),
    ("dni", "DNI"),
    ("ruc", "RUC asociado"),
    ("email", "Correo electrónico"),
    ("phone", "Teléfono"),
    ("account", "Cuenta bancaria"),
    ("address", "Dirección"),
    ("occupation", "Ocupación"),
    ("amount", "Monto referencial"),
    ("date", "Fecha de emisión"),
    ("risk_level", "Nivel de riesgo"),
    ("operation_code", "Código de operación"),
]


# --------------------------------------------------------------------------- #
# Helpers de transformación a nivel de campo
# --------------------------------------------------------------------------- #
def _mask_digits(value: str) -> str:
    value = str(value)
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]



def _mask_name(value: str) -> str:
    parts = [p for p in str(value).replace("-", " ").split() if p]
    if not parts:
        return "[NOMBRE_ENMASCARADO]"
    initials = " ".join((p[0].upper() + ".") for p in parts[:4])
    return "CLIENTE ENMASCARADO"

def _ocr_substitute(value: str) -> str:
    replacements = {"a": "@", "e": "3", "i": "1", "o": "0", "s": "5", "B": "8"}
    chars = list(str(value))
    for index, char in enumerate(chars):
        if char in replacements and index % 12 == 0:
            chars[index] = replacements[char]
    return "".join(chars)


def t_mask_pii(data: dict) -> dict:
    """T8 reforzado: anonimizaci?n parcial de PII y se?ales personales.
    Reduce valores que text_only/text+PII podr?an usar como atajo, manteniendo
    etiquetas y estructura documental para que texto residual/layout a?n aporten.
    """
    if data.get("name"):
        data["name"] = _mask_name(data["name"])

    for key in ["dni", "ruc", "phone"]:
        if data.get(key):
            data[key] = _mask_digits(data[key])

    if data.get("account"):
        data["account"] = "[CUENTA_ENMASCARADA]"

    if data.get("email"):
        data["email"] = "[EMAIL_ENMASCARADO]"

    if data.get("address"):
        data["address"] = "[DIRECCION_ENMASCARADA]"

    if data.get("operation_code"):
        data["operation_code"] = "OP-******"

    return data

def t_drop_fields(data: dict) -> dict:
    """T6 reforzado: eliminaci?n parcial de campos sin proteger siempre el nombre.
    Evita que una se?al textual ?nica quede viva en todos los casos.
    """
    candidates = [k for k, v in data.items() if isinstance(v, str) and v != ""]
    if not candidates:
        return data

    drop_count = max(1, int(len(candidates) * 0.50))
    drop_count = min(drop_count, max(1, len(candidates) - 2))

    for key in random.sample(candidates, drop_count):
        data[key] = ""

    return data

def t_case_punct(data: dict) -> dict:
    """T5: conversión de mayúsculas/puntuación preservando significado."""
    for key, value in data.items():
        if isinstance(value, str) and value:
            value = value.upper() if random.random() < 0.5 else value.lower()
            value = value.replace(",", "").replace(".", "")
            data[key] = value
    return data


def t_whitespace(data: dict) -> dict:
    """T3: cambios cosméticos de espacios."""
    for key, value in data.items():
        if isinstance(value, str) and value:
            data[key] = value.replace(" ", "  ")
    return data


def t_ocr_noise(data: dict) -> dict:
    """Ruido de caracter tipo OCR aplicado a nivel de campo (subconjunto de T4
    sin rasterizar; el T4 'real' usa la ruta ocr_reocr)."""
    for key, value in data.items():
        if isinstance(value, str) and value:
            data[key] = _ocr_substitute(value)
    return data


def t_combined(data: dict) -> dict:
    """2-3 transformaciones combinadas (escenario realista adversario nivel 2)."""
    data = t_mask_pii(data)
    data = t_drop_fields(data)
    data = t_case_punct(data)
    return data


DATA_TRANSFORMS = {
    "whitespace": t_whitespace,
    "case_punct": t_case_punct,
    "drop_fields": t_drop_fields,
    "mask_pii": t_mask_pii,
    "ocr_noise": t_ocr_noise,
    "combined": t_combined,
}


# --------------------------------------------------------------------------- #
# Renderers auxiliares (DOCX para T1, texto plano para OCR/paráfrasis)
# --------------------------------------------------------------------------- #
def render_docx_from_data(data: dict, document_type: str, output_path: str) -> None:
    if not _DOCX_AVAILABLE:
        raise RuntimeError("python-docx no disponible: no se puede generar T1 (DOCX).")
    doc = DocxDocument()
    doc.add_heading(document_type.replace("_", " ").title(), level=1)
    for key, label in FIELD_LABELS:
        value = data.get(key, "")
        if value != "":
            doc.add_paragraph(f"{label}: {value}")
    doc.save(output_path)


def _render_plain_text_pdf(text: str, output_path: str) -> None:
    """Render plano SIN cabecera identificatoria. Solo para OCR/paráfrasis,
    donde el layout legítimamente se degrada."""
    c = canvas.Canvas(str(output_path), pagesize=A4)
    _, height = A4
    c.setFont("Helvetica", 10)
    y = height - 60
    for line in text.splitlines():
        if y < 60:
            c.showPage()
            c.setFont("Helvetica", 10)
            y = height - 60
        for chunk in ([line[i:i + 95] for i in range(0, len(line), 95)] or [""]):
            c.drawString(60, y, chunk)
            y -= 14
    c.save()


def _variant_filename(transformation_type: str, original_filename: str, ext: str) -> str:
    return (
        f"VARIANT_{transformation_type}_"
        f"{Path(original_filename).stem}_{uuid4().hex[:8]}{ext}"
    )


# --------------------------------------------------------------------------- #
# Ruta OCR-reOCR (T4): rasteriza el ORIGINAL estructurado, escanea, re-OCR
# --------------------------------------------------------------------------- #
def render_pdf_first_page_to_image(file_path: str, zoom: float = 2.0) -> Image.Image:
    with fitz.open(file_path) as pdf:
        page = pdf[0]
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
    return image


def apply_light_scan_noise(image: Image.Image) -> Image.Image:
    processed = ImageOps.grayscale(image)
    processed = processed.filter(ImageFilter.GaussianBlur(radius=0.35))
    processed = ImageOps.autocontrast(processed)
    return processed.convert("RGB")


def generate_ocr_reocr_variant(file_path: str) -> dict:
    original_path = Path(file_path)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    ocr_failed = False
    ocr_error = None
    try:
        image = render_pdf_first_page_to_image(str(original_path), zoom=2.0)
        noisy = apply_light_scan_noise(image)
        try:
            ocr_text = pytesseract.image_to_string(noisy, lang="spa+eng").strip()
        except Exception:
            ocr_text = pytesseract.image_to_string(noisy).strip()
    except Exception as exc:
        # tesseract ausente / fallo de render: se reporta explícitamente en
        # lugar de desaparecer la fila en silencio (hallazgo #9).
        ocr_text = ""
        ocr_failed = True
        ocr_error = str(exc)

    if not ocr_text:
        ocr_text = "Texto no reconocido mediante OCR. Documento reprocesado para evaluacion."

    variant_filename = _variant_filename("ocr_reocr", original_path.name, ".pdf")
    variant_path = OUTPUT_DIR / variant_filename
    _render_plain_text_pdf(ocr_text, str(variant_path))

    result = {
        "original_filename": original_path.name,
        "original_path": str(original_path),
        "variant_filename": variant_filename,
        "variant_path": str(variant_path),
        "transformation_type": "ocr_reocr",
        "layout_preserved": False,  # un escaneo degrada el layout (realista)
        "altered_text_preview": ocr_text[:800],
    }
    if ocr_failed:
        result["ocr_failed"] = True
        result["ocr_error"] = ocr_error
    return result


# --------------------------------------------------------------------------- #
# Paráfrasis (FUERA del threat model, nivel 3) - reportar aparte
# --------------------------------------------------------------------------- #
def generate_paraphrase_variant(file_path: str) -> dict:
    original_path = Path(file_path)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    text = extract_text(str(original_path))
    replacements = {
        "Nombre completo:": "Titular:",
        "DNI:": "Documento de identidad:",
        "RUC asociado:": "Registro tributario:",
        "Correo electrónico:": "Contacto digital:",
        "Teléfono:": "Número de contacto:",
        "Cuenta bancaria:": "Producto financiero:",
        "Monto referencial:": "Importe registrado:",
        "Fecha de emisión:": "Fecha de registro:",
        "Nivel de riesgo:": "Clasificación interna:",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    variant_filename = _variant_filename("paraphrase_full", original_path.name, ".pdf")
    variant_path = OUTPUT_DIR / variant_filename
    _render_plain_text_pdf(text, str(variant_path))

    return {
        "original_filename": original_path.name,
        "original_path": str(original_path),
        "variant_filename": variant_filename,
        "variant_path": str(variant_path),
        "transformation_type": "paraphrase_full",
        "layout_preserved": False,
        "beyond_threat_model": True,
    }


# --------------------------------------------------------------------------- #
# Fallback legacy (metadata ausente): mantiene compatibilidad, marca el déficit
# --------------------------------------------------------------------------- #
def _generate_variant_legacy_flat(file_path: str, transformation_type: str) -> dict:
    original_path = Path(file_path)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    text = extract_text(str(original_path))
    variant_filename = _variant_filename(transformation_type, original_path.name, ".pdf")
    variant_path = OUTPUT_DIR / variant_filename
    _render_plain_text_pdf(text, str(variant_path))
    return {
        "original_filename": original_path.name,
        "original_path": str(original_path),
        "variant_filename": variant_filename,
        "variant_path": str(variant_path),
        "transformation_type": transformation_type,
        "layout_preserved": False,
        "metadata_missing": True,  # el layout de esta variante NO es comparable
    }


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def generate_variant_from_pdf(
    file_path: str,
    transformation_type: str = "combined",
    seed: int | None = None,
) -> dict:
    if transformation_type == "ocr_reocr":
        return generate_ocr_reocr_variant(file_path)

    if transformation_type == "paraphrase_full":
        return generate_paraphrase_variant(file_path)

    metadata = load_document_metadata(file_path)
    if metadata is None:
        # PDF sin sidecar (corpus viejo): no hay datos estructurados para
        # re-renderizar con el template original -> el layout no es comparable.
        return _generate_variant_legacy_flat(file_path, transformation_type)

    if seed is not None:
        random.seed(seed)

    data = deepcopy(metadata["data"])
    document_type = metadata["document_type"]
    doc_seed = metadata.get("doc_seed")
    original_path = Path(file_path)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # doc_code neutralizado: la variante NO debe nombrar a su padre (anti-leak).
    neutral_code = ""

    if transformation_type == "format_change":  # T1
        variant_filename = _variant_filename(transformation_type, original_path.name, ".docx")
        variant_path = OUTPUT_DIR / variant_filename
        render_docx_from_data(data, document_type, str(variant_path))
        layout_preserved = False  # cambia de formato; texto/PII intactos

    elif transformation_type == "binary_recode":  # T2
        # Mismo contenido y layout, distintos bytes (nuevo archivo) -> rompe
        # SHA-256, trivial para fingerprint/TLSH.
        variant_filename = _variant_filename(transformation_type, original_path.name, ".pdf")
        variant_path = OUTPUT_DIR / variant_filename
        render_document_from_data(data, document_type, neutral_code, str(variant_path), doc_seed)
        layout_preserved = True

    elif transformation_type == "reorder_blocks":  # T7
        # Mismo contenido y estilo; se reordenan los grupos sección+contenido.
        # El layout (posiciones, histogramas verticales) cambia; texto/PII no.
        variant_filename = _variant_filename(transformation_type, original_path.name, ".pdf")
        variant_path = OUTPUT_DIR / variant_filename
        reorder_seed = random.randint(0, 2_147_483_647)
        render_document_from_data(
            data, document_type, neutral_code, str(variant_path), doc_seed,
            reorder_blocks=True, reorder_seed=reorder_seed,
        )
        layout_preserved = True  # estilo en familia; cambia el orden

    elif transformation_type in DATA_TRANSFORMS:
        data = DATA_TRANSFORMS[transformation_type](data)
        variant_filename = _variant_filename(transformation_type, original_path.name, ".pdf")
        variant_path = OUTPUT_DIR / variant_filename
        # Re-render con el MISMO renderer y doc_seed: layout en familia, solo
        # difieren los campos transformados.
        render_document_from_data(data, document_type, neutral_code, str(variant_path), doc_seed)
        layout_preserved = True

    else:
        raise ValueError(f"Tipo de transformación no soportado: {transformation_type}")

    return {
        "original_filename": original_path.name,
        "original_path": str(original_path),
        "variant_filename": variant_filename,
        "variant_path": str(variant_path),
        "transformation_type": transformation_type,
        "protocol_id": PROTOCOL_TRANSFORMATION_MAP.get(transformation_type),
        "layout_preserved": layout_preserved,
    }


# === FORENSIQ_PROTOCOL_M1_M10_PATCH ===
# Extensi?n metodol?gica: 8 transformaciones simples + 10 combinadas expl?citas.
# Mantiene compatibilidad con el paquete original del profesor.

def t_combo_format_noise(data: dict) -> dict:
    """M1: cambio de formato + ruido textual tipo OCR."""
    data = t_ocr_noise(data)
    return data

def t_combo_ocr_noise(data: dict) -> dict:
    """M2: degradaci?n OCR + puntuaci?n/case."""
    data = t_ocr_noise(data)
    data = t_case_punct(data)
    return data

def t_combo_ocr_mask(data: dict) -> dict:
    """M3: degradaci?n OCR + enmascaramiento parcial de PII."""
    data = t_ocr_noise(data)
    data = t_mask_pii(data)
    return data

def t_combo_reorder_mask(data: dict) -> dict:
    """M4: reordenamiento parcial + enmascaramiento de PII."""
    data = t_mask_pii(data)
    return data

def t_combo_noise_drop(data: dict) -> dict:
    """M5: ruido OCR + eliminaci?n parcial de campos."""
    data = t_ocr_noise(data)
    data = t_drop_fields(data)
    return data

def t_combo_reorder_noise(data: dict) -> dict:
    """M6: reordenamiento parcial + ruido OCR."""
    data = t_ocr_noise(data)
    return data

def t_combo_drop_case(data: dict) -> dict:
    """M7: eliminaci?n parcial de campos + cambios de may?sculas/puntuaci?n."""
    data = t_drop_fields(data)
    data = t_case_punct(data)
    return data

def t_combo_noise_reorder_mask(data: dict) -> dict:
    """M8: ruido OCR + reordenamiento parcial + enmascaramiento de PII."""
    data = t_ocr_noise(data)
    data = t_mask_pii(data)
    return data

def t_combo_drop_reorder_mask(data: dict) -> dict:
    """M9: eliminaci?n parcial + reordenamiento parcial + enmascaramiento de PII."""
    data = t_drop_fields(data)
    data = t_mask_pii(data)
    return data

def t_combo_strong(data: dict) -> dict:
    """M10: combinaci?n fuerte nivel 2: ruido + m?scara + eliminaci?n + case/punct."""
    data = t_ocr_noise(data)
    data = t_mask_pii(data)
    data = t_drop_fields(data)
    data["_redact_transactions"] = True
    data = t_case_punct(data)
    return data


COMBINED_RENDER_TRANSFORMS = {
    "combo_format_noise": {
        "protocol_id": "M1",
        "ops": [t_combo_format_noise],
        "reorder": False,
        "ext": ".docx",
    },
    "combo_ocr_noise": {
        "protocol_id": "M2",
        "ops": [t_combo_ocr_noise],
        "reorder": False,
        "ext": ".pdf",
    },
    "combo_ocr_mask": {
        "protocol_id": "M3",
        "ops": [t_combo_ocr_mask],
        "reorder": False,
        "ext": ".pdf",
    },
    "combo_reorder_mask": {
        "protocol_id": "M4",
        "ops": [t_combo_reorder_mask],
        "reorder": True,
        "ext": ".pdf",
    },
    "combo_noise_drop": {
        "protocol_id": "M5",
        "ops": [t_combo_noise_drop],
        "reorder": False,
        "ext": ".pdf",
    },
    "combo_reorder_noise": {
        "protocol_id": "M6",
        "ops": [t_combo_reorder_noise],
        "reorder": True,
        "ext": ".pdf",
    },
    "combo_drop_case": {
        "protocol_id": "M7",
        "ops": [t_combo_drop_case],
        "reorder": False,
        "ext": ".pdf",
    },
    "combo_noise_reorder_mask": {
        "protocol_id": "M8",
        "ops": [t_combo_noise_reorder_mask],
        "reorder": True,
        "ext": ".pdf",
    },
    "combo_drop_reorder_mask": {
        "protocol_id": "M9",
        "ops": [t_combo_drop_reorder_mask],
        "reorder": True,
        "ext": ".pdf",
    },
    "combo_strong": {
        "protocol_id": "M10",
        "ops": [t_combo_strong],
        "reorder": True,
        "ext": ".pdf",
    },
}

PROTOCOL_TRANSFORMATION_MAP.update({
    "combo_format_noise": "M1",
    "combo_ocr_noise": "M2",
    "combo_ocr_mask": "M3",
    "combo_reorder_mask": "M4",
    "combo_noise_drop": "M5",
    "combo_reorder_noise": "M6",
    "combo_drop_case": "M7",
    "combo_noise_reorder_mask": "M8",
    "combo_drop_reorder_mask": "M9",
    "combo_strong": "M10",
})


def generate_variant_from_pdf(
    file_path: str,
    transformation_type: str = "combined",
    seed: int | None = None,
) -> dict:
    if transformation_type == "ocr_reocr":
        return generate_ocr_reocr_variant(file_path)

    if transformation_type == "paraphrase_full":
        return generate_paraphrase_variant(file_path)

    metadata = load_document_metadata(file_path)
    if metadata is None:
        return _generate_variant_legacy_flat(file_path, transformation_type)

    if seed is not None:
        random.seed(seed)

    data = deepcopy(metadata["data"])
    document_type = metadata["document_type"]
    doc_seed = metadata.get("doc_seed")
    original_path = Path(file_path)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    neutral_code = ""

    if transformation_type == "format_change":
        variant_filename = _variant_filename(transformation_type, original_path.name, ".docx")
        variant_path = OUTPUT_DIR / variant_filename
        render_docx_from_data(data, document_type, str(variant_path))
        layout_preserved = False

    elif transformation_type == "binary_recode":
        variant_filename = _variant_filename(transformation_type, original_path.name, ".pdf")
        variant_path = OUTPUT_DIR / variant_filename
        render_document_from_data(data, document_type, neutral_code, str(variant_path), doc_seed)
        layout_preserved = True

    elif transformation_type == "reorder_blocks":
        variant_filename = _variant_filename(transformation_type, original_path.name, ".pdf")
        variant_path = OUTPUT_DIR / variant_filename
        reorder_seed = random.randint(0, 2_147_483_647)
        render_document_from_data(
            data,
            document_type,
            neutral_code,
            str(variant_path),
            doc_seed,
            reorder_blocks=True,
            reorder_seed=reorder_seed,
        )
        layout_preserved = True

    elif transformation_type in COMBINED_RENDER_TRANSFORMS:
        spec = COMBINED_RENDER_TRANSFORMS[transformation_type]
        for op in spec["ops"]:
            data = op(data)

        ext = spec.get("ext", ".pdf")
        variant_filename = _variant_filename(transformation_type, original_path.name, ext)
        variant_path = OUTPUT_DIR / variant_filename

        if ext == ".docx":
            render_docx_from_data(data, document_type, str(variant_path))
            layout_preserved = False
        else:
            reorder = bool(spec.get("reorder", False))
            reorder_seed = random.randint(0, 2_147_483_647) if reorder else None
            render_document_from_data(
                data,
                document_type,
                neutral_code,
                str(variant_path),
                doc_seed,
                reorder_blocks=reorder,
                reorder_seed=reorder_seed,
            )
            layout_preserved = True

    elif transformation_type in DATA_TRANSFORMS:
        data = DATA_TRANSFORMS[transformation_type](data)
        variant_filename = _variant_filename(transformation_type, original_path.name, ".pdf")
        variant_path = OUTPUT_DIR / variant_filename
        render_document_from_data(data, document_type, neutral_code, str(variant_path), doc_seed)
        layout_preserved = True

    else:
        raise ValueError(f"Tipo de transformaci?n no soportado: {transformation_type}")

    return {
        "original_filename": original_path.name,
        "original_path": str(original_path),
        "variant_filename": variant_filename,
        "variant_path": str(variant_path),
        "transformation_type": transformation_type,
        "protocol_id": PROTOCOL_TRANSFORMATION_MAP.get(transformation_type),
        "layout_preserved": layout_preserved,
    }


# === FORENSIQ_VISUAL_STRESS_VARIANTS_PATCH ===
# Visual stress variants. Text/PII are strongly degraded while the synthetic
# visual security pattern is preserved by doc_seed.

def t_visual_redacted(data: dict) -> dict:
    """V1: strong textual and PII redaction while preserving visual identity."""
    for key in list(data.keys()):
        value = data.get(key)
        if isinstance(value, str):
            if key.lower() in {"name", "cliente", "customer"}:
                data[key] = "CLIENTE REDACTADO"
            elif key.lower() in {"dni", "ruc", "phone", "account", "email"}:
                data[key] = "[PII_REDACTADA]"
            elif any(token in key.lower() for token in ["amount", "monto", "saldo", "cuota", "money"]):
                data[key] = "S/ [REDACTADO]"
            elif any(token in key.lower() for token in ["date", "fecha"]):
                data[key] = "[FECHA_REDACTADA]"
            else:
                data[key] = "[DATO_REDACTADO]"
        elif isinstance(value, (int, float)):
            data[key] = 0
    data["_redact_transactions"] = True
    return data


def t_visual_redacted_noise(data: dict) -> dict:
    """V2: OCR-like noise + strong redaction."""
    data = t_ocr_noise(data)
    data = t_visual_redacted(data)
    return data


def t_visual_redacted_drop(data: dict) -> dict:
    """V3: strong redaction + partial field deletion."""
    data = t_visual_redacted(data)
    data = t_drop_fields(data)
    return data


def t_visual_strong(data: dict) -> dict:
    """V4: strong visual stress scenario: noise + redaction + drop + case/punct."""
    data = t_ocr_noise(data)
    data = t_visual_redacted(data)
    data = t_drop_fields(data)
    data = t_case_punct(data)
    return data


VISUAL_STRESS_TRANSFORMS = {
    "visual_redacted": {
        "protocol_id": "V1",
        "ops": [t_visual_redacted],
        "reorder": False,
        "ext": ".pdf",
    },
    "visual_redacted_reorder": {
        "protocol_id": "V2",
        "ops": [t_visual_redacted],
        "reorder": True,
        "ext": ".pdf",
    },
    "visual_noise_redacted": {
        "protocol_id": "V3",
        "ops": [t_visual_redacted_noise],
        "reorder": False,
        "ext": ".pdf",
    },
    "visual_strong": {
        "protocol_id": "V4",
        "ops": [t_visual_strong],
        "reorder": True,
        "ext": ".pdf",
    },
}

COMBINED_RENDER_TRANSFORMS.update(VISUAL_STRESS_TRANSFORMS)

PROTOCOL_TRANSFORMATION_MAP.update({
    "visual_redacted": "V1",
    "visual_redacted_reorder": "V2",
    "visual_noise_redacted": "V3",
    "visual_strong": "V4",
})


# === FORENSIQ_VISUAL_V2_SCAN_VARIANTS_PATCH ===
# Image-only scan variants for OCR stress testing: low DPI, blur, JPEG compression,
# and redacted image-only PDFs.

import io as _v2_io
from PIL import Image as _v2_Image, ImageFilter as _v2_ImageFilter
from reportlab.lib.utils import ImageReader as _v2_ImageReader


def _v2_pdf_to_image(file_path: str, dpi: int = 110):
    scale = dpi / 72.0
    with fitz.open(file_path) as doc:
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        img = _v2_Image.open(_v2_io.BytesIO(pix.tobytes("png"))).convert("RGB")
    return img


def _v2_apply_scan_degradation(img, blur: float = 0.0, jpeg_quality: int = 55, resize_factor: float = 1.0):
    if resize_factor != 1.0:
        w, h = img.size
        img = img.resize((max(1, int(w * resize_factor)), max(1, int(h * resize_factor))))
        img = img.resize((w, h))

    if blur and blur > 0:
        img = img.filter(_v2_ImageFilter.GaussianBlur(radius=blur))

    buffer = _v2_io.BytesIO()
    img.save(buffer, format="JPEG", quality=jpeg_quality)
    buffer.seek(0)
    return _v2_Image.open(buffer).convert("RGB")


def _v2_image_to_pdf(img, output_path: str):
    width, height = A4
    c = canvas.Canvas(str(output_path), pagesize=A4)

    img_reader = _v2_ImageReader(img)
    c.drawImage(img_reader, 0, 0, width=width, height=height, preserveAspectRatio=False, mask="auto")
    c.save()


def _v2_render_temp_redacted_pdf(file_path: str, op_name: str, seed: int | None = None, reorder: bool = False) -> str:
    metadata = load_document_metadata(file_path)
    if metadata is None:
        return file_path

    if seed is not None:
        random.seed(seed)

    data = deepcopy(metadata["data"])
    document_type = metadata["document_type"]
    doc_seed = metadata.get("doc_seed")
    original_path = Path(file_path)

    if op_name == "redacted":
        data = t_visual_redacted(data)
    elif op_name == "strong":
        data = t_visual_strong(data)
    else:
        data = t_visual_redacted_noise(data)

    temp_name = _variant_filename(f"temp_{op_name}", original_path.name, ".pdf")
    temp_path = OUTPUT_DIR / temp_name

    render_document_from_data(
        data,
        document_type,
        "",
        str(temp_path),
        doc_seed,
        reorder_blocks=reorder,
        reorder_seed=random.randint(0, 2_147_483_647) if reorder else None,
    )

    return str(temp_path)


def generate_visual_scan_variant(file_path: str, transformation_type: str, seed: int | None = None) -> dict:
    original_path = Path(file_path)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    specs = {
        "scan_low_dpi": {"source": "original", "dpi": 105, "blur": 0.0, "quality": 58, "resize": 0.85},
        "scan_low_dpi_blur": {"source": "original", "dpi": 95, "blur": 0.75, "quality": 48, "resize": 0.75},
        "scan_redacted_low_dpi": {"source": "redacted", "dpi": 105, "blur": 0.45, "quality": 52, "resize": 0.82},
        "scan_strong_low_dpi": {"source": "strong", "dpi": 90, "blur": 0.95, "quality": 45, "resize": 0.72},
    }

    if transformation_type not in specs:
        raise ValueError(f"Transformacion scan no soportada: {transformation_type}")

    spec = specs[transformation_type]
    source_path = str(original_path)

    if spec["source"] == "redacted":
        source_path = _v2_render_temp_redacted_pdf(file_path, "redacted", seed=seed, reorder=False)
    elif spec["source"] == "strong":
        source_path = _v2_render_temp_redacted_pdf(file_path, "strong", seed=seed, reorder=True)

    img = _v2_pdf_to_image(source_path, dpi=spec["dpi"])
    img = _v2_apply_scan_degradation(
        img,
        blur=spec["blur"],
        jpeg_quality=spec["quality"],
        resize_factor=spec["resize"],
    )

    variant_filename = _variant_filename(transformation_type, original_path.name, ".pdf")
    variant_path = OUTPUT_DIR / variant_filename
    _v2_image_to_pdf(img, str(variant_path))

    return {
        "original_filename": original_path.name,
        "original_path": str(original_path),
        "variant_filename": variant_filename,
        "variant_path": str(variant_path),
        "transformation_type": transformation_type,
        "protocol_id": PROTOCOL_TRANSFORMATION_MAP.get(transformation_type),
        "layout_preserved": False,
    }


SCAN_VISUAL_TRANSFORMS = {
    "scan_low_dpi": "S1",
    "scan_low_dpi_blur": "S2",
    "scan_redacted_low_dpi": "S3",
    "scan_strong_low_dpi": "S4",
}

PROTOCOL_TRANSFORMATION_MAP.update(SCAN_VISUAL_TRANSFORMS)


_previous_generate_variant_from_pdf_visual_v2 = generate_variant_from_pdf

def generate_variant_from_pdf(
    file_path: str,
    transformation_type: str = "combined",
    seed: int | None = None,
) -> dict:
    if transformation_type in SCAN_VISUAL_TRANSFORMS:
        return generate_visual_scan_variant(file_path, transformation_type, seed=seed)

    return _previous_generate_variant_from_pdf_visual_v2(
        file_path=file_path,
        transformation_type=transformation_type,
        seed=seed,
    )

