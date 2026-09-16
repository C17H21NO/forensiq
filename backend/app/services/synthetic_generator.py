"""
ForensiQ synthetic financial document generator — Visual V4 FINAL.

Goals:
- controlled, reproducible corpus for OE3;
- generic synthetic financial identity (no real institution imitation);
- cleaner, denser and more realistic document layouts;
- document-type-specific content structure;
- stable ground-truth metadata for legitimate and distractor documents;
- compatible public API with the previous synthetic_generator.py.
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from random import choice, randint, uniform

from faker import Faker
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


# ---------------------------------------------------------------------------
# Configuration and reproducibility
# ---------------------------------------------------------------------------

DEFAULT_LOCALE = "es_ES"
fake = Faker(DEFAULT_LOCALE)

# In the real project this module lives under backend/app/services/, so parents[3]
# resolves to the repository root. Keep a safe fallback for isolated execution.
try:
    _BASE_DATA_DIR = Path(__file__).resolve().parents[3] / "synthetic_data"
except IndexError:
    _BASE_DATA_DIR = Path(__file__).resolve().parent / "synthetic_data"

OUTPUT_DIR = _BASE_DATA_DIR / "legitimate"
DISTRACTOR_OUTPUT_DIR = _BASE_DATA_DIR / "distractors"
DISTRACTOR_SEED_OFFSET = 1_000_003

DOCUMENT_TYPES = [
    "estado_cuenta",
    "solicitud_credito",
    "contrato_financiero",
    "ficha_kyc",
    "comprobante_operacion",
    "reporte_transaccion",
    "carta_cobranza",
    "constancia_bancaria",
]

TITLES = {
    "estado_cuenta": "Estado de Cuenta",
    "solicitud_credito": "Solicitud de Crédito",
    "contrato_financiero": "Contrato Financiero",
    "ficha_kyc": "Ficha de Conocimiento del Cliente",
    "comprobante_operacion": "Comprobante de Operación",
    "reporte_transaccion": "Reporte de Transacción",
    "carta_cobranza": "Carta de Cobranza",
    "constancia_bancaria": "Constancia Bancaria",
}

DOCUMENT_SUBTITLES = {
    "estado_cuenta": "Resumen de movimientos y saldo referencial",
    "solicitud_credito": "Evaluación documental de solicitud sintética",
    "contrato_financiero": "Acuerdo financiero de carácter exclusivamente sintético",
    "ficha_kyc": "Registro de conocimiento y perfil del cliente",
    "comprobante_operacion": "Constancia de una operación financiera simulada",
    "reporte_transaccion": "Reporte de control transaccional sintético",
    "carta_cobranza": "Comunicación de seguimiento financiero simulada",
    "constancia_bancaria": "Constancia de relación financiera sintética",
}

LIMA_DISTRICTS = [
    "Miraflores", "San Isidro", "Santiago de Surco", "San Borja",
    "Jesús María", "Magdalena del Mar", "Pueblo Libre", "Lince",
    "La Molina", "Barranco", "Surquillo", "San Miguel",
]

STREET_NAMES = [
    "Av. Los Cedros", "Av. República", "Jr. Las Flores", "Calle Los Álamos",
    "Av. Primavera", "Jr. Independencia", "Calle Las Palmeras", "Av. Central",
    "Jr. Los Pinos", "Calle Pacífico", "Av. del Parque", "Jr. Unión",
]

OCCUPATIONS = [
    "Analista financiero", "Comerciante", "Administrador", "Contador",
    "Consultor independiente", "Empleado dependiente", "Ingeniero",
    "Docente", "Emprendedor", "Asistente administrativo",
]


# ---------------------------------------------------------------------------
# V4 identity architecture
# ---------------------------------------------------------------------------
# All names and identities below are fictional. They intentionally describe
# broad financial-document archetypes instead of imitating any real institution.
ENTITY_PROFILES = {
    "andino_capital": {
        "name": "Banco Andino Capital",
        "short": "BAC",
        "personality": "traditional_corporate",
        "tagline": "Servicios financieros · documentación institucional",
    },
    "finexa": {
        "name": "Finexa",
        "short": "FX",
        "personality": "digital_minimal",
        "tagline": "Gestión financiera digital",
    },
    "metropolitana_sur": {
        "name": "Caja Metropolitana Sur",
        "short": "CMS",
        "personality": "administrative_institutional",
        "tagline": "Servicios financieros regionales",
    },
    "nova_financiera": {
        "name": "Nova Financiera",
        "short": "NF",
        "personality": "modern_commercial",
        "tagline": "Soluciones financieras",
    },
}

TEMPLATE_FAMILIES = {
    "estado_cuenta": ["tradicional_corporativo", "digital_resumen"],
    "solicitud_credito": ["formulario_clasico", "evaluacion_ejecutiva"],
    "contrato_financiero": ["institucional", "compacto"],
    "ficha_kyc": ["expediente_compliance", "dashboard_perfil"],
    "comprobante_operacion": ["voucher", "digital"],
    "reporte_transaccion": ["auditoria", "monitoreo"],
    "carta_cobranza": ["carta_formal", "notificacion_administrativa"],
    "constancia_bancaria": ["institucional", "minimalista"],
}

ENTITY_IDS = tuple(ENTITY_PROFILES)


def _select_entity_id(doc_seed=None, document_type: str = "") -> str:
    seed = _stable_visual_seed(doc_seed, f"{document_type}|entity")
    return ENTITY_IDS[seed % len(ENTITY_IDS)]


def _select_template_family(doc_seed=None, document_type: str = "") -> str:
    families = TEMPLATE_FAMILIES[document_type]
    seed = _stable_visual_seed(doc_seed, f"{document_type}|family")
    return families[seed % len(families)]


# ---------------------------------------------------------------------------
# Visual system
# ---------------------------------------------------------------------------

PAGE_W, PAGE_H = A4
LEFT = 1.55 * cm
RIGHT = PAGE_W - 1.55 * cm
CONTENT_W = RIGHT - LEFT
HEADER_TOP = PAGE_H - 1.35 * cm
BODY_TOP = PAGE_H - 5.25 * cm
BODY_BOTTOM = 4.0 * cm

INK = colors.HexColor("#172033")
MUTED = colors.HexColor("#667085")
LINE = colors.HexColor("#D0D5DD")
SOFT = colors.HexColor("#F5F7FA")
SOFT_2 = colors.HexColor("#EEF2F6")
ACCENT = colors.HexColor("#244A73")
ACCENT_LIGHT = colors.HexColor("#EAF0F6")
DANGER = colors.HexColor("#8D2B2B")
STAMP_LIGHT = colors.HexColor("#F9EEEE")
WHITE = colors.white


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------

def set_global_seed(seed: int, locale: str = DEFAULT_LOCALE) -> None:
    """Seed Python random and Faker so the generated corpus is reproducible."""
    global fake
    random.seed(seed)
    Faker.seed(seed)
    fake = Faker(locale)
    fake.seed_instance(seed)


def random_dni(namespace: str | None = None) -> str:
    # Namespace separates legitimate/distractor synthetic identifier spaces.
    # It does NOT claim the number is unassigned in real Peru.
    first = "7" if namespace == "legitimate" else "8" if namespace == "distractor" else str(randint(0, 9))
    return first + "".join(str(randint(0, 9)) for _ in range(7))


def random_ruc(namespace: str | None = None) -> str:
    prefix = "20" if namespace != "distractor" else "10"
    return prefix + "".join(str(randint(0, 9)) for _ in range(9))


def random_phone(namespace: str | None = None) -> str:
    second = "1" if namespace == "legitimate" else "2" if namespace == "distractor" else str(randint(0, 9))
    return "9" + second + "".join(str(randint(0, 9)) for _ in range(7))


def random_bank_account(namespace: str | None = None) -> str:
    branch = randint(100, 999)
    lead = "7" if namespace == "legitimate" else "8" if namespace == "distractor" else str(randint(0, 9))
    core = lead + "".join(str(randint(0, 9)) for _ in range(11))
    return f"{branch}-{core}-{randint(10, 99)}"


def random_money(minimum: float = 500, maximum: float = 95_000) -> str:
    amount = round(uniform(minimum, maximum), 2)
    return f"S/ {amount:,.2f}"


def random_date() -> str:
    start_date = datetime(2021, 1, 1)
    delta_days = randint(0, 1600)
    return (start_date + timedelta(days=delta_days)).strftime("%Y-%m-%d")


def random_lima_address() -> str:
    return f"{choice(STREET_NAMES)} {randint(100, 1999)}, {choice(LIMA_DISTRICTS)}, Lima"


def build_person_data(identifier_namespace: str | None = None) -> dict:
    return {
        "name": fake.name(),
        "dni": random_dni(identifier_namespace),
        "ruc": random_ruc(identifier_namespace),
        "email": f"{fake.user_name()}.{'l' if identifier_namespace == 'legitimate' else 'd' if identifier_namespace == 'distractor' else 'x'}{randint(1000, 9999)}@example.net",
        "phone": random_phone(identifier_namespace),
        "account": random_bank_account(identifier_namespace),
        "amount": random_money(),
        "date": random_date(),
        "address": random_lima_address(),
        "occupation": choice(OCCUPATIONS),
        "risk_level": choice(["Bajo", "Medio", "Alto"]),
        "operation_code": f"OP-{randint(100000, 999999)}",
        "currency": "PEN",
        "branch": choice(["Lima Centro", "Lima Este", "Lima Norte", "Lima Sur", "Canal Digital"]),
    }


# ---------------------------------------------------------------------------
# Text/layout primitives
# ---------------------------------------------------------------------------

def _safe_set_alpha(c, fill: float | None = None, stroke: float | None = None) -> None:
    try:
        if fill is not None:
            c.setFillAlpha(fill)
        if stroke is not None:
            c.setStrokeAlpha(stroke)
    except Exception:
        pass


def _stable_visual_seed(doc_seed, document_type: str = "") -> int:
    raw = f"{doc_seed}|{document_type}|forensiq-v4".encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest()[:12], 16)


def _style_id(doc_seed=None, document_type: str = "") -> int:
    return _stable_visual_seed(doc_seed, document_type) % 6


def _add_box(labels, cls, x, y, w, h, **extra):
    item = {
        "class": cls,
        "x0": round(x / PAGE_W, 6),
        "y0": round(y / PAGE_H, 6),
        "x1": round((x + w) / PAGE_W, 6),
        "y1": round((y + h) / PAGE_H, 6),
        "cx": round((x + w / 2) / PAGE_W, 6),
        "cy": round((y + h / 2) / PAGE_H, 6),
        "width": round(w / PAGE_W, 6),
        "height": round(h / PAGE_H, 6),
    }
    item.update(extra)
    labels.append(item)


def _wrap_text(text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    words = str(text).split()
    if not words:
        return [""]
    lines, current = [], words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_logo(c, labels, style_id: int) -> None:
    x, y, w, h = LEFT, PAGE_H - 2.80 * cm, 2.35 * cm, 1.10 * cm
    c.saveState()
    c.setStrokeColor(ACCENT)
    c.setFillColor(ACCENT_LIGHT)
    c.roundRect(x, y, w, h, 6, stroke=1, fill=1)
    c.setFillColor(ACCENT)
    if style_id % 2 == 0:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(x + 0.25 * cm, y + 0.55 * cm, "FS")
        c.setFont("Helvetica-Bold", 6.1)
        c.drawString(x + 0.98 * cm, y + 0.66 * cm, "FORENSIQ")
        c.setFont("Helvetica", 4.9)
        c.drawString(x + 0.98 * cm, y + 0.38 * cm, "SYNTHETIC LAB")
    else:
        c.setFont("Helvetica-Bold", 5.7)
        c.drawCentredString(x + w / 2, y + 0.67 * cm, "ENTIDAD FINANCIERA")
        c.setFont("Helvetica-Bold", 6.6)
        c.drawCentredString(x + w / 2, y + 0.36 * cm, "SINTÉTICA")
    c.restoreState()
    _add_box(labels, "logo", x, y, w, h)


def draw_header(
    c, title: str, doc_code: str, document_type: str, doc_seed=None, labels=None,
    entity_id: str | None = None, template_family: str | None = None,
):
    labels = labels if labels is not None else []
    entity_id = entity_id or _select_entity_id(doc_seed, document_type)
    template_family = template_family or _select_template_family(doc_seed, document_type)
    entity = ENTITY_PROFILES[entity_id]

    # Compact fictional identity mark. No real-bank logo or template is reproduced.
    x, y, w, h = LEFT, PAGE_H - 2.72 * cm, 2.55 * cm, 1.02 * cm
    c.saveState()
    c.setStrokeColor(ACCENT)
    c.setFillColor(ACCENT_LIGHT if entity["personality"] != "digital_minimal" else colors.HexColor("#F8FAFC"))
    c.roundRect(x, y, w, h, 5, stroke=1, fill=1)
    c.setFillColor(ACCENT)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(x + 0.18 * cm, y + 0.54 * cm, entity["short"])
    c.setFont("Helvetica-Bold", 5.6)
    c.drawString(x + 0.83 * cm, y + 0.61 * cm, entity["name"][:24])
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 4.7)
    c.drawString(x + 0.83 * cm, y + 0.34 * cm, entity["tagline"][:34])
    c.restoreState()
    _add_box(labels, "logo", x, y, w, h, entity_id=entity_id)

    title_x = LEFT + 2.88 * cm
    title_y = PAGE_H - 1.72 * cm
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 16.2)
    c.drawString(title_x, title_y, title)

    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.3)
    subtitle = DOCUMENT_SUBTITLES.get(document_type, "Documento financiero")
    c.drawString(title_x, title_y - 0.45 * cm, subtitle)

    meta_y = PAGE_H - 3.25 * cm
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.8)
    c.drawString(LEFT, meta_y, f"Código: {doc_code}")
    c.drawString(LEFT + 4.0 * cm, meta_y, f"Familia: {template_family.replace('_', ' ')}")
    c.drawRightString(RIGHT, meta_y, entity["name"])

    c.setStrokeColor(ACCENT)
    c.setLineWidth(1.05)
    c.line(LEFT, PAGE_H - 3.58 * cm, RIGHT, PAGE_H - 3.58 * cm)
    return labels


def _draw_watermark(c, labels, doc_seed=None, document_type=""):
    style_id = _style_id(doc_seed, document_type)
    c.saveState()
    # Use a genuinely light ink instead of relying on PDF alpha support.
    # This keeps the watermark visible but prevents it from competing with content.
    c.setFillColor(colors.HexColor("#E6EBF1"))
    c.translate(PAGE_W / 2, PAGE_H * 0.47)
    c.rotate(28 if style_id % 2 else 0)
    c.setFont("Helvetica-Bold", 23)
    c.drawCentredString(0, 0, "DOCUMENTO SINTÉTICO")
    c.restoreState()
    _add_box(labels, "watermark", PAGE_W * 0.20, PAGE_H * 0.44, PAGE_W * 0.60, PAGE_H * 0.11)


def _draw_validation_badge(c, labels, doc_seed=None, document_type=""):
    style_id = _style_id(doc_seed, document_type)
    w, h = 4.1 * cm, 0.86 * cm
    x, y = RIGHT - w, 2.42 * cm
    c.saveState()
    c.setFillColor(SOFT)
    c.setStrokeColor(LINE)
    c.roundRect(x, y, w, h, 5, stroke=1, fill=1)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 6.2)
    c.drawString(x + 0.20 * cm, y + 0.51 * cm, "CONTROL DE MUESTRA")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 5.6)
    c.drawString(x + 0.20 * cm, y + 0.22 * cm, f"Sintético · estilo V3-{style_id + 1}")
    c.restoreState()
    _add_box(labels, "validation_box", x, y, w, h)


def _draw_pseudo_qr(c, labels, doc_seed=None, document_type=""):
    seed = _stable_visual_seed(doc_seed, f"{document_type}|qr")
    rng = random.Random(seed)
    grid, cell = 11, 0.082 * cm
    size = grid * cell
    x0, y0 = LEFT, 2.35 * cm

    c.saveState()
    c.setFillColor(INK)
    c.setStrokeColor(INK)
    c.rect(x0 - 0.06 * cm, y0 - 0.06 * cm, size + 0.12 * cm, size + 0.12 * cm, stroke=1, fill=0)
    fixed = {
        (0, 0), (0, 1), (1, 0), (1, 1),
        (0, grid - 1), (0, grid - 2), (1, grid - 1), (1, grid - 2),
        (grid - 1, 0), (grid - 2, 0), (grid - 1, 1), (grid - 2, 1),
    }
    for row in range(grid):
        for col in range(grid):
            if (row, col) in fixed or rng.random() > 0.52:
                c.rect(x0 + col * cell, y0 + (grid - 1 - row) * cell, cell * 0.80, cell * 0.80, stroke=0, fill=1)
    c.restoreState()
    _add_box(labels, "pseudo_qr", x0 - 0.06 * cm, y0 - 0.06 * cm, size + 0.12 * cm, size + 0.12 * cm)


def _draw_stamp(c, labels, doc_seed=None, document_type=""):
    seed = _stable_visual_seed(doc_seed, f"{document_type}|stamp")
    rng = random.Random(seed)
    r = 0.68 * cm
    x = LEFT + 2.25 * cm + rng.uniform(-0.04, 0.04) * cm
    y = 2.78 * cm
    c.saveState()
    _safe_set_alpha(c, stroke=0.8, fill=0.8)
    c.setStrokeColor(DANGER)
    c.setFillColor(DANGER)
    c.setLineWidth(0.9)
    c.circle(x, y, r, stroke=1, fill=0)
    c.circle(x, y, r * 0.73, stroke=1, fill=0)
    c.setFont("Helvetica-Bold", 5.4)
    c.drawCentredString(x, y + 0.15 * cm, "VALIDADO")
    c.setFont("Helvetica", 4.7)
    c.drawCentredString(x, y - 0.08 * cm, "SINTÉTICO")
    c.drawCentredString(x, y - 0.31 * cm, "NO VÁLIDO")
    c.restoreState()
    _add_box(labels, "stamp", x - r, y - r, 2 * r, 2 * r)


def draw_visual_security_features(c, document_type: str, doc_seed=None):
    # V4: no central watermark. Synthetic status is disclosed discretely in
    # the footer/control zone so the document remains immersive yet unambiguous.
    labels = []
    _draw_pseudo_qr(c, labels, doc_seed, document_type)
    _draw_stamp(c, labels, doc_seed, document_type)
    _draw_validation_badge(c, labels, doc_seed, document_type)
    return labels


def draw_footer(c, page_number: int = 1):
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.line(LEFT, 1.72 * cm, RIGHT, 1.72 * cm)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.2)
    c.drawString(LEFT, 1.35 * cm, "MUESTRA ACADÉMICA · DATOS FICTICIOS · SIN VALIDEZ LEGAL")
    c.drawRightString(RIGHT, 1.35 * cm, f"Página {page_number}")


def draw_section_title(c, x, y, title, width=CONTENT_W):
    box_h = 0.64 * cm
    c.setFillColor(ACCENT_LIGHT)
    c.setStrokeColor(colors.HexColor("#CBD8E6"))
    c.roundRect(x, y - box_h + 0.14 * cm, width, box_h, 4, stroke=1, fill=1)
    c.setFillColor(ACCENT)
    c.setFont("Helvetica-Bold", 9.2)
    c.drawString(x + 0.22 * cm, y - 0.23 * cm, title)
    return y - box_h - 0.18 * cm


def draw_key_value(c, x, y, label, value, line_height=17, width=CONTENT_W, shade=False):
    row_h = 0.62 * cm
    if shade:
        c.setFillColor(colors.HexColor("#FAFBFC"))
        c.rect(x, y - row_h + 0.08 * cm, width, row_h, stroke=0, fill=1)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 7.8)
    c.drawString(x + 0.12 * cm, y - 0.25 * cm, str(label))
    value_x = x + 4.45 * cm
    max_w = width - 4.65 * cm
    c.setFont("Helvetica", 7.8)
    value_lines = _wrap_text(str(value), "Helvetica", 7.8, max_w)
    for idx, line in enumerate(value_lines[:2]):
        c.drawString(value_x, y - 0.25 * cm - idx * 0.34 * cm, line)
    return y - max(row_h, 0.42 * cm + len(value_lines[:2]) * 0.30 * cm)


def draw_simple_table(c, x, y, headers, rows, width=CONTENT_W):
    cols = len(headers)
    col_w = width / cols
    header_h = 0.66 * cm
    row_h = 0.62 * cm

    c.setFillColor(ACCENT)
    c.setStrokeColor(WHITE)
    for i, header in enumerate(headers):
        c.rect(x + i * col_w, y - header_h, col_w, header_h, stroke=1, fill=1)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 6.8)
        c.drawString(x + i * col_w + 0.12 * cm, y - 0.41 * cm, str(header))
        c.setFillColor(ACCENT)

    y -= header_h
    for r_idx, row in enumerate(rows):
        fill = WHITE if r_idx % 2 == 0 else SOFT
        for i, value in enumerate(row):
            c.setFillColor(fill)
            c.setStrokeColor(LINE)
            c.rect(x + i * col_w, y - row_h, col_w, row_h, stroke=1, fill=1)
            c.setFillColor(INK)
            c.setFont("Helvetica", 6.7)
            text = str(value)
            if stringWidth(text, "Helvetica", 6.7) > col_w - 0.24 * cm:
                text = text[:28] + "…" if len(text) > 29 else text
            c.drawString(x + i * col_w + 0.12 * cm, y - 0.40 * cm, text)
        y -= row_h
    return y - 0.24 * cm


def draw_paragraph(c, x, y, lines, size=8.2, leading=12, width=CONTENT_W):
    c.setFillColor(INK)
    c.setFont("Helvetica", size)
    for raw_line in lines:
        for line in _wrap_text(str(raw_line), "Helvetica", size, width - 0.20 * cm):
            c.drawString(x + 0.10 * cm, y, line)
            y -= leading
        y -= 2
    return y


def draw_signature(c, y, labels, width=CONTENT_W):
    count = len(labels)
    c.setStrokeColor(colors.HexColor("#98A2B3"))
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.8)
    if count <= 1:
        line_w = 5.8 * cm
        x = LEFT + (width - line_w) / 2
        c.line(x, y, x + line_w, y)
        c.drawCentredString(x + line_w / 2, y - 0.36 * cm, labels[0] if labels else "Firma")
    else:
        gap = 1.2 * cm
        line_w = (width - gap) / 2
        x1, x2 = LEFT, LEFT + line_w + gap
        c.line(x1, y, x1 + line_w, y)
        c.line(x2, y, x2 + line_w, y)
        c.drawCentredString(x1 + line_w / 2, y - 0.36 * cm, labels[0])
        c.drawCentredString(x2 + line_w / 2, y - 0.36 * cm, labels[1])
    return y - 0.80 * cm


# ---------------------------------------------------------------------------
# Declarative blocks by document type
# ---------------------------------------------------------------------------

def build_estado_cuenta_blocks(data):
    if data.get("_redact_transactions"):
        rows = [["[FECHA]", "Movimiento", "S/ [MONTO]"] for _ in range(4)]
    elif data.get("_drop_transactions"):
        rows = [["—", "Movimiento omitido", "—"], ["—", "Cargo omitido", "—"]]
    else:
        rows = [
            [random_date(), "Abono", random_money()],
            [random_date(), "Cargo", random_money()],
            [random_date(), "Transferencia", random_money()],
            [random_date(), "Pago de servicio", random_money()],
            [random_date(), "Compra", random_money(50, 8_000)],
        ]
    return [
        {"kind": "section", "title": "Datos del cliente"},
        {"kind": "kv", "label": "Nombre completo", "value": data["name"]},
        {"kind": "kv", "label": "DNI", "value": data["dni"]},
        {"kind": "kv", "label": "Cuenta bancaria", "value": data["account"]},
        {"kind": "kv", "label": "Correo electrónico", "value": data["email"]},
        {"kind": "section", "title": "Movimientos del periodo"},
        {"kind": "table", "headers": ["Fecha", "Operación", "Monto"], "rows": rows},
        {"kind": "section", "title": "Resumen"},
        {"kind": "kv", "label": "Saldo referencial", "value": data["amount"]},
        {"kind": "kv", "label": "Canal asociado", "value": data["branch"]},
    ]


def build_solicitud_credito_blocks(data):
    return [
        {"kind": "section", "title": "Datos del solicitante"},
        {"kind": "kv", "label": "Nombre completo", "value": data["name"]},
        {"kind": "kv", "label": "DNI", "value": data["dni"]},
        {"kind": "kv", "label": "RUC asociado", "value": data["ruc"]},
        {"kind": "kv", "label": "Dirección", "value": data["address"]},
        {"kind": "kv", "label": "Ocupación", "value": data["occupation"]},
        {"kind": "section", "title": "Condiciones solicitadas"},
        {"kind": "kv", "label": "Monto solicitado", "value": data["amount"]},
        {"kind": "kv", "label": "Fecha de emisión", "value": data["date"]},
        {"kind": "kv", "label": "Nivel de riesgo", "value": data["risk_level"]},
        {"kind": "kv", "label": "Canal de origen", "value": data["branch"]},
        {"kind": "section", "title": "Declaración"},
        {"kind": "paragraph", "lines": [
            "El solicitante declara que la información incluida en esta muestra es ficticia y ha sido generada para evaluación académica.",
            "La presente solicitud no representa una operación crediticia real ni genera obligación alguna.",
        ]},
        {"kind": "signature", "labels": ["Firma simulada del solicitante", "Validación sintética"]},
    ]


def build_contrato_financiero_blocks(data):
    return [
        {"kind": "section", "title": "Partes del contrato"},
        {"kind": "kv", "label": "Cliente", "value": data["name"]},
        {"kind": "kv", "label": "DNI", "value": data["dni"]},
        {"kind": "kv", "label": "Cuenta asociada", "value": data["account"]},
        {"kind": "kv", "label": "Correo", "value": data["email"]},
        {"kind": "section", "title": "Condiciones principales"},
        {"kind": "paragraph", "lines": [
            "Primera. La entidad sintética registra una obligación financiera exclusivamente referencial.",
            "Segunda. El cliente sintético acepta condiciones simuladas de pago, seguimiento y control documental.",
            "Tercera. Los datos incluidos en esta muestra no corresponden a una relación contractual real.",
            "Cuarta. El documento se utiliza únicamente para pruebas de recuperación y comparación forense.",
        ]},
        {"kind": "section", "title": "Datos de control"},
        {"kind": "kv", "label": "Fecha", "value": data["date"]},
        {"kind": "kv", "label": "Monto referencial", "value": data["amount"]},
        {"kind": "signature", "labels": ["Cliente sintético", "Representante sintético"]},
    ]


def build_ficha_kyc_blocks(data):
    return [
        {"kind": "section", "title": "Identificación"},
        {"kind": "kv", "label": "Nombre completo", "value": data["name"]},
        {"kind": "kv", "label": "DNI", "value": data["dni"]},
        {"kind": "kv", "label": "RUC asociado", "value": data["ruc"]},
        {"kind": "kv", "label": "Teléfono", "value": data["phone"]},
        {"kind": "kv", "label": "Correo electrónico", "value": data["email"]},
        {"kind": "section", "title": "Perfil del cliente"},
        {"kind": "kv", "label": "Ocupación", "value": data["occupation"]},
        {"kind": "kv", "label": "Nivel de riesgo", "value": data["risk_level"]},
        {"kind": "kv", "label": "Monto mensual estimado", "value": data["amount"]},
        {"kind": "kv", "label": "Dirección declarada", "value": data["address"]},
        {"kind": "section", "title": "Control KYC sintético"},
        {"kind": "paragraph", "lines": [
            "Registro generado para simular tareas de identificación, comparación documental y revisión contextual de PII.",
        ]},
    ]


def build_comprobante_operacion_blocks(data):
    return [
        {"kind": "section", "title": "Detalle de la operación"},
        {"kind": "kv", "label": "Código de operación", "value": data["operation_code"]},
        {"kind": "kv", "label": "Fecha de emisión", "value": data["date"]},
        {"kind": "kv", "label": "Cuenta origen", "value": data["account"]},
        {"kind": "kv", "label": "Titular", "value": data["name"]},
        {"kind": "kv", "label": "DNI", "value": data["dni"]},
        {"kind": "section", "title": "Importe y canal"},
        {"kind": "kv", "label": "Monto referencial", "value": data["amount"]},
        {"kind": "kv", "label": "Moneda", "value": data["currency"]},
        {"kind": "kv", "label": "Canal", "value": data["branch"]},
        {"kind": "section", "title": "Observación"},
        {"kind": "paragraph", "lines": ["Operación registrada en un entorno sintético de evaluación; no corresponde a una transacción real."]},
    ]


def build_reporte_transaccion_blocks(data):
    rows = [
        ["Cliente", data["name"], data["dni"]],
        ["Cuenta", data["account"], data["amount"]],
        ["RUC", data["ruc"], data["risk_level"]],
        ["Contacto", data["email"], data["phone"]],
    ]
    return [
        {"kind": "section", "title": "Resumen transaccional"},
        {"kind": "table", "headers": ["Campo", "Valor principal", "Valor secundario"], "rows": rows},
        {"kind": "section", "title": "Clasificación"},
        {"kind": "kv", "label": "Nivel de riesgo", "value": data["risk_level"]},
        {"kind": "kv", "label": "Canal", "value": data["branch"]},
        {"kind": "section", "title": "Observación"},
        {"kind": "paragraph", "lines": [
            "Reporte sintético para evaluación de recuperación documental.",
            "La información contenida es ficticia y puede ser modificada de forma controlada para experimentos forenses.",
        ]},
    ]


def build_carta_cobranza_blocks(data):
    return [
        {"kind": "section", "title": "Comunicación"},
        {"kind": "paragraph", "lines": [
            f"Estimado/a {data['name']}:",
            f"Se registra una obligación referencial asociada al DNI {data['dni']} por un monto simulado de {data['amount']}.",
            "La presente comunicación forma parte de un corpus académico y no constituye una gestión real de cobranza.",
        ]},
        {"kind": "section", "title": "Datos de contacto registrados"},
        {"kind": "kv", "label": "Correo", "value": data["email"]},
        {"kind": "kv", "label": "Teléfono", "value": data["phone"]},
        {"kind": "kv", "label": "Fecha de referencia", "value": data["date"]},
        {"kind": "section", "title": "Seguimiento"},
        {"kind": "paragraph", "lines": ["Para fines del experimento, cualquier respuesta o coordinación es igualmente sintética."]},
        {"kind": "signature", "labels": ["Área de seguimiento financiero sintético"]},
    ]


def build_constancia_bancaria_blocks(data):
    return [
        {"kind": "section", "title": "Titular de la constancia"},
        {"kind": "kv", "label": "Nombre", "value": data["name"]},
        {"kind": "kv", "label": "Documento de identidad", "value": data["dni"]},
        {"kind": "section", "title": "Relación financiera referencial"},
        {"kind": "kv", "label": "Cuenta asociada", "value": data["account"]},
        {"kind": "kv", "label": "Fecha de emisión", "value": data["date"]},
        {"kind": "kv", "label": "Canal", "value": data["branch"]},
        {"kind": "section", "title": "Constancia"},
        {"kind": "paragraph", "lines": [
            "Se deja constancia de una relación financiera exclusivamente referencial para fines académicos.",
            "Este documento es sintético y carece de validez bancaria, contractual o legal.",
        ]},
        {"kind": "signature", "labels": ["Representante sintético"]},
    ]


BLOCK_BUILDERS = {
    "estado_cuenta": build_estado_cuenta_blocks,
    "solicitud_credito": build_solicitud_credito_blocks,
    "contrato_financiero": build_contrato_financiero_blocks,
    "ficha_kyc": build_ficha_kyc_blocks,
    "comprobante_operacion": build_comprobante_operacion_blocks,
    "reporte_transaccion": build_reporte_transaccion_blocks,
    "carta_cobranza": build_carta_cobranza_blocks,
    "constancia_bancaria": build_constancia_bancaria_blocks,
}


def build_document_blocks(data: dict, document_type: str) -> list:
    return BLOCK_BUILDERS[document_type](data)


def _group_blocks(blocks: list) -> list:
    groups, current = [], []
    for block in blocks:
        if block["kind"] == "section" and current:
            groups.append(current)
            current = [block]
        else:
            current.append(block)
    if current:
        groups.append(current)
    return groups


def _estimated_block_height(block: dict) -> float:
    kind = block["kind"]
    if kind == "section":
        return 0.95 * cm
    if kind == "kv":
        return 0.72 * cm
    if kind == "table":
        return (1 + len(block.get("rows", []))) * 0.64 * cm + 0.28 * cm
    if kind == "paragraph":
        lines = sum(max(1, len(str(x)) // 85 + 1) for x in block.get("lines", []))
        return lines * 0.48 * cm + 0.18 * cm
    if kind == "signature":
        return 1.25 * cm
    if kind == "spacer":
        return block.get("height", 8)
    return 0.5 * cm


def render_blocks(c, blocks: list, start_y: float, *, new_page_callback=None) -> float:
    y = start_y
    shade_idx = 0
    for block in blocks:
        needed = _estimated_block_height(block)
        if y - needed < BODY_BOTTOM:
            if new_page_callback is None:
                c.showPage()
                y = BODY_TOP
            else:
                y = new_page_callback()
        kind = block["kind"]
        if kind == "section":
            y -= 0.10 * cm
            y = draw_section_title(c, LEFT, y, block["title"])
            shade_idx = 0
        elif kind == "kv":
            y = draw_key_value(c, LEFT, y, block["label"], block["value"], shade=shade_idx % 2 == 1)
            shade_idx += 1
        elif kind == "table":
            y = draw_simple_table(c, LEFT, y, block["headers"], block["rows"])
        elif kind == "paragraph":
            y = draw_paragraph(c, LEFT, y, block["lines"])
        elif kind == "signature":
            y -= 0.45 * cm
            y = draw_signature(c, y, block["labels"])
        elif kind == "spacer":
            y -= block.get("height", 8)
    return y



# ---------------------------------------------------------------------------
# V4 Stage 2 — Estado de Cuenta specialized renderer
# ---------------------------------------------------------------------------

def _money_to_float(value) -> float:
    raw = str(value or "0").replace("S/", "").replace(",", "").strip()
    try:
        return float(raw)
    except Exception:
        return 0.0


def _fmt_money(value: float) -> str:
    return f"S/ {value:,.2f}"


def _mask_account(account: str) -> str:
    raw = str(account or "")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) < 6:
        return raw
    return f"••• •••• {digits[-6:]}"


def _estado_cuenta_payload(data: dict, doc_seed=None) -> dict:
    """Stable statement data derived from the document seed.

    The payload is regenerated identically for parent/variant PDFs so binary
    recode and controlled transformations do not accidentally change unrelated
    transaction text.
    """
    rng = random.Random(_stable_visual_seed(doc_seed, "estado_cuenta|payload"))
    final_balance = max(250.0, _money_to_float(data.get("amount")))

    operations = [
        ("Abono de nómina", "Abono", 1),
        ("Transferencia recibida", "Transferencia", 1),
        ("Depósito en cuenta", "Abono", 1),
        ("Compra POS", "Compra", -1),
        ("Pago de servicio", "Servicios", -1),
        ("Transferencia enviada", "Transferencia", -1),
        ("Retiro cajero", "Cajero", -1),
        ("Comisión de servicio", "Comisión", -1),
        ("Compra por internet", "Compra", -1),
        ("Pago con tarjeta", "Tarjeta", -1),
        ("Transferencia interbancaria", "Transferencia", -1),
        ("Consumo en comercio", "Compra", -1),
        ("Devolución de compra", "Abono", 1),
        ("Pago automático", "Servicios", -1),
        ("Abono por devolución", "Abono", 1),
    ]
    rng.shuffle(operations)
    operations = operations[:12]

    rows = []
    credits = 0.0
    debits = 0.0
    base_date = datetime(2026, 8, 31)
    for idx, (description, channel, sign) in enumerate(operations):
        days_back = 1 + idx * 2 + rng.randint(0, 1)
        date = (base_date - timedelta(days=days_back)).strftime("%d/%m/%Y")
        if sign > 0:
            amount = round(rng.uniform(350, max(650, min(5500, final_balance * 0.20))), 2)
            credits += amount
        else:
            amount = round(rng.uniform(25, max(80, min(2400, final_balance * 0.09))), 2)
            debits += amount
        rows.append({
            "date": date,
            "description": description,
            "channel": channel,
            "amount": amount,
            "sign": sign,
        })

    opening_balance = max(100.0, final_balance - credits + debits)
    # Reconcile exactly: if clamping changed the opening balance, adjust final.
    final_balance = opening_balance + credits - debits

    if data.get("_redact_transactions"):
        rows = [
            {"date": "[FECHA]", "description": "[MOVIMIENTO]", "channel": "[CANAL]", "amount": 0.0, "sign": 0}
            for _ in range(5)
        ]
    elif data.get("_drop_transactions"):
        rows = [
            {"date": "—", "description": "Movimiento omitido", "channel": "—", "amount": 0.0, "sign": 0},
            {"date": "—", "description": "Movimiento omitido", "channel": "—", "amount": 0.0, "sign": 0},
        ]

    return {
        "period": "01/08/2026 — 31/08/2026",
        "cutoff": "31/08/2026",
        "account_type": rng.choice(["Cuenta Ahorros", "Cuenta Sueldo", "Cuenta Digital"]),
        "masked_account": _mask_account(data.get("account", "")),
        "opening_balance": opening_balance,
        "credits": credits,
        "debits": debits,
        "final_balance": final_balance,
        "rows": rows,
        "statement_number": f"EC-{rng.randint(100000, 999999)}",
    }


def _draw_entity_mark_compact(c, entity_id: str, *, x=LEFT, y=None, labels=None, dark=False):
    """Draw a compact fictional institution badge without text overflow.

    The acronym occupies a fixed left column. The institution name is fitted
    down slightly when needed, while the tagline can wrap to at most two lines.
    This keeps long identities such as Banco Andino Capital / Caja Metropolitana
    Sur fully inside the rounded badge in both light and dark variants.
    """
    labels = labels if labels is not None else []
    entity = ENTITY_PROFILES[entity_id]
    y = y if y is not None else PAGE_H - 2.35 * cm

    w, h = 4.15 * cm, 1.05 * cm
    acronym_x = x + 0.20 * cm
    text_x = x + 1.20 * cm
    text_right = x + w - 0.18 * cm
    text_max_w = text_right - text_x

    def _fit_size(text, font_name, preferred, minimum, max_width):
        size = preferred
        while size > minimum and stringWidth(str(text), font_name, size) > max_width:
            size -= 0.2
        return max(size, minimum)

    c.saveState()
    if dark:
        c.setFillColor(ACCENT)
        c.setStrokeColor(ACCENT)
        c.roundRect(x, y, w, h, 5, stroke=0, fill=1)
        primary = WHITE
        secondary = colors.HexColor("#E7EEF6")
    else:
        c.setFillColor(WHITE)
        c.setStrokeColor(ACCENT)
        c.roundRect(x, y, w, h, 5, stroke=1, fill=1)
        primary = ACCENT
        secondary = MUTED

    # Acronym / monogram.
    short_size = _fit_size(entity["short"], "Helvetica-Bold", 11.0, 9.0, 0.78 * cm)
    c.setFillColor(primary)
    c.setFont("Helvetica-Bold", short_size)
    c.drawString(acronym_x, y + 0.58 * cm, entity["short"])

    # Institution name: always one line, fitted to the available width.
    name_size = _fit_size(entity["name"], "Helvetica-Bold", 6.4, 5.0, text_max_w)
    c.setFillColor(primary)
    c.setFont("Helvetica-Bold", name_size)
    c.drawString(text_x, y + 0.64 * cm, entity["name"])

    # Tagline: one line when possible; otherwise wrap cleanly into two lines.
    tagline_size = 4.5
    tagline_lines = _wrap_text(entity["tagline"], "Helvetica", tagline_size, text_max_w)
    if len(tagline_lines) > 2:
        tagline_size = 4.1
        tagline_lines = _wrap_text(entity["tagline"], "Helvetica", tagline_size, text_max_w)
    tagline_lines = tagline_lines[:2]

    c.setFillColor(secondary)
    c.setFont("Helvetica", tagline_size)
    if len(tagline_lines) == 1:
        c.drawString(text_x, y + 0.31 * cm, tagline_lines[0])
    else:
        c.drawString(text_x, y + 0.35 * cm, tagline_lines[0])
        c.drawString(text_x, y + 0.14 * cm, tagline_lines[1])

    c.restoreState()
    _add_box(labels, "logo", x, y, w, h, entity_id=entity_id)
    return labels


def _draw_statement_footer(c, page_number: int = 1):
    c.setStrokeColor(LINE)
    c.setLineWidth(0.45)
    c.line(LEFT, 1.65 * cm, RIGHT, 1.65 * cm)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 5.9)
    c.drawString(LEFT, 1.30 * cm, "MUESTRA ACADÉMICA · DATOS FICTICIOS · SIN VALIDEZ LEGAL")
    c.drawRightString(RIGHT, 1.30 * cm, f"Página {page_number}")


def _draw_summary_card(c, x, y, w, h, label, value, *, prominent=False):
    c.saveState()
    c.setFillColor(ACCENT_LIGHT if prominent else colors.HexColor("#F8FAFC"))
    c.setStrokeColor(colors.HexColor("#D9E2EC"))
    c.roundRect(x, y - h, w, h, 6, stroke=1, fill=1)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.2)
    c.drawString(x + 0.20 * cm, y - 0.34 * cm, label)
    c.setFillColor(ACCENT if prominent else INK)
    c.setFont("Helvetica-Bold", 11.3 if prominent else 9.2)
    c.drawString(x + 0.20 * cm, y - 0.80 * cm, value)
    c.restoreState()


def _draw_statement_transactions(c, x, y, width, rows, *, digital=False):
    if digital:
        headers = ["Fecha", "Movimiento", "Categoría", "Importe"]
        ratios = [0.16, 0.44, 0.18, 0.22]
    else:
        headers = ["Fecha", "Descripción", "Canal", "Importe"]
        ratios = [0.16, 0.46, 0.18, 0.20]
    header_h, row_h = 0.66 * cm, 0.58 * cm
    xs = [x]
    for ratio in ratios[:-1]:
        xs.append(xs[-1] + width * ratio)
    col_ws = [width * r for r in ratios]

    c.saveState()
    c.setFillColor(ACCENT if not digital else colors.HexColor("#243B53"))
    for i, header in enumerate(headers):
        c.rect(xs[i], y - header_h, col_ws[i], header_h, stroke=0, fill=1)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 6.6)
        c.drawString(xs[i] + 0.12 * cm, y - 0.42 * cm, header)
        c.setFillColor(ACCENT if not digital else colors.HexColor("#243B53"))
    y -= header_h

    for idx, row in enumerate(rows):
        fill = WHITE if idx % 2 == 0 else colors.HexColor("#F7F9FC")
        values = [row["date"], row["description"], row["channel"]]
        amount_text = "—" if row["sign"] == 0 else (("+ " if row["sign"] > 0 else "- ") + _fmt_money(row["amount"]))
        values.append(amount_text)
        for i, value in enumerate(values):
            c.setFillColor(fill)
            c.setStrokeColor(colors.HexColor("#D8E0E8"))
            c.rect(xs[i], y - row_h, col_ws[i], row_h, stroke=1, fill=1)
            c.setFillColor(INK)
            c.setFont("Helvetica", 6.4)
            txt = str(value)
            maxw = col_ws[i] - 0.22 * cm
            while len(txt) > 6 and stringWidth(txt, "Helvetica", 6.4) > maxw:
                txt = txt[:-2]
            if txt != str(value):
                txt = txt.rstrip() + "…"
            if i == 3:
                c.drawRightString(xs[i] + col_ws[i] - 0.12 * cm, y - 0.42 * cm, txt)
            else:
                c.drawString(xs[i] + 0.12 * cm, y - 0.42 * cm, txt)
        y -= row_h
    c.restoreState()
    return y


def _statement_section_customer(c, data, payload, y, *, digital=False):
    if digital:
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 6.4)
        c.drawString(LEFT, y, f"Titular  {data['name']}")
        c.drawString(LEFT + 8.3 * cm, y, f"{payload['account_type']}  ·  {payload['masked_account']}")
        return y - 0.72 * cm

    c.setFillColor(ACCENT_LIGHT)
    c.setStrokeColor(colors.HexColor("#CCD8E5"))
    h = 2.05 * cm
    c.roundRect(LEFT, y - h, CONTENT_W, h, 5, stroke=1, fill=1)
    c.setFillColor(ACCENT)
    c.setFont("Helvetica-Bold", 7.6)
    c.drawString(LEFT + 0.24 * cm, y - 0.38 * cm, "INFORMACIÓN DE LA CUENTA")
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 7.2)
    c.drawString(LEFT + 0.24 * cm, y - 0.90 * cm, data["name"])
    c.setFont("Helvetica", 6.5)
    c.drawString(LEFT + 0.24 * cm, y - 1.34 * cm, f"DNI {data['dni']}")
    c.drawString(LEFT + 6.2 * cm, y - 0.90 * cm, payload["account_type"])
    c.drawString(LEFT + 6.2 * cm, y - 1.34 * cm, payload["masked_account"])
    c.drawRightString(RIGHT - 0.24 * cm, y - 0.90 * cm, f"Periodo {payload['period']}")
    c.drawRightString(RIGHT - 0.24 * cm, y - 1.34 * cm, f"Corte {payload['cutoff']}")
    return y - h - 0.45 * cm


def _statement_section_summary(c, payload, y, *, digital=False):
    gap = 0.25 * cm
    if digital:
        big_w = 6.35 * cm
        small_w = (CONTENT_W - big_w - 2 * gap) / 2
        h = 1.70 * cm
        _draw_summary_card(c, LEFT, y, big_w, h, "Saldo al cierre", _fmt_money(payload["final_balance"]), prominent=True)
        _draw_summary_card(c, LEFT + big_w + gap, y, small_w, h, "Abonos", _fmt_money(payload["credits"]))
        _draw_summary_card(c, LEFT + big_w + gap + small_w + gap, y, small_w, h, "Cargos", _fmt_money(payload["debits"]))
        return y - h - 0.50 * cm

    w = (CONTENT_W - 3 * gap) / 4
    h = 1.45 * cm
    cards = [
        ("Saldo anterior", _fmt_money(payload["opening_balance"]), False),
        ("Abonos", _fmt_money(payload["credits"]), False),
        ("Cargos", _fmt_money(payload["debits"]), False),
        ("Saldo final", _fmt_money(payload["final_balance"]), True),
    ]
    for idx, (label, value, prominent) in enumerate(cards):
        _draw_summary_card(c, LEFT + idx * (w + gap), y, w, h, label, value, prominent=prominent)
    return y - h - 0.50 * cm


def _statement_section_movements(c, payload, y, *, digital=False):
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 9.6)
    c.drawString(LEFT, y, "Actividad del periodo" if digital else "Detalle de movimientos")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.1)
    c.drawRightString(RIGHT, y, f"{len(payload['rows'])} movimientos")
    y -= 0.36 * cm
    return _draw_statement_transactions(c, LEFT, y, CONTENT_W, payload["rows"], digital=digital) - 0.42 * cm


def _render_estado_cuenta_tradicional(c, data, doc_code, doc_seed, entity_id, payload, *, reorder_blocks=False, reorder_seed=None):
    labels = []
    entity = ENTITY_PROFILES[entity_id]

    _draw_entity_mark_compact(c, entity_id, x=LEFT, y=PAGE_H - 2.48 * cm, labels=labels, dark=False)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 17)
    c.drawRightString(RIGHT, PAGE_H - 1.55 * cm, "ESTADO DE CUENTA")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.8)
    c.drawRightString(RIGHT, PAGE_H - 2.00 * cm, f"Estado N.° {payload['statement_number']}")
    c.drawRightString(RIGHT, PAGE_H - 2.34 * cm, f"Periodo {payload['period']}")
    if doc_code:
        c.drawString(LEFT, PAGE_H - 3.08 * cm, f"Código documental: {doc_code}")
    c.drawRightString(RIGHT, PAGE_H - 3.08 * cm, entity["name"])
    c.setStrokeColor(ACCENT)
    c.setLineWidth(1.0)
    c.line(LEFT, PAGE_H - 3.36 * cm, RIGHT, PAGE_H - 3.36 * cm)

    segments = ["customer", "summary", "movements"]
    if reorder_blocks:
        random.Random(reorder_seed).shuffle(segments)

    y = PAGE_H - 4.15 * cm
    for segment in segments:
        if segment == "customer":
            y = _statement_section_customer(c, data, payload, y, digital=False)
        elif segment == "summary":
            y = _statement_section_summary(c, payload, y, digital=False)
        else:
            y = _statement_section_movements(c, payload, y, digital=False)

    # Small, document-appropriate audit line instead of generic QR/stamp.
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 5.8)
    c.drawString(LEFT, 2.30 * cm, f"Documento de consulta · {payload['statement_number']} · Canal {data['branch']}")
    _statement_section_footer_note = "Los importes y datos corresponden exclusivamente a una muestra académica sintética."
    c.drawRightString(RIGHT, 2.30 * cm, _statement_section_footer_note)
    _draw_statement_footer(c, 1)
    return labels


def _render_estado_cuenta_digital(c, data, doc_code, doc_seed, entity_id, payload, *, reorder_blocks=False, reorder_seed=None):
    labels = []
    entity = ENTITY_PROFILES[entity_id]

    # Distinct digital/export composition: title first, compact identity on right.
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(LEFT, PAGE_H - 1.55 * cm, "Tu resumen del periodo")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.1)
    c.drawString(LEFT, PAGE_H - 2.00 * cm, f"Estado de cuenta · {payload['period']}")
    _draw_entity_mark_compact(c, entity_id, x=RIGHT - 4.15 * cm, y=PAGE_H - 2.52 * cm, labels=labels, dark=True)
    if doc_code:
        c.setFont("Helvetica", 5.9)
        c.drawString(LEFT, PAGE_H - 2.62 * cm, f"Referencia {doc_code}")
    c.setStrokeColor(colors.HexColor("#D7DEE7"))
    c.line(LEFT, PAGE_H - 3.08 * cm, RIGHT, PAGE_H - 3.08 * cm)

    segments = ["summary", "customer", "movements"]
    if reorder_blocks:
        random.Random(reorder_seed).shuffle(segments)

    y = PAGE_H - 3.82 * cm
    for segment in segments:
        if segment == "summary":
            y = _statement_section_summary(c, payload, y, digital=True)
        elif segment == "customer":
            y = _statement_section_customer(c, data, payload, y, digital=True)
        else:
            y = _statement_section_movements(c, payload, y, digital=True)

    # Minimal information band typical of a digital export.
    band_y = 2.08 * cm
    c.setFillColor(colors.HexColor("#F3F6F9"))
    c.roundRect(LEFT, band_y, CONTENT_W, 0.80 * cm, 5, stroke=0, fill=1)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 5.8)
    c.drawString(LEFT + 0.18 * cm, band_y + 0.29 * cm, f"Cuenta {_mask_account(data['account'])}  ·  Corte {payload['cutoff']}")
    c.drawRightString(RIGHT - 0.18 * cm, band_y + 0.29 * cm, f"{entity['name']} · exportación digital")
    _draw_statement_footer(c, 1)
    return labels


def render_estado_cuenta_specialized(
    data: dict,
    doc_code: str,
    output_path: str,
    doc_seed: int | None,
    entity_id: str,
    template_family: str,
    *,
    reorder_blocks: bool = False,
    reorder_seed: int | None = None,
) -> list:
    payload = _estado_cuenta_payload(data, doc_seed)
    c = canvas.Canvas(str(output_path), pagesize=A4, invariant=1)
    if template_family == "digital_resumen":
        labels = _render_estado_cuenta_digital(
            c, data, doc_code, doc_seed, entity_id, payload,
            reorder_blocks=reorder_blocks, reorder_seed=reorder_seed,
        )
    else:
        labels = _render_estado_cuenta_tradicional(
            c, data, doc_code, doc_seed, entity_id, payload,
            reorder_blocks=reorder_blocks, reorder_seed=reorder_seed,
        )
    c.save()
    return labels



# ---------------------------------------------------------------------------
# V4 Final — specialized renderers for the remaining document types
# ---------------------------------------------------------------------------

def _ordered_segments(segments, reorder_blocks=False, reorder_seed=None):
    result = list(segments)
    if reorder_blocks:
        random.Random(reorder_seed).shuffle(result)
    return result


def _special_footer(c, page_number=1, right_text=""):
    c.setStrokeColor(LINE)
    c.setLineWidth(0.45)
    c.line(LEFT, 1.58 * cm, RIGHT, 1.58 * cm)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 5.8)
    c.drawString(LEFT, 1.24 * cm, "MUESTRA ACADÉMICA · DATOS FICTICIOS · SIN VALIDEZ LEGAL")
    c.drawRightString(RIGHT, 1.24 * cm, right_text or f"Página {page_number}")


def _special_header(c, title, subtitle, doc_code, entity_id, *, compact=False, right_meta=None, labels=None):
    labels = labels if labels is not None else []
    entity = ENTITY_PROFILES[entity_id]
    if compact:
        _draw_entity_mark_compact(c, entity_id, x=LEFT, y=PAGE_H - 2.35 * cm, labels=labels, dark=False)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 15.5)
        c.drawRightString(RIGHT, PAGE_H - 1.48 * cm, title.upper())
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 6.6)
        c.drawRightString(RIGHT, PAGE_H - 1.92 * cm, subtitle)
        if right_meta:
            c.drawRightString(RIGHT, PAGE_H - 2.32 * cm, right_meta)
        c.drawString(LEFT, PAGE_H - 2.95 * cm, f"Código documental: {doc_code}")
        c.setStrokeColor(ACCENT)
        c.setLineWidth(0.9)
        c.line(LEFT, PAGE_H - 3.20 * cm, RIGHT, PAGE_H - 3.20 * cm)
        return PAGE_H - 3.85 * cm

    _draw_entity_mark_compact(c, entity_id, x=RIGHT - 4.15 * cm, y=PAGE_H - 2.40 * cm, labels=labels, dark=True)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(LEFT, PAGE_H - 1.48 * cm, title)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.8)
    c.drawString(LEFT, PAGE_H - 1.93 * cm, subtitle)
    c.drawString(LEFT, PAGE_H - 2.42 * cm, f"Referencia {doc_code}")
    if right_meta:
        c.drawRightString(RIGHT, PAGE_H - 2.90 * cm, right_meta)
    c.setStrokeColor(colors.HexColor("#D7DEE7"))
    c.line(LEFT, PAGE_H - 3.10 * cm, RIGHT, PAGE_H - 3.10 * cm)
    return PAGE_H - 3.78 * cm


def _panel(c, x, y, w, h, *, fill=SOFT, stroke=LINE, radius=5):
    c.saveState()
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.roundRect(x, y - h, w, h, radius, stroke=1, fill=1)
    c.restoreState()


def _label_value(c, x, y, label, value, *, label_w=3.4 * cm, size=7.0, value_bold=False):
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Bold", size - 0.3)
    c.drawString(x, y, str(label))
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold" if value_bold else "Helvetica", size)
    max_w = RIGHT - (x + label_w)
    txt = str(value)
    while len(txt) > 5 and stringWidth(txt, "Helvetica-Bold" if value_bold else "Helvetica", size) > max_w:
        txt = txt[:-2]
    if txt != str(value):
        txt = txt.rstrip() + "…"
    c.drawString(x + label_w, y, txt)


def _section_caption(c, y, text, *, accent=True):
    c.setFillColor(ACCENT if accent else INK)
    c.setFont("Helvetica-Bold", 8.7)
    c.drawString(LEFT, y, text)
    c.setStrokeColor(colors.HexColor("#D7DEE7"))
    c.line(LEFT, y - 0.18 * cm, RIGHT, y - 0.18 * cm)
    return y - 0.58 * cm


def _simple_grid_table(c, x, y, width, headers, rows, ratios=None, font_size=6.3, row_h=0.56*cm, header_h=0.62*cm):
    ratios = ratios or [1 / len(headers)] * len(headers)
    xs = [x]
    for r in ratios[:-1]:
        xs.append(xs[-1] + width * r)
    ws = [width * r for r in ratios]
    c.saveState()
    c.setFillColor(ACCENT)
    c.setStrokeColor(ACCENT)
    for i, header in enumerate(headers):
        c.rect(xs[i], y - header_h, ws[i], header_h, stroke=1, fill=1)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", font_size)
        c.drawString(xs[i] + 0.10*cm, y - 0.40*cm, str(header))
        c.setFillColor(ACCENT)
    y -= header_h
    for ri, row in enumerate(rows):
        fill = WHITE if ri % 2 == 0 else colors.HexColor("#F7F9FC")
        for i, val in enumerate(row):
            c.setFillColor(fill)
            c.setStrokeColor(colors.HexColor("#D8E0E8"))
            c.rect(xs[i], y - row_h, ws[i], row_h, stroke=1, fill=1)
            c.setFillColor(INK)
            c.setFont("Helvetica", font_size)
            txt = str(val)
            maxw = ws[i] - 0.20*cm
            while len(txt) > 5 and stringWidth(txt, "Helvetica", font_size) > maxw:
                txt = txt[:-2]
            if txt != str(val):
                txt = txt.rstrip() + "…"
            if i == len(row)-1 and any(ch.isdigit() for ch in txt):
                c.drawRightString(xs[i] + ws[i] - 0.10*cm, y - 0.38*cm, txt)
            else:
                c.drawString(xs[i] + 0.10*cm, y - 0.38*cm, txt)
        y -= row_h
    c.restoreState()
    return y


def _signature_pair(c, y, left_label, right_label=None):
    c.setStrokeColor(colors.HexColor("#98A2B3"))
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.0)
    if right_label:
        w=6.3*cm
        c.line(LEFT, y, LEFT+w, y)
        c.line(RIGHT-w, y, RIGHT, y)
        c.drawCentredString(LEFT+w/2, y-0.34*cm, left_label)
        c.drawCentredString(RIGHT-w/2, y-0.34*cm, right_label)
    else:
        w=6.3*cm
        x=LEFT+(CONTENT_W-w)/2
        c.line(x,y,x+w,y)
        c.drawCentredString(x+w/2,y-0.34*cm,left_label)
    return y-0.70*cm


# ---- Solicitud de Crédito -------------------------------------------------

def _solicitud_payload(data, doc_seed=None):
    rng=random.Random(_stable_visual_seed(doc_seed,"solicitud|payload"))
    amount=max(1500.0,_money_to_float(data.get("amount")))
    term=rng.choice([12,18,24,36,48,60])
    income=round(max(1800.0, amount/rng.uniform(7.5,15.0)),2)
    installment=round(amount/term*rng.uniform(1.04,1.18),2)
    return {
        "application_no":f"SC-{rng.randint(100000,999999)}",
        "product":rng.choice(["Préstamo Personal","Crédito Vehicular","Capital de Trabajo","Crédito de Libre Disponibilidad"]),
        "term":term,
        "income":income,
        "installment":installment,
        "purpose":rng.choice(["Consumo personal","Consolidación de obligaciones","Adquisición de activo","Capital de trabajo"]),
        "employment_months":rng.randint(8,96),
        "housing":rng.choice(["Propia","Alquilada","Familiar"]),
        "score":rng.randint(540,790),
    }


def _render_solicitud_formulario(c,data,doc_code,doc_seed,entity_id,payload,*,reorder_blocks=False,reorder_seed=None):
    labels=[]
    y=_special_header(c,"SOLICITUD DE CRÉDITO","Formulario de evaluación del solicitante",doc_code,entity_id,compact=True,right_meta=f"Solicitud {payload['application_no']}",labels=labels)
    segments=_ordered_segments(["personal","laboral","credito","declaracion"],reorder_blocks,reorder_seed)
    for seg in segments:
        if seg=="personal":
            y=_section_caption(c,y,"1. DATOS DEL SOLICITANTE")
            _panel(c,LEFT,y,CONTENT_W,2.15*cm,fill=colors.HexColor("#FAFBFC"))
            _label_value(c,LEFT+0.22*cm,y-0.48*cm,"Nombre",data["name"],label_w=2.3*cm,value_bold=True)
            _label_value(c,LEFT+0.22*cm,y-0.92*cm,"DNI",data["dni"],label_w=2.3*cm)
            _label_value(c,LEFT+8.0*cm,y-0.92*cm,"Teléfono",data["phone"],label_w=2.0*cm)
            _label_value(c,LEFT+0.22*cm,y-1.36*cm,"Correo",data["email"],label_w=2.3*cm)
            _label_value(c,LEFT+0.22*cm,y-1.80*cm,"Dirección",data["address"],label_w=2.3*cm)
            y-=2.55*cm
        elif seg=="laboral":
            y=_section_caption(c,y,"2. PERFIL LABORAL Y ECONÓMICO")
            rows=[["Ocupación",data["occupation"]],["Ingreso mensual",_fmt_money(payload["income"])],["Antigüedad laboral",f"{payload['employment_months']} meses"],["Vivienda",payload["housing"]]]
            y=_simple_grid_table(c,LEFT,y,CONTENT_W,["Dato","Declarado"],rows,[0.34,0.66],font_size=6.5,row_h=0.54*cm)-0.35*cm
        elif seg=="credito":
            y=_section_caption(c,y,"3. CONDICIONES SOLICITADAS")
            gap=0.22*cm; w=(CONTENT_W-gap)/2; h=1.35*cm
            for idx,(lab,val) in enumerate([("Producto",payload["product"]),("Monto",data["amount"]),("Plazo",f"{payload['term']} meses"),("Cuota referencial",_fmt_money(payload["installment"]))]):
                row=idx//2; col=idx%2; x=LEFT+col*(w+gap); yy=y-row*(h+gap)
                _panel(c,x,yy,w,h,fill=ACCENT_LIGHT if idx==1 else colors.HexColor("#F8FAFC"))
                c.setFillColor(MUTED); c.setFont("Helvetica",6.0); c.drawString(x+0.18*cm,yy-0.36*cm,lab)
                c.setFillColor(ACCENT if idx==1 else INK); c.setFont("Helvetica-Bold",8.0); c.drawString(x+0.18*cm,yy-0.85*cm,str(val)[:34])
            y-=2*(h+gap)+0.25*cm
        else:
            y=_section_caption(c,y,"4. DECLARACIÓN Y AUTORIZACIÓN")
            c.setFillColor(INK); c.setFont("Helvetica",6.7)
            lines=_wrap_text("Declaro que los datos consignados en esta muestra son ficticios y autorizo su uso exclusivamente para evaluación académica del sistema ForensiQ.","Helvetica",6.7,CONTENT_W)
            for ln in lines:
                c.drawString(LEFT,y,ln); y-=0.34*cm
            y-=0.35*cm
            y=_signature_pair(c,y,"Firma simulada del solicitante","Recepción / validación sintética")
    _special_footer(c,right_text=f"Solicitud {payload['application_no']}")
    return labels


def _render_solicitud_ejecutiva(c,data,doc_code,doc_seed,entity_id,payload,*,reorder_blocks=False,reorder_seed=None):
    labels=[]
    y=_special_header(c,"Evaluación de solicitud","Resumen ejecutivo para decisión crediticia",doc_code,entity_id,compact=False,right_meta=payload["application_no"],labels=labels)
    segments=_ordered_segments(["hero","perfil","decision","notas"],reorder_blocks,reorder_seed)
    for seg in segments:
        if seg=="hero":
            _panel(c,LEFT,y,CONTENT_W,2.25*cm,fill=colors.HexColor("#F4F7FB"),stroke=colors.HexColor("#D7E1ED"))
            c.setFillColor(MUTED); c.setFont("Helvetica",6.1); c.drawString(LEFT+0.25*cm,y-0.42*cm,"SOLICITANTE")
            c.setFillColor(INK); c.setFont("Helvetica-Bold",11.0); c.drawString(LEFT+0.25*cm,y-0.94*cm,data["name"])
            c.setFillColor(MUTED); c.setFont("Helvetica",6.4); c.drawString(LEFT+0.25*cm,y-1.38*cm,f"DNI {data['dni']} · {data['occupation']}")
            c.setFillColor(ACCENT); c.setFont("Helvetica-Bold",13.0); c.drawRightString(RIGHT-0.25*cm,y-0.78*cm,data["amount"])
            c.setFillColor(MUTED); c.setFont("Helvetica",6.0); c.drawRightString(RIGHT-0.25*cm,y-1.20*cm,f"{payload['product']} · {payload['term']} meses")
            y-=2.65*cm
        elif seg=="perfil":
            y=_section_caption(c,y,"Perfil económico")
            gap=.22*cm; w=(CONTENT_W-2*gap)/3; h=1.45*cm
            cards=[("Ingreso mensual",_fmt_money(payload["income"])),("Cuota estimada",_fmt_money(payload["installment"])),("Score sintético",str(payload["score"]))]
            for i,(lab,val) in enumerate(cards):
                x=LEFT+i*(w+gap); _panel(c,x,y,w,h,fill=WHITE)
                c.setFillColor(MUTED);c.setFont("Helvetica",6.0);c.drawString(x+.18*cm,y-.36*cm,lab)
                c.setFillColor(INK);c.setFont("Helvetica-Bold",9.5);c.drawString(x+.18*cm,y-.87*cm,val)
            y-=h+.45*cm
        elif seg=="decision":
            y=_section_caption(c,y,"Resumen de evaluación")
            rows=[["Destino",payload["purpose"]],["Vivienda",payload["housing"]],["Antigüedad",f"{payload['employment_months']} meses"],["Riesgo declarado",data["risk_level"]],["Canal",data["branch"]]]
            y=_simple_grid_table(c,LEFT,y,CONTENT_W,["Variable","Resultado"],rows,[.38,.62],font_size=6.6,row_h=.56*cm)-.4*cm
        else:
            _panel(c,LEFT,y,CONTENT_W,1.35*cm,fill=colors.HexColor("#FFFDF6"),stroke=colors.HexColor("#E9E1C7"))
            c.setFillColor(INK);c.setFont("Helvetica",6.6)
            msg="La información y el resultado mostrados son simulados. Este documento no constituye aprobación, oferta ni decisión crediticia real."
            for i,ln in enumerate(_wrap_text(msg,"Helvetica",6.6,CONTENT_W-.5*cm)):
                c.drawString(LEFT+.25*cm,y-.45*cm-i*.34*cm,ln)
            y-=1.75*cm
    _special_footer(c,right_text=f"Evaluación {payload['application_no']}")
    return labels


def render_solicitud_credito_specialized(data,doc_code,output_path,doc_seed,entity_id,template_family,**kwargs):
    payload=_solicitud_payload(data,doc_seed); c=canvas.Canvas(str(output_path),pagesize=A4,invariant=1)
    if template_family=="evaluacion_ejecutiva": labels=_render_solicitud_ejecutiva(c,data,doc_code,doc_seed,entity_id,payload,**kwargs)
    else: labels=_render_solicitud_formulario(c,data,doc_code,doc_seed,entity_id,payload,**kwargs)
    c.save(); return labels


# ---- Contrato Financiero --------------------------------------------------

def _contrato_payload(data,doc_seed=None):
    rng=random.Random(_stable_visual_seed(doc_seed,"contrato|payload")); amount=max(1200,_money_to_float(data.get("amount")))
    return {"contract_no":f"CF-{rng.randint(100000,999999)}","term":rng.choice([12,24,36,48]),"annual_rate":round(rng.uniform(8.5,24.5),2),"payment_day":rng.randint(5,28),"product":rng.choice(["Financiamiento personal","Línea de crédito","Crédito comercial"]),"amount":amount}


def _contract_clauses(data,p):
    return [
        ("PRIMERA · OBJETO",f"La entidad sintética registra un {p['product'].lower()} por un monto referencial de {_fmt_money(p['amount'])}."),
        ("SEGUNDA · PLAZO",f"El plazo simulado es de {p['term']} meses y la fecha de pago referencial corresponde al día {p['payment_day']} de cada mes."),
        ("TERCERA · TASA REFERENCIAL",f"Para efectos exclusivamente académicos se consigna una tasa anual sintética de {p['annual_rate']:.2f} %."),
        ("CUARTA · OBLIGACIONES",f"El cliente sintético {data['name']} declara haber revisado las condiciones y datos ficticios consignados en esta muestra."),
        ("QUINTA · TRATAMIENTO DE DATOS","Los datos personales contenidos son generados artificialmente y se emplean únicamente para pruebas de comparación documental."),
        ("SEXTA · VALIDEZ","El presente instrumento carece de validez jurídica, comercial o financiera y no representa a una institución real."),
    ]


def _render_contrato_institucional(c,data,doc_code,doc_seed,entity_id,p,*,reorder_blocks=False,reorder_seed=None):
    labels=[]; y=_special_header(c,"CONTRATO FINANCIERO","Instrumento contractual sintético",doc_code,entity_id,compact=True,right_meta=f"Contrato {p['contract_no']}",labels=labels)
    _panel(c,LEFT,y,CONTENT_W,1.65*cm,fill=colors.HexColor("#FAFBFC"))
    _label_value(c,LEFT+.22*cm,y-.47*cm,"Cliente",data["name"],label_w=2.0*cm,value_bold=True)
    _label_value(c,LEFT+.22*cm,y-.92*cm,"DNI",data["dni"],label_w=2.0*cm)
    _label_value(c,LEFT+8.0*cm,y-.92*cm,"Monto",_fmt_money(p["amount"]),label_w=1.7*cm,value_bold=True)
    _label_value(c,LEFT+.22*cm,y-1.35*cm,"Cuenta",_mask_account(data["account"]),label_w=2.0*cm)
    y-=2.05*cm
    clauses=_contract_clauses(data,p)
    order=list(range(len(clauses)))
    if reorder_blocks: random.Random(reorder_seed).shuffle(order)
    for idx in order:
        title,body=clauses[idx]
        c.setFillColor(ACCENT);c.setFont("Helvetica-Bold",7.1);c.drawString(LEFT,y,title)
        y-=.34*cm;c.setFillColor(INK);c.setFont("Helvetica",6.45)
        for ln in _wrap_text(body,"Helvetica",6.45,CONTENT_W): c.drawString(LEFT,y,ln); y-=.31*cm
        y-=.18*cm
    y-=.2*cm; _signature_pair(c,y,"Cliente sintético","Representante de la entidad sintética")
    _special_footer(c,right_text=p["contract_no"]); return labels


def _render_contrato_compacto(c,data,doc_code,doc_seed,entity_id,p,*,reorder_blocks=False,reorder_seed=None):
    labels=[]; y=_special_header(c,"Acuerdo de financiamiento","Resumen contractual",doc_code,entity_id,compact=False,right_meta=p["contract_no"],labels=labels)
    _panel(c,LEFT,y,CONTENT_W,2.00*cm,fill=ACCENT_LIGHT,stroke=colors.HexColor("#C7D5E3"))
    c.setFillColor(MUTED);c.setFont("Helvetica",6.0);c.drawString(LEFT+.22*cm,y-.38*cm,"TITULAR")
    c.setFillColor(INK);c.setFont("Helvetica-Bold",9.5);c.drawString(LEFT+.22*cm,y-.85*cm,data["name"])
    c.setFont("Helvetica",6.5);c.drawString(LEFT+.22*cm,y-1.28*cm,f"DNI {data['dni']} · {_mask_account(data['account'])}")
    c.setFillColor(ACCENT);c.setFont("Helvetica-Bold",12.5);c.drawRightString(RIGHT-.22*cm,y-.75*cm,_fmt_money(p["amount"]))
    c.setFillColor(MUTED);c.setFont("Helvetica",6.1);c.drawRightString(RIGHT-.22*cm,y-1.20*cm,f"{p['term']} meses · {p['annual_rate']:.2f}% anual")
    y-=2.45*cm
    clauses=_contract_clauses(data,p)
    order=list(range(len(clauses)))
    if reorder_blocks: random.Random(reorder_seed).shuffle(order)
    for idx in order:
        title,body=clauses[idx]
        _panel(c,LEFT,y,CONTENT_W,1.20*cm,fill=WHITE)
        c.setFillColor(INK);c.setFont("Helvetica-Bold",6.7);c.drawString(LEFT+.18*cm,y-.34*cm,title.replace(" · "," — "))
        c.setFillColor(MUTED);c.setFont("Helvetica",6.0)
        lines=_wrap_text(body,"Helvetica",6.0,CONTENT_W-.36*cm)[:2]
        for i,ln in enumerate(lines):c.drawString(LEFT+.18*cm,y-.68*cm-i*.27*cm,ln)
        y-=1.38*cm
    _signature_pair(c,y-.1*cm,"Aceptación del cliente","Validación sintética")
    _special_footer(c,right_text=p["contract_no"]); return labels


def render_contrato_financiero_specialized(data,doc_code,output_path,doc_seed,entity_id,template_family,**kwargs):
    p=_contrato_payload(data,doc_seed); c=canvas.Canvas(str(output_path),pagesize=A4,invariant=1)
    labels=_render_contrato_compacto(c,data,doc_code,doc_seed,entity_id,p,**kwargs) if template_family=="compacto" else _render_contrato_institucional(c,data,doc_code,doc_seed,entity_id,p,**kwargs)
    c.save(); return labels


# ---- Ficha KYC ------------------------------------------------------------

def _kyc_payload(data,doc_seed=None):
    rng=random.Random(_stable_visual_seed(doc_seed,"kyc|payload"))
    return {"kyc_no":f"KYC-{rng.randint(100000,999999)}","source":rng.choice(["Remuneración","Actividad comercial","Servicios profesionales","Ahorros"]),"pep":rng.choice(["No identificado","No declarado"]),"expected":rng.choice(["S/ 2,000 – 8,000","S/ 8,000 – 20,000","S/ 20,000 – 50,000"]),"products":rng.choice(["Cuenta de ahorros","Cuenta + tarjeta","Cuenta empresarial"]),"verification":rng.choice(["Completa","Revisión documental completa"]),"review_date":"30/09/2026"}


def _render_kyc_expediente(c,data,doc_code,doc_seed,entity_id,p,*,reorder_blocks=False,reorder_seed=None):
    labels=[];y=_special_header(c,"FICHA DE CONOCIMIENTO DEL CLIENTE","Expediente de debida diligencia sintético",doc_code,entity_id,compact=True,right_meta=p["kyc_no"],labels=labels)
    segments=_ordered_segments(["identidad","actividad","perfil","control"],reorder_blocks,reorder_seed)
    for seg in segments:
        if seg=="identidad":
            y=_section_caption(c,y,"A. IDENTIFICACIÓN")
            rows=[["Nombre completo",data["name"]],["Documento",data["dni"]],["RUC",data["ruc"]],["Dirección",data["address"]],["Contacto",f"{data['phone']} · {data['email']}"]]
            y=_simple_grid_table(c,LEFT,y,CONTENT_W,["Campo","Información declarada"],rows,[.30,.70],font_size=6.35,row_h=.53*cm)-.33*cm
        elif seg=="actividad":
            y=_section_caption(c,y,"B. ACTIVIDAD ECONÓMICA")
            rows=[["Ocupación",data["occupation"]],["Origen de fondos",p["source"]],["Productos",p["products"]]]
            y=_simple_grid_table(c,LEFT,y,CONTENT_W,["Variable","Detalle"],rows,[.30,.70],font_size=6.35,row_h=.53*cm)-.33*cm
        elif seg=="perfil":
            y=_section_caption(c,y,"C. PERFIL TRANSACCIONAL")
            gap=.22*cm;w=(CONTENT_W-2*gap)/3;h=1.35*cm
            for i,(lab,val) in enumerate([("Rango esperado",p["expected"]),("Nivel de riesgo",data["risk_level"]),("PEP",p["pep"])]):
                x=LEFT+i*(w+gap);_panel(c,x,y,w,h,fill=ACCENT_LIGHT if i==1 else colors.HexColor("#F8FAFC"));c.setFillColor(MUTED);c.setFont("Helvetica",5.9);c.drawString(x+.17*cm,y-.36*cm,lab);c.setFillColor(INK);c.setFont("Helvetica-Bold",7.7);c.drawString(x+.17*cm,y-.82*cm,str(val)[:27])
            y-=1.75*cm
        else:
            y=_section_caption(c,y,"D. CONTROL Y REVISIÓN")
            _panel(c,LEFT,y,CONTENT_W,1.45*cm,fill=colors.HexColor("#F8FAFC"));_label_value(c,LEFT+.22*cm,y-.48*cm,"Verificación",p["verification"],label_w=2.5*cm,value_bold=True);_label_value(c,LEFT+.22*cm,y-.94*cm,"Próxima revisión",p["review_date"],label_w=2.5*cm);y-=1.85*cm
    _special_footer(c,right_text=p["kyc_no"]);return labels


def _render_kyc_dashboard(c,data,doc_code,doc_seed,entity_id,p,*,reorder_blocks=False,reorder_seed=None):
    labels=[];y=_special_header(c,"Perfil KYC","Vista resumida de cumplimiento",doc_code,entity_id,compact=False,right_meta=p["kyc_no"],labels=labels)
    _panel(c,LEFT,y,CONTENT_W,2.15*cm,fill=colors.HexColor("#F4F7FB"))
    c.setFillColor(INK);c.setFont("Helvetica-Bold",11);c.drawString(LEFT+.24*cm,y-.58*cm,data["name"])
    c.setFillColor(MUTED);c.setFont("Helvetica",6.3);c.drawString(LEFT+.24*cm,y-1.02*cm,f"DNI {data['dni']} · {data['occupation']}");c.drawString(LEFT+.24*cm,y-1.43*cm,data["address"])
    c.setFillColor(ACCENT);c.setFont("Helvetica-Bold",12);c.drawRightString(RIGHT-.24*cm,y-.70*cm,data["risk_level"].upper());c.setFillColor(MUTED);c.setFont("Helvetica",5.9);c.drawRightString(RIGHT-.24*cm,y-1.10*cm,"RIESGO DECLARADO")
    y-=2.55*cm
    segments=_ordered_segments(["cards","identity","review"],reorder_blocks,reorder_seed)
    for seg in segments:
        if seg=="cards":
            gap=.22*cm;w=(CONTENT_W-2*gap)/3;h=1.5*cm
            for i,(lab,val) in enumerate([("Origen de fondos",p["source"]),("Transaccionalidad",p["expected"]),("Condición PEP",p["pep"])]):
                x=LEFT+i*(w+gap);_panel(c,x,y,w,h,fill=WHITE);c.setFillColor(MUTED);c.setFont("Helvetica",5.8);c.drawString(x+.16*cm,y-.36*cm,lab);c.setFillColor(INK);c.setFont("Helvetica-Bold",7.4);c.drawString(x+.16*cm,y-.86*cm,str(val)[:25])
            y-=1.90*cm
        elif seg=="identity":
            y=_section_caption(c,y,"Información vinculada")
            rows=[["RUC",data["ruc"]],["Teléfono",data["phone"]],["Correo",data["email"]],["Producto",p["products"]]]
            y=_simple_grid_table(c,LEFT,y,CONTENT_W,["Dato","Valor"],rows,[.27,.73],font_size=6.4,row_h=.54*cm)-.4*cm
        else:
            _panel(c,LEFT,y,CONTENT_W,1.45*cm,fill=ACCENT_LIGHT,stroke=colors.HexColor("#CAD8E6"));c.setFillColor(ACCENT);c.setFont("Helvetica-Bold",7);c.drawString(LEFT+.22*cm,y-.45*cm,"ESTADO DE REVISIÓN");c.setFillColor(INK);c.setFont("Helvetica",6.5);c.drawString(LEFT+.22*cm,y-.90*cm,f"{p['verification']} · Próxima revisión: {p['review_date']}");y-=1.85*cm
    _special_footer(c,right_text=p["kyc_no"]);return labels


def render_ficha_kyc_specialized(data,doc_code,output_path,doc_seed,entity_id,template_family,**kwargs):
    p=_kyc_payload(data,doc_seed);c=canvas.Canvas(str(output_path),pagesize=A4,invariant=1)
    labels=_render_kyc_dashboard(c,data,doc_code,doc_seed,entity_id,p,**kwargs) if template_family=="dashboard_perfil" else _render_kyc_expediente(c,data,doc_code,doc_seed,entity_id,p,**kwargs)
    c.save();return labels


# ---- Comprobante de Operación --------------------------------------------

def _comprobante_payload(data,doc_seed=None):
    rng=random.Random(_stable_visual_seed(doc_seed,"comprobante|payload")); amt=max(20,_money_to_float(data.get("amount")));fee=round(rng.uniform(0,12.5),2)
    dest="".join(str(rng.randint(0,9)) for _ in range(10))
    return {"time":f"{rng.randint(8,21):02d}:{rng.randint(0,59):02d}:{rng.randint(0,59):02d}","destination":f"•••• {dest[-4:]}","recipient":rng.choice(["Comercio sintético","Beneficiario de prueba","Cuenta destino simulada"]),"fee":fee,"total":amt+fee,"status":"OPERACIÓN REGISTRADA","reference":f"REF-{rng.randint(10000000,99999999)}"}


def _render_comprobante_voucher(c,data,doc_code,doc_seed,entity_id,p,*,reorder_blocks=False,reorder_seed=None):
    labels=[]
    # Narrow receipt centered on A4.
    receipt_w=11.6*cm;x=(PAGE_W-receipt_w)/2;y=PAGE_H-1.55*cm
    _panel(c,x,y,receipt_w,24.0*cm,fill=WHITE,stroke=colors.HexColor("#C8D0DA"),radius=8)
    _draw_entity_mark_compact(c,entity_id,x=x+.45*cm,y=y-1.35*cm,labels=labels,dark=False)
    c.setFillColor(ACCENT);c.setFont("Helvetica-Bold",8.5);c.drawRightString(x+receipt_w-.45*cm,y-.72*cm,"COMPROBANTE")
    c.setFillColor(MUTED);c.setFont("Helvetica",5.8);c.drawRightString(x+receipt_w-.45*cm,y-1.08*cm,doc_code)
    yy=y-2.30*cm;c.setFillColor(MUTED);c.setFont("Helvetica",6.0);c.drawCentredString(x+receipt_w/2,yy,"MONTO DE LA OPERACIÓN");c.setFillColor(INK);c.setFont("Helvetica-Bold",18);c.drawCentredString(x+receipt_w/2,yy-.70*cm,data["amount"]);yy-=1.35*cm
    c.setStrokeColor(colors.HexColor("#D7DEE7"));c.line(x+.45*cm,yy,x+receipt_w-.45*cm,yy);yy-=.55*cm
    items=[("Estado",p["status"]),("Código",data["operation_code"]),("Fecha",data["date"]),("Hora",p["time"]),("Titular",data["name"]),("Cuenta origen",_mask_account(data["account"])),("Destino",p["destination"]),("Beneficiario",p["recipient"]),("Canal",data["branch"]),("Comisión",_fmt_money(p["fee"])),("Total",_fmt_money(p["total"])),("Referencia",p["reference"])]
    if reorder_blocks:
        head=items[:2];tail=items[2:];random.Random(reorder_seed).shuffle(tail);items=head+tail
    for lab,val in items:
        c.setFillColor(MUTED);c.setFont("Helvetica",6.0);c.drawString(x+.55*cm,yy,lab);c.setFillColor(INK);c.setFont("Helvetica-Bold" if lab in {"Estado","Total"} else "Helvetica",6.5);c.drawRightString(x+receipt_w-.55*cm,yy,str(val)[:42]);yy-=.55*cm
    c.setFillColor(colors.HexColor("#F4F7FB"));c.roundRect(x+.45*cm,yy-.95*cm,receipt_w-.9*cm,.95*cm,5,stroke=0,fill=1);c.setFillColor(MUTED);c.setFont("Helvetica",5.7);c.drawCentredString(x+receipt_w/2,yy-.55*cm,"Conserva esta referencia para fines de la simulación académica")
    _special_footer(c,right_text=p["reference"]);return labels


def _render_comprobante_digital(c,data,doc_code,doc_seed,entity_id,p,*,reorder_blocks=False,reorder_seed=None):
    labels=[];y=_special_header(c,"Operación completada","Confirmación digital de movimiento",doc_code,entity_id,compact=False,right_meta=p["reference"],labels=labels)
    _panel(c,LEFT,y,CONTENT_W,2.55*cm,fill=ACCENT_LIGHT,stroke=colors.HexColor("#CAD8E6"));c.setFillColor(ACCENT);c.setFont("Helvetica-Bold",7);c.drawString(LEFT+.25*cm,y-.48*cm,p["status"]);c.setFillColor(INK);c.setFont("Helvetica-Bold",17);c.drawString(LEFT+.25*cm,y-1.20*cm,data["amount"]);c.setFillColor(MUTED);c.setFont("Helvetica",6.3);c.drawString(LEFT+.25*cm,y-1.70*cm,f"{data['date']} · {p['time']} · {data['branch']}");c.drawRightString(RIGHT-.25*cm,y-1.18*cm,p["recipient"]);c.drawRightString(RIGHT-.25*cm,y-1.65*cm,p["destination"]);y-=2.95*cm
    segments=_ordered_segments(["route","cost","reference"],reorder_blocks,reorder_seed)
    for seg in segments:
        if seg=="route":
            y=_section_caption(c,y,"Origen y destino");rows=[["Titular",data["name"]],["Cuenta origen",_mask_account(data["account"])],["Destino",p["destination"]],["Beneficiario",p["recipient"]]];y=_simple_grid_table(c,LEFT,y,CONTENT_W,["Dato","Detalle"],rows,[.30,.70],font_size=6.5,row_h=.55*cm)-.35*cm
        elif seg=="cost":
            y=_section_caption(c,y,"Detalle económico");gap=.22*cm;w=(CONTENT_W-gap)/2;h=1.35*cm
            for i,(lab,val) in enumerate([("Comisión",_fmt_money(p["fee"])),("Total debitado",_fmt_money(p["total"]))]):x=LEFT+i*(w+gap);_panel(c,x,y,w,h,fill=WHITE);c.setFillColor(MUTED);c.setFont("Helvetica",6);c.drawString(x+.18*cm,y-.36*cm,lab);c.setFillColor(INK);c.setFont("Helvetica-Bold",9);c.drawString(x+.18*cm,y-.85*cm,val)
            y-=1.75*cm
        else:
            _panel(c,LEFT,y,CONTENT_W,1.10*cm,fill=colors.HexColor("#F7F9FC"));c.setFillColor(MUTED);c.setFont("Helvetica",6.1);c.drawString(LEFT+.18*cm,y-.42*cm,"Código de operación");c.setFillColor(INK);c.setFont("Helvetica-Bold",7);c.drawString(LEFT+4.0*cm,y-.42*cm,data["operation_code"]);c.setFillColor(MUTED);c.setFont("Helvetica",6.1);c.drawRightString(RIGHT-.18*cm,y-.42*cm,p["reference"]);y-=1.5*cm
    _special_footer(c,right_text=p["reference"]);return labels


def render_comprobante_operacion_specialized(data,doc_code,output_path,doc_seed,entity_id,template_family,**kwargs):
    p=_comprobante_payload(data,doc_seed);c=canvas.Canvas(str(output_path),pagesize=A4,invariant=1)
    labels=_render_comprobante_voucher(c,data,doc_code,doc_seed,entity_id,p,**kwargs) if template_family=="voucher" else _render_comprobante_digital(c,data,doc_code,doc_seed,entity_id,p,**kwargs);c.save();return labels


# ---- Reporte de Transacción ----------------------------------------------

def _reporte_payload(data,doc_seed=None):
    rng=random.Random(_stable_visual_seed(doc_seed,"reporte|payload"));rows=[]
    for i in range(8):
        sign=rng.choice([-1,-1,-1,1]);amt=round(rng.uniform(90,7800),2);rows.append([f"{rng.randint(1,28):02d}/08/2026",rng.choice(["Transferencia","Compra","Retiro","Abono","Pago"]),rng.choice(["Web","App","POS","ATM","Agencia"]),("+ " if sign>0 else "- ")+_fmt_money(amt),rng.choice(["Normal","Revisar","Normal","Normal"])])
    return {"report_no":f"RT-{rng.randint(100000,999999)}","rows":rows,"total":len(rows),"alerts":sum(1 for r in rows if r[-1]=="Revisar"),"window":"01/08/2026 – 31/08/2026","generated":"16/09/2026 09:30"}


def _render_reporte_auditoria(c,data,doc_code,doc_seed,entity_id,p,*,reorder_blocks=False,reorder_seed=None):
    labels=[];y=_special_header(c,"REPORTE DE TRANSACCIONES","Documento de auditoría y revisión operativa",doc_code,entity_id,compact=True,right_meta=p["report_no"],labels=labels)
    segments=_ordered_segments(["scope","table","findings"],reorder_blocks,reorder_seed)
    for seg in segments:
        if seg=="scope":
            _panel(c,LEFT,y,CONTENT_W,1.55*cm,fill=colors.HexColor("#F8FAFC"));_label_value(c,LEFT+.22*cm,y-.46*cm,"Cliente",data["name"],label_w=2.2*cm,value_bold=True);_label_value(c,LEFT+.22*cm,y-.90*cm,"Cuenta",_mask_account(data["account"]),label_w=2.2*cm);_label_value(c,LEFT+8.4*cm,y-.90*cm,"Ventana",p["window"],label_w=1.8*cm);y-=1.95*cm
        elif seg=="table":
            y=_section_caption(c,y,"Detalle transaccional");y=_simple_grid_table(c,LEFT,y,CONTENT_W,["Fecha","Tipo","Canal","Importe","Control"],p["rows"],[.15,.24,.16,.23,.22],font_size=5.9,row_h=.52*cm)-.38*cm
        else:
            y=_section_caption(c,y,"Hallazgos de control");gap=.22*cm;w=(CONTENT_W-2*gap)/3;h=1.32*cm
            for i,(lab,val) in enumerate([("Operaciones",str(p["total"])),("Alertas",str(p["alerts"])),("Riesgo del perfil",data["risk_level"])]):x=LEFT+i*(w+gap);_panel(c,x,y,w,h,fill=ACCENT_LIGHT if i==1 else WHITE);c.setFillColor(MUTED);c.setFont("Helvetica",5.9);c.drawString(x+.17*cm,y-.35*cm,lab);c.setFillColor(INK);c.setFont("Helvetica-Bold",9);c.drawString(x+.17*cm,y-.82*cm,val)
            y-=1.72*cm
    _special_footer(c,right_text=f"Generado {p['generated']}");return labels


def _render_reporte_monitoreo(c,data,doc_code,doc_seed,entity_id,p,*,reorder_blocks=False,reorder_seed=None):
    labels=[];y=_special_header(c,"Monitor transaccional","Resumen de actividad y señales",doc_code,entity_id,compact=False,right_meta=p["report_no"],labels=labels)
    _panel(c,LEFT,y,CONTENT_W,1.75*cm,fill=colors.HexColor("#F4F7FB"));c.setFillColor(INK);c.setFont("Helvetica-Bold",10);c.drawString(LEFT+.22*cm,y-.58*cm,data["name"]);c.setFillColor(MUTED);c.setFont("Helvetica",6.2);c.drawString(LEFT+.22*cm,y-1.02*cm,f"{_mask_account(data['account'])} · {p['window']}");c.setFillColor(ACCENT);c.setFont("Helvetica-Bold",12);c.drawRightString(RIGHT-.22*cm,y-.62*cm,f"{p['alerts']} alerta(s)");c.setFillColor(MUTED);c.setFont("Helvetica",5.8);c.drawRightString(RIGHT-.22*cm,y-1.02*cm,"SEÑALES PARA REVISIÓN");y-=2.18*cm
    segments=_ordered_segments(["metrics","table","note"],reorder_blocks,reorder_seed)
    for seg in segments:
        if seg=="metrics":
            gap=.22*cm;w=(CONTENT_W-2*gap)/3;h=1.28*cm
            for i,(lab,val) in enumerate([("Movimientos",str(p["total"])),("Canal principal",data["branch"]),("Riesgo",data["risk_level"])]):x=LEFT+i*(w+gap);_panel(c,x,y,w,h,fill=WHITE);c.setFillColor(MUTED);c.setFont("Helvetica",5.8);c.drawString(x+.16*cm,y-.34*cm,lab);c.setFillColor(INK);c.setFont("Helvetica-Bold",7.8);c.drawString(x+.16*cm,y-.79*cm,str(val)[:25]);y_dummy=0
            y-=1.65*cm
        elif seg=="table":
            y=_section_caption(c,y,"Actividad reciente");y=_simple_grid_table(c,LEFT,y,CONTENT_W,["Fecha","Movimiento","Canal","Monto","Señal"],p["rows"],[.15,.25,.15,.23,.22],font_size=5.9,row_h=.51*cm)-.35*cm
        else:
            _panel(c,LEFT,y,CONTENT_W,1.10*cm,fill=colors.HexColor("#FFFDF6"),stroke=colors.HexColor("#E9E1C7"));c.setFillColor(INK);c.setFont("Helvetica",6.1);c.drawString(LEFT+.18*cm,y-.45*cm,"Las señales mostradas son sintéticas y sirven únicamente para orientar la revisión documental del experimento.");y-=1.5*cm
    _special_footer(c,right_text=p["report_no"]);return labels


def render_reporte_transaccion_specialized(data,doc_code,output_path,doc_seed,entity_id,template_family,**kwargs):
    p=_reporte_payload(data,doc_seed);c=canvas.Canvas(str(output_path),pagesize=A4,invariant=1)
    labels=_render_reporte_monitoreo(c,data,doc_code,doc_seed,entity_id,p,**kwargs) if template_family=="monitoreo" else _render_reporte_auditoria(c,data,doc_code,doc_seed,entity_id,p,**kwargs);c.save();return labels


# ---- Carta de Cobranza ----------------------------------------------------

def _cobranza_payload(data,doc_seed=None):
    rng=random.Random(_stable_visual_seed(doc_seed,"cobranza|payload"));amt=max(300,_money_to_float(data.get("amount")))
    return {"case_no":f"CB-{rng.randint(100000,999999)}","days":rng.randint(12,95),"due":"30/09/2026","installment":round(amt*rng.uniform(.18,.45),2),"contact":"Área de Soluciones de Pago","schedule":"Lun–Vie 09:00–18:00"}


def _render_cobranza_carta(c,data,doc_code,doc_seed,entity_id,p,*,reorder_blocks=False,reorder_seed=None):
    labels=[]; entity=ENTITY_PROFILES[entity_id]
    _draw_entity_mark_compact(c,entity_id,x=LEFT,y=PAGE_H-2.35*cm,labels=labels,dark=False)
    c.setFillColor(MUTED);c.setFont("Helvetica",6.2);c.drawRightString(RIGHT,PAGE_H-1.52*cm,"Lima, 16 de septiembre de 2026");c.drawRightString(RIGHT,PAGE_H-1.93*cm,f"Caso {p['case_no']}")
    y=PAGE_H-3.25*cm;c.setFillColor(INK);c.setFont("Helvetica-Bold",8.5);c.drawString(LEFT,y,"Señor(a)");y-=.44*cm;c.setFont("Helvetica-Bold",10);c.drawString(LEFT,y,data["name"]);y-=.42*cm;c.setFont("Helvetica",6.5);c.drawString(LEFT,y,data["address"]);y-=.80*cm
    c.setFont("Helvetica-Bold",8.5);c.drawString(LEFT,y,"Asunto: Regularización de obligación referencial");y-=.72*cm
    paragraphs=[f"Estimado(a) señor(a) {data['name']}:",f"De acuerdo con los datos sintéticos del expediente, se registra una obligación referencial con {p['days']} días de atraso. El saldo simulado asociado asciende a {data['amount']}.",f"Para fines de esta muestra se propone regularizar un importe referencial de {_fmt_money(p['installment'])} hasta el {p['due']}. Esta comunicación no constituye una exigencia de pago real.",f"Para consultas dentro del escenario experimental, el canal asignado es {p['contact']} ({p['schedule']})."]
    order=list(range(len(paragraphs)));
    if reorder_blocks: random.Random(reorder_seed).shuffle(order)
    for idx in order:
        c.setFillColor(INK);c.setFont("Helvetica",7.1)
        for ln in _wrap_text(paragraphs[idx],"Helvetica",7.1,CONTENT_W):c.drawString(LEFT,y,ln);y-=.38*cm
        y-=.30*cm
    _panel(c,LEFT,y,CONTENT_W,1.55*cm,fill=colors.HexColor("#FFF9F4"),stroke=colors.HexColor("#E8D7C8"));c.setFillColor(MUTED);c.setFont("Helvetica",6);c.drawString(LEFT+.22*cm,y-.40*cm,"SALDO REFERENCIAL");c.setFillColor(INK);c.setFont("Helvetica-Bold",11);c.drawString(LEFT+.22*cm,y-.95*cm,data["amount"]);c.setFillColor(MUTED);c.setFont("Helvetica",6);c.drawRightString(RIGHT-.22*cm,y-.48*cm,f"Caso {p['case_no']}");y-=2.2*cm
    c.setFillColor(INK);c.setFont("Helvetica",7);c.drawString(LEFT,y,"Atentamente,");y-=.55*cm;c.setFont("Helvetica-Bold",7.2);c.drawString(LEFT,y,p["contact"]);c.setFont("Helvetica",6.2);c.setFillColor(MUTED);c.drawString(LEFT,y-.36*cm,entity["name"])
    _special_footer(c,right_text=doc_code);return labels


def _render_cobranza_notificacion(c,data,doc_code,doc_seed,entity_id,p,*,reorder_blocks=False,reorder_seed=None):
    labels=[];y=_special_header(c,"Aviso de regularización","Notificación administrativa de seguimiento",doc_code,entity_id,compact=False,right_meta=p["case_no"],labels=labels)
    _panel(c,LEFT,y,CONTENT_W,2.25*cm,fill=colors.HexColor("#FFF8F3"),stroke=colors.HexColor("#E8D6C8"));c.setFillColor(MUTED);c.setFont("Helvetica",6);c.drawString(LEFT+.23*cm,y-.40*cm,"SALDO REFERENCIAL");c.setFillColor(INK);c.setFont("Helvetica-Bold",16);c.drawString(LEFT+.23*cm,y-1.10*cm,data["amount"]);c.setFillColor(MUTED);c.setFont("Helvetica",6.3);c.drawString(LEFT+.23*cm,y-1.62*cm,f"{p['days']} días de atraso sintético");c.setFillColor(ACCENT);c.setFont("Helvetica-Bold",9);c.drawRightString(RIGHT-.23*cm,y-.85*cm,f"Vence {p['due']}");y-=2.70*cm
    segments=_ordered_segments(["person","proposal","contact"],reorder_blocks,reorder_seed)
    for seg in segments:
        if seg=="person":
            y=_section_caption(c,y,"Datos del expediente");rows=[["Cliente",data["name"]],["DNI",data["dni"]],["Código",p["case_no"]]];y=_simple_grid_table(c,LEFT,y,CONTENT_W,["Dato","Valor"],rows,[.28,.72],font_size=6.5,row_h=.55*cm)-.35*cm
        elif seg=="proposal":
            y=_section_caption(c,y,"Propuesta referencial");_panel(c,LEFT,y,CONTENT_W,1.35*cm,fill=ACCENT_LIGHT);c.setFillColor(MUTED);c.setFont("Helvetica",6);c.drawString(LEFT+.20*cm,y-.38*cm,"Importe de regularización");c.setFillColor(ACCENT);c.setFont("Helvetica-Bold",10);c.drawString(LEFT+.20*cm,y-.88*cm,_fmt_money(p["installment"]));c.setFillColor(MUTED);c.setFont("Helvetica",6);c.drawRightString(RIGHT-.20*cm,y-.65*cm,"Escenario académico · sin obligación real");y-=1.75*cm
        else:
            y=_section_caption(c,y,"Canal de atención");c.setFillColor(INK);c.setFont("Helvetica-Bold",7.4);c.drawString(LEFT,y,p["contact"]);c.setFillColor(MUTED);c.setFont("Helvetica",6.3);c.drawString(LEFT,y-.42*cm,f"Horario: {p['schedule']} · {data['phone']} · {data['email']}");y-=1.15*cm
    _special_footer(c,right_text=p["case_no"]);return labels


def render_carta_cobranza_specialized(data,doc_code,output_path,doc_seed,entity_id,template_family,**kwargs):
    p=_cobranza_payload(data,doc_seed);c=canvas.Canvas(str(output_path),pagesize=A4,invariant=1)
    labels=_render_cobranza_notificacion(c,data,doc_code,doc_seed,entity_id,p,**kwargs) if template_family=="notificacion_administrativa" else _render_cobranza_carta(c,data,doc_code,doc_seed,entity_id,p,**kwargs);c.save();return labels


# ---- Constancia Bancaria --------------------------------------------------

def _constancia_payload(data,doc_seed=None):
    rng=random.Random(_stable_visual_seed(doc_seed,"constancia|payload"))
    return {"cert_no":f"CT-{rng.randint(100000,999999)}","account_type":rng.choice(["Cuenta de Ahorros","Cuenta Corriente","Cuenta Digital"]),"opened":f"{rng.randint(1,28):02d}/{rng.randint(1,12):02d}/{rng.randint(2018,2025)}","purpose":rng.choice(["Trámite administrativo","Acreditación académica","Verificación documental"]),"issued":"16 de septiembre de 2026"}


def _render_constancia_institucional(c,data,doc_code,doc_seed,entity_id,p,*,reorder_blocks=False,reorder_seed=None):
    labels=[];_draw_entity_mark_compact(c,entity_id,x=LEFT,y=PAGE_H-2.35*cm,labels=labels,dark=False);c.setFillColor(MUTED);c.setFont("Helvetica",6);c.drawRightString(RIGHT,PAGE_H-1.55*cm,f"Constancia N.° {p['cert_no']}");c.drawRightString(RIGHT,PAGE_H-1.94*cm,"Lima, "+p["issued"])
    y=PAGE_H-4.15*cm;c.setFillColor(INK);c.setFont("Helvetica-Bold",15);c.drawCentredString(PAGE_W/2,y,"CONSTANCIA BANCARIA");y-=1.10*cm
    body=["A QUIEN CORRESPONDA:",f"Por medio de la presente, se deja constancia de que {data['name']}, identificado(a) con DNI {data['dni']}, mantiene registrada una {p['account_type'].lower()} en el escenario financiero sintético de esta investigación.",f"La cuenta de referencia corresponde a {_mask_account(data['account'])} y registra como fecha de apertura simulada el {p['opened']}.",f"La presente constancia se emite a solicitud del interesado para fines de {p['purpose'].lower()}."]
    order=list(range(1,len(body)))
    if reorder_blocks: random.Random(reorder_seed).shuffle(order)
    c.setFont("Helvetica-Bold",7.8);c.drawString(LEFT,y,body[0]);y-=.70*cm
    for idx in order:
        c.setFillColor(INK);c.setFont("Helvetica",7.4)
        for ln in _wrap_text(body[idx],"Helvetica",7.4,CONTENT_W):c.drawString(LEFT,y,ln);y-=.42*cm
        y-=.35*cm
    y-=.5*cm;_signature_pair(c,y,"Firma autorizada simulada")
    _special_footer(c,right_text=p["cert_no"]);return labels


def _render_constancia_minimalista(c,data,doc_code,doc_seed,entity_id,p,*,reorder_blocks=False,reorder_seed=None):
    labels=[];y=_special_header(c,"Constancia","Acreditación sintética de relación financiera",doc_code,entity_id,compact=False,right_meta=p["cert_no"],labels=labels)
    _panel(c,LEFT,y,CONTENT_W,2.00*cm,fill=colors.HexColor("#F7F9FC"));c.setFillColor(MUTED);c.setFont("Helvetica",6);c.drawString(LEFT+.24*cm,y-.42*cm,"TITULAR");c.setFillColor(INK);c.setFont("Helvetica-Bold",11);c.drawString(LEFT+.24*cm,y-.95*cm,data["name"]);c.setFillColor(MUTED);c.setFont("Helvetica",6.3);c.drawString(LEFT+.24*cm,y-1.40*cm,f"DNI {data['dni']} · {p['account_type']}");c.setFillColor(ACCENT);c.setFont("Helvetica-Bold",9);c.drawRightString(RIGHT-.24*cm,y-.85*cm,_mask_account(data["account"]));y-=2.60*cm
    segments=_ordered_segments(["statement","facts","close"],reorder_blocks,reorder_seed)
    for seg in segments:
        if seg=="statement":
            c.setFillColor(INK);c.setFont("Helvetica",7.4);msg="Se certifica, exclusivamente para el escenario académico de ForensiQ, que los datos indicados figuran en el corpus financiero sintético utilizado para evaluación experimental."
            for ln in _wrap_text(msg,"Helvetica",7.4,CONTENT_W):c.drawString(LEFT,y,ln);y-=.42*cm
            y-=.45*cm
        elif seg=="facts":
            rows=[["Fecha de apertura",p["opened"]],["Fecha de emisión",p["issued"]],["Finalidad",p["purpose"]],["Canal asociado",data["branch"]]];y=_simple_grid_table(c,LEFT,y,CONTENT_W,["Dato","Constancia"],rows,[.34,.66],font_size=6.5,row_h=.56*cm)-.5*cm
        else:
            _panel(c,LEFT,y,CONTENT_W,1.20*cm,fill=ACCENT_LIGHT);c.setFillColor(ACCENT);c.setFont("Helvetica-Bold",7);c.drawString(LEFT+.20*cm,y-.43*cm,"DOCUMENTO DE MUESTRA");c.setFillColor(INK);c.setFont("Helvetica",6.3);c.drawRightString(RIGHT-.20*cm,y-.43*cm,"Sin validez bancaria, legal o comercial");y-=1.65*cm
    _signature_pair(c,y,"Validación sintética")
    _special_footer(c,right_text=p["cert_no"]);return labels


def render_constancia_bancaria_specialized(data,doc_code,output_path,doc_seed,entity_id,template_family,**kwargs):
    p=_constancia_payload(data,doc_seed);c=canvas.Canvas(str(output_path),pagesize=A4,invariant=1)
    labels=_render_constancia_minimalista(c,data,doc_code,doc_seed,entity_id,p,**kwargs) if template_family=="minimalista" else _render_constancia_institucional(c,data,doc_code,doc_seed,entity_id,p,**kwargs);c.save();return labels


SPECIALIZED_RENDERERS = {
    "estado_cuenta": render_estado_cuenta_specialized,
    "solicitud_credito": render_solicitud_credito_specialized,
    "contrato_financiero": render_contrato_financiero_specialized,
    "ficha_kyc": render_ficha_kyc_specialized,
    "comprobante_operacion": render_comprobante_operacion_specialized,
    "reporte_transaccion": render_reporte_transaccion_specialized,
    "carta_cobranza": render_carta_cobranza_specialized,
    "constancia_bancaria": render_constancia_bancaria_specialized,
}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_document_from_data(
    data: dict,
    document_type: str,
    doc_code: str,
    output_path: str,
    doc_seed: int | None = None,
    reorder_blocks: bool = False,
    reorder_seed: int | None = None,
    entity_id: str | None = None,
    template_family: str | None = None,
) -> None:
    if doc_seed is not None:
        random.seed(doc_seed)

    entity_id = entity_id or _select_entity_id(doc_seed, document_type)
    template_family = template_family or _select_template_family(doc_seed, document_type)

    if document_type in SPECIALIZED_RENDERERS:
        output_path = str(output_path)
        labels = SPECIALIZED_RENDERERS[document_type](
            data, doc_code, output_path, doc_seed, entity_id, template_family,
            reorder_blocks=reorder_blocks, reorder_seed=reorder_seed,
        )
        try:
            sidecar = Path(output_path).with_suffix(".visual.json")
            sidecar.write_text(
                json.dumps({
                    "document_type": document_type,
                    "doc_seed": doc_seed,
                    "style_id": _style_id(doc_seed, document_type),
                    "entity_id": entity_id,
                    "template_family": template_family,
                    "labels": labels,
                    "note": "Synthetic visual labels for research; not a real financial document.",
                    "visual_version": "v4-final",
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
        return

    blocks = build_document_blocks(data, document_type)
    if reorder_blocks:
        groups = _group_blocks(blocks)
        rng = random.Random(reorder_seed)
        rng.shuffle(groups)
        blocks = [b for group in groups for b in group]

    output_path = str(output_path)
    c = canvas.Canvas(output_path, pagesize=A4, invariant=1)
    all_labels = []
    page_number = 1

    def begin_page() -> float:
        nonlocal page_number
        if page_number > 1:
            draw_footer(c, page_number - 1)
            c.showPage()
        page_labels = []
        draw_header(c, TITLES.get(document_type, "Documento financiero"), doc_code, document_type, doc_seed, page_labels, entity_id, template_family)
        visual_labels = draw_visual_security_features(c, document_type, doc_seed)
        for item in page_labels + visual_labels:
            item = dict(item)
            item["page"] = page_number
            all_labels.append(item)
        page_number += 1
        return BODY_TOP

    y = begin_page()
    y = render_blocks(c, blocks, y, new_page_callback=begin_page)
    draw_footer(c, page_number - 1)
    c.save()

    try:
        sidecar = Path(output_path).with_suffix(".visual.json")
        sidecar.write_text(
            json.dumps({
                "document_type": document_type,
                "doc_seed": doc_seed,
                "style_id": _style_id(doc_seed, document_type),
                "entity_id": entity_id,
                "template_family": template_family,
                "labels": all_labels,
                "note": "Synthetic visual labels for research; not a real financial document.",
                "visual_version": "v4-stage1",
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Ground-truth metadata and corpus generation
# ---------------------------------------------------------------------------

def _metadata_path_for(pdf_path: str | Path) -> Path:
    p = Path(pdf_path)
    return p.parent / (p.stem + ".meta.json")


def load_document_metadata(pdf_path: str | Path) -> dict | None:
    meta_path = _metadata_path_for(pdf_path)
    if not meta_path.exists():
        return None
    with meta_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def generate_single_pdf(
    index: int,
    *,
    code_prefix: str = "DOC",
    output_dir: Path | None = None,
    document_role: str = "legitimate",
) -> dict:
    target_dir = Path(output_dir) if output_dir is not None else OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    document_type = DOCUMENT_TYPES[(index - 1) % len(DOCUMENT_TYPES)]
    namespace = "distractor" if document_role == "distractor" else "legitimate"
    data = build_person_data(identifier_namespace=namespace)
    doc_code = f"{code_prefix}-{index:04d}"

    # Deterministic suffix: unlike uuid4(), this preserves full corpus reproducibility
    # when the global seed is fixed.
    suffix = f"{randint(0, 0xFFFFFFFF):08x}"
    filename = f"{doc_code}_{document_type}_{suffix}.pdf"
    output_path = target_dir / filename

    doc_seed = randint(0, 2_147_483_647)
    entity_id = _select_entity_id(doc_seed, document_type)
    template_family = _select_template_family(doc_seed, document_type)
    rng_state = random.getstate()
    render_document_from_data(
        data, document_type, doc_code, str(output_path), doc_seed,
        entity_id=entity_id, template_family=template_family,
    )
    random.setstate(rng_state)

    metadata = {
        "document_id": filename,
        "filename": filename,
        "path": str(output_path),
        "document_type": document_type,
        "doc_code": doc_code,
        "document_role": document_role,
        "doc_seed": doc_seed,
        "entity_id": entity_id,
        "entity_name": ENTITY_PROFILES[entity_id]["name"],
        "template_family": template_family,
        "layout_variant": _style_id(doc_seed, document_type),
        "visual_version": "v4-final",
        "data": data,
    }
    with _metadata_path_for(output_path).open("w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    return metadata


def generate_synthetic_pdfs(
    n: int = 10,
    *,
    seed: int | None = None,
    start_index: int = 1,
    code_prefix: str = "DOC",
    output_dir: Path | None = None,
    document_role: str = "legitimate",
    locale: str = DEFAULT_LOCALE,
) -> list[dict]:
    if seed is not None:
        set_global_seed(seed, locale=locale)

    return [
        generate_single_pdf(
            start_index + offset,
            code_prefix=code_prefix,
            output_dir=output_dir,
            document_role=document_role,
        )
        for offset in range(n)
    ]


def generate_distractor_pdfs(
    n: int,
    *,
    seed: int | None = None,
    start_index: int = 1,
    locale: str = DEFAULT_LOCALE,
) -> list[dict]:
    if seed is not None:
        set_global_seed(seed + DISTRACTOR_SEED_OFFSET, locale=locale)

    return [
        generate_single_pdf(
            start_index + offset,
            code_prefix="DIST",
            output_dir=DISTRACTOR_OUTPUT_DIR,
            document_role="distractor",
        )
        for offset in range(n)
    ]
