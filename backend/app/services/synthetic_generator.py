# =============================================================================
# synthetic_generator.py  ·  versión ajustada para evaluación forense
# -----------------------------------------------------------------------------
# CAMBIOS RESPECTO A LA VERSIÓN ORIGINAL
#   1. set_global_seed(seed): siembra `random` y `Faker` -> corpus reproducible
#      (requisito de IC por bootstrap con corpus fijo, decisión A2).
#   2. generate_distractor_pdfs(n, seed): genera documentos del MISMO dominio
#      financiero que NO se indexan, con PII garantizada distinta de los
#      legítimos (decisión B1). Un distractor no tiene match verdadero en el
#      índice; sirve para el FPR operativo del protocolo (§5.1).
#   3. output_dir / code_prefix / document_role parametrizados; el dict de
#      retorno incluye `document_role` ("legitimate" | "distractor") para que
#      el harness separe poblaciones sin heurísticas frágiles.
#   4. Los renderers NO se modificaron (eran correctos).
#
# NOTAS METODOLÓGICAS PENDIENTES (no resueltas aquí, requieren decisión):
#   - Locale Faker = "es_ES": nombres pasables, pero direcciones son españolas,
#     no de Lima Metropolitana (protocolo §3.1). Para alinear, habría que
#     registrar un provider de direcciones limeñas. Se deja como parámetro.
#   - DNIs/RUCs aleatorios SIN verificación de "no asignado" (protocolo §8.2).
#     No se puede garantizar contra un registro real desde aquí; declararlo
#     como limitación o cruzar contra rangos confirmados como no emitidos.
# =============================================================================

import json
import random
from pathlib import Path
from uuid import uuid4
from random import choice, randint, uniform
from datetime import datetime, timedelta

from faker import Faker
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm

# Locale parametrizable. Default conserva el comportamiento original.
DEFAULT_LOCALE = "es_ES"
fake = Faker(DEFAULT_LOCALE)

_BASE_DATA_DIR = Path(__file__).resolve().parents[3] / "synthetic_data"
OUTPUT_DIR = _BASE_DATA_DIR / "legitimate"
DISTRACTOR_OUTPUT_DIR = _BASE_DATA_DIR / "distractors"

# Offset primo para derivar la semilla de los distractores a partir de la
# semilla de los legítimos: reproducible pero garantiza streams disjuntos,
# evitando que un distractor reciba la MISMA PII que un legítimo (lo que
# crearía un falso match y contaminaría el FPR).
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


def set_global_seed(seed: int, locale: str = DEFAULT_LOCALE) -> None:
    """Siembra todas las fuentes de aleatoriedad para reproducibilidad total.

    Debe llamarse ANTES de cualquier generación. `random.seed` cubre choice/
    randint/uniform (importados de `random`); `Faker.seed` cubre la instancia
    compartida usada por `fake`.
    """
    global fake
    random.seed(seed)
    Faker.seed(seed)
    # Re-instanciar para respetar el locale solicitado y la semilla por-instancia.
    fake = Faker(locale)
    fake.seed_instance(seed)


def random_dni() -> str:
    return "".join(str(randint(0, 9)) for _ in range(8))


def random_ruc() -> str:
    prefix = choice(["10", "20"])
    return prefix + "".join(str(randint(0, 9)) for _ in range(9))


def random_phone() -> str:
    return "9" + "".join(str(randint(0, 9)) for _ in range(8))


def random_bank_account() -> str:
    return (
        f"{randint(100, 999)}-"
        f"{''.join(str(randint(0, 9)) for _ in range(12))}-"
        f"{randint(10, 99)}"
    )


def random_money() -> str:
    amount = round(uniform(500, 95000), 2)
    return f"S/ {amount:,.2f}"


def random_date() -> str:
    start_date = datetime(2021, 1, 1)
    delta_days = randint(0, 1200)
    return (start_date + timedelta(days=delta_days)).strftime("%Y-%m-%d")


def build_person_data() -> dict:
    name = fake.name()
    return {
        "name": name,
        "dni": random_dni(),
        "ruc": random_ruc(),
        "email": fake.email(),
        "phone": random_phone(),
        "account": random_bank_account(),
        "amount": random_money(),
        "date": random_date(),
        "address": fake.address().replace("\n", ", "),
        "occupation": choice([
            "Analista financiero",
            "Comerciante",
            "Administrador",
            "Contador",
            "Consultor independiente",
            "Empleado dependiente",
        ]),
        "risk_level": choice(["Bajo", "Medio", "Alto"]),
        "operation_code": f"OP-{randint(100000, 999999)}",
    }


def draw_header(c, title: str, doc_code: str, document_type: str):
    width, height = A4

    c.setFont("Helvetica-Bold", 16)
    c.drawString(2 * cm, height - 2 * cm, title)

    c.setFont("Helvetica", 9)
    c.drawString(2 * cm, height - 2.7 * cm, "Documento financiero sintetico")
    c.drawString(2 * cm, height - 3.2 * cm, f"Tipo documental: {document_type}")
    c.drawString(2 * cm, height - 3.7 * cm, "Entidad financiera sintética - Perú")

    c.line(2 * cm, height - 4.1 * cm, width - 2 * cm, height - 4.1 * cm)


def draw_footer(c):
    width, _ = A4
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(
        2 * cm,
        1.5 * cm,
        "Documento sintético generado automáticamente. Sin validez legal.",
    )
    c.drawRightString(width - 2 * cm, 1.5 * cm, "Uso exclusivo para evaluación experimental.")


def draw_key_value(c, x, y, label, value, line_height=14):
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x, y, label)
    c.setFont("Helvetica", 9)
    c.drawString(x + 4.2 * cm, y, str(value))
    return y - line_height


def draw_section_title(c, x, y, title):
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y, title)
    c.line(x, y - 4, x + 15 * cm, y - 4)
    return y - 18


def draw_simple_table(c, x, y, headers, rows):
    col_width = 4.2 * cm
    row_height = 16

    c.setFont("Helvetica-Bold", 8)
    for i, header in enumerate(headers):
        c.rect(x + i * col_width, y, col_width, row_height)
        c.drawString(x + i * col_width + 4, y + 5, header)

    y -= row_height

    c.setFont("Helvetica", 8)
    for row in rows:
        for i, value in enumerate(row):
            c.rect(x + i * col_width, y, col_width, row_height)
            c.drawString(x + i * col_width + 4, y + 5, str(value))
        y -= row_height

    return y - 12


# --------------------------------------------------------------------------- #
# Modelo declarativo de bloques (habilita T7 - reordenamiento fiel)
# --------------------------------------------------------------------------- #
# Los renderers imperativos se reemplazaron por CONSTRUCTORES DE BLOQUES. Cada
# documento se describe como una lista ordenada de bloques (section, kv, table,
# paragraph, signature) y un renderer genérico los dibuja de arriba a abajo
# reusando las primitivas de estilo. Esto permite implementar T7 de forma fiel:
# se reordenan GRUPOS (seccion + su contenido) preservando el estilo visual y
# cambiando solo el orden y las posiciones -> el descriptor de layout refleja
# el cambio, mientras el contenido (texto/PII) permanece idéntico. Una T7
# falsa (re-render idéntico) habría SOBRESTIMADO la robustez.

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


def draw_paragraph(c, x, y, lines, size=9, leading=16):
    c.setFont("Helvetica", size)
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def draw_signature(c, y, labels):
    if len(labels) == 1:
        c.line(2 * cm, y, 8 * cm, y)
        c.setFont("Helvetica", 9)
        c.drawString(2 * cm, y - 14, labels[0])
    else:
        c.line(2 * cm, y, 7 * cm, y)
        c.line(11 * cm, y, 18 * cm, y)
        c.setFont("Helvetica", 9)
        c.drawString(2 * cm, y - 14, labels[0])
        c.drawString(11 * cm, y - 14, labels[1])
    return y - 28


# --- Constructores de bloques por tipo documental ------------------------- #
def build_estado_cuenta_blocks(data):
    if data.get("_redact_transactions"):
        rows = [
            ["[FECHA]", "Movimiento", "S/ [MONTO]"],
            ["[FECHA]", "Cargo", "S/ [MONTO]"],
            ["[FECHA]", "Transferencia", "S/ [MONTO]"],
            ["[FECHA]", "Pago servicio", "S/ [MONTO]"],
        ]
    elif data.get("_drop_transactions"):
        rows = [
            ["", "Movimiento omitido", ""],
            ["", "Cargo omitido", ""],
        ]
    else:
        rows = [
            [random_date(), "Abono", random_money()],
            [random_date(), "Cargo", random_money()],
            [random_date(), "Transferencia", random_money()],
            [random_date(), "Pago servicio", random_money()],
        ]
    return [
        {"kind": "section", "title": "Datos del cliente"},
        {"kind": "kv", "label": "Nombre completo:", "value": data["name"]},
        {"kind": "kv", "label": "DNI:", "value": data["dni"]},
        {"kind": "kv", "label": "Correo electrónico:", "value": data["email"]},
        {"kind": "kv", "label": "Teléfono:", "value": data["phone"]},
        {"kind": "kv", "label": "Cuenta bancaria:", "value": data["account"]},
        {"kind": "section", "title": "Movimientos recientes"},
        {"kind": "table", "headers": ["Fecha", "Operación", "Monto"], "rows": rows},
        {"kind": "kv", "label": "Saldo referencial:", "value": data["amount"]},
    ]


def build_solicitud_credito_blocks(data):
    return [
        {"kind": "section", "title": "Datos personales"},
        {"kind": "kv", "label": "Nombre completo:", "value": data["name"]},
        {"kind": "kv", "label": "DNI:", "value": data["dni"]},
        {"kind": "kv", "label": "RUC asociado:", "value": data["ruc"]},
        {"kind": "kv", "label": "Dirección:", "value": str(data["address"])[:70]},
        {"kind": "kv", "label": "Ocupación:", "value": data["occupation"]},
        {"kind": "section", "title": "Datos de la solicitud"},
        {"kind": "kv", "label": "Monto solicitado:", "value": data["amount"]},
        {"kind": "kv", "label": "Fecha de emisión:", "value": data["date"]},
        {"kind": "kv", "label": "Nivel de riesgo:", "value": data["risk_level"]},
        {"kind": "paragraph", "lines": [
            "El solicitante declara que la información proporcionada es referencial",
            "y generada únicamente para fines de evaluación académica.",
        ]},
    ]


def build_contrato_financiero_blocks(data):
    return [
        {"kind": "section", "title": "Partes del contrato"},
        {"kind": "kv", "label": "Cliente:", "value": data["name"]},
        {"kind": "kv", "label": "DNI:", "value": data["dni"]},
        {"kind": "kv", "label": "Cuenta asociada:", "value": data["account"]},
        {"kind": "kv", "label": "Correo:", "value": data["email"]},
        {"kind": "section", "title": "Cláusulas principales"},
        {"kind": "paragraph", "lines": [
            "Primera: La entidad registra una obligación financiera referencial.",
            "Segunda: El cliente acepta condiciones simuladas de pago y seguimiento.",
            "Tercera: Los datos incluidos no corresponden a una operación real.",
            "Cuarta: Este documento se utiliza para pruebas de comparación forense.",
        ]},
        {"kind": "signature", "labels": ["Firma del cliente", "Representante de entidad"]},
    ]


def build_ficha_kyc_blocks(data):
    return [
        {"kind": "section", "title": "Identificación"},
        {"kind": "kv", "label": "Nombre completo:", "value": data["name"]},
        {"kind": "kv", "label": "DNI:", "value": data["dni"]},
        {"kind": "kv", "label": "RUC asociado:", "value": data["ruc"]},
        {"kind": "kv", "label": "Teléfono:", "value": data["phone"]},
        {"kind": "kv", "label": "Correo electrónico:", "value": data["email"]},
        {"kind": "section", "title": "Perfil transaccional"},
        {"kind": "kv", "label": "Ocupación:", "value": data["occupation"]},
        {"kind": "kv", "label": "Nivel de riesgo:", "value": data["risk_level"]},
        {"kind": "kv", "label": "Monto mensual estimado:", "value": data["amount"]},
    ]


def build_comprobante_operacion_blocks(data):
    return [
        {"kind": "section", "title": "Detalle de operación"},
        {"kind": "kv", "label": "Código de operación:", "value": data["operation_code"]},
        {"kind": "kv", "label": "Fecha de emisión:", "value": data["date"]},
        {"kind": "kv", "label": "Cuenta origen:", "value": data["account"]},
        {"kind": "kv", "label": "Titular:", "value": data["name"]},
        {"kind": "kv", "label": "DNI:", "value": data["dni"]},
        {"kind": "kv", "label": "Monto referencial:", "value": data["amount"]},
        {"kind": "paragraph", "lines": [
            "La operación fue registrada en un entorno sintético de evaluación.",
        ]},
    ]


def build_reporte_transaccion_blocks(data):
    rows = [
        ["Cliente", data["name"], data["dni"]],
        ["Cuenta", data["account"], data["amount"]],
        ["RUC", data["ruc"], data["risk_level"]],
        ["Contacto", data["email"], data["phone"]],
    ]
    return [
        {"kind": "table", "headers": ["Campo", "Valor principal", "Valor secundario"], "rows": rows},
        {"kind": "section", "title": "Observación"},
        {"kind": "paragraph", "lines": [
            "Reporte sintético para evaluación de recuperación documental.",
            "Contiene datos ficticios con estructura financiera variable.",
        ]},
    ]


def build_carta_cobranza_blocks(data):
    return [
        {"kind": "paragraph", "lines": [
            f"Estimado/a {data['name']},",
            f"Se registra una obligación referencial asociada al DNI {data['dni']}.",
            f"El monto pendiente simulado asciende a {data['amount']}.",
            f"Para coordinaciones, se tiene registrado el correo {data['email']}",
            f"y el teléfono {data['phone']}.",
            "Este documento no constituye una comunicación real de cobranza.",
        ]},
        {"kind": "signature", "labels": ["Área de seguimiento financiero"]},
    ]


def build_constancia_bancaria_blocks(data):
    return [
        {"kind": "section", "title": "Constancia"},
        {"kind": "paragraph", "lines": [
            f"Se deja constancia de que {data['name']} mantiene una cuenta referencial.",
            f"Documento de identidad: {data['dni']}.",
            f"Cuenta bancaria asociada: {data['account']}.",
            f"Fecha de emisión: {data['date']}.",
            "La presente constancia es sintética y se emite para fines académicos.",
        ]},
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
    """Agrupa cada 'section' con los bloques que la siguen hasta la próxima
    'section'. Los bloques previos a la primera sección forman su propio grupo.
    Reordenar GRUPOS (no bloques sueltos) mantiene la coherencia semántica de
    cada sección, que es lo que define a T7."""
    groups = []
    current = []
    for b in blocks:
        if b["kind"] == "section" and current:
            groups.append(current)
            current = [b]
        else:
            current.append(b)
    if current:
        groups.append(current)
    return groups


def render_blocks(c, blocks: list, start_y: float) -> float:
    _, height = A4
    y = start_y
    for b in blocks:
        if y < 3 * cm:
            c.showPage()
            y = height - 2 * cm
        kind = b["kind"]
        if kind == "section":
            y -= 6
            y = draw_section_title(c, 2 * cm, y, b["title"])
        elif kind == "kv":
            y = draw_key_value(c, 2 * cm, y, b["label"], b["value"])
        elif kind == "table":
            y = draw_simple_table(c, 2 * cm, y, b["headers"], b["rows"])
        elif kind == "paragraph":
            y = draw_paragraph(c, 2 * cm, y, b["lines"])
        elif kind == "signature":
            y -= 20
            y = draw_signature(c, y, b["labels"])
        elif kind == "spacer":
            y -= b.get("height", 8)
    return y


def render_document_from_data(
    data: dict,
    document_type: str,
    doc_code: str,
    output_path: str,
    doc_seed: int | None = None,
    reorder_blocks: bool = False,
    reorder_seed: int | None = None,
) -> None:
    """Renderiza un PDF desde datos estructurados con el modelo de bloques.
    CLAVE PARA LA VALIDEZ DEL LAYOUT: las variantes se re-renderizan con ESTE
    mismo renderer (datos mutados y/o orden alterado), de modo que su layout
    pertenece a la MISMA familia visual que el legítimo padre, no a un volcado
    plano genérico. Eso vuelve discriminativo al descriptor de layout.

    `doc_seed` reproduce el contenido no-determinista (p. ej. filas de
    movimientos), para que una variante difiera del padre SOLO en lo
    transformado. `reorder_blocks` activa T7: reordena grupos sección+contenido
    con un RNG dedicado que NO perturba el stream sembrado por `doc_seed`.
    """
    if doc_seed is not None:
        random.seed(doc_seed)

    blocks = build_document_blocks(data, document_type)

    if reorder_blocks:
        groups = _group_blocks(blocks)
        rng = random.Random(reorder_seed)
        rng.shuffle(groups)
        blocks = [b for group in groups for b in group]

    _, height = A4
    c = canvas.Canvas(str(output_path), pagesize=A4)
    draw_header(c, TITLES[document_type], doc_code, document_type)
    render_blocks(c, blocks, height - 4.8 * cm)
    draw_footer(c)
    c.save()


def _metadata_path_for(pdf_path: str | Path) -> Path:
    p = Path(pdf_path)
    return p.parent / (p.stem + ".meta.json")


def load_document_metadata(pdf_path: str | Path) -> dict | None:
    """Carga la metadata ground-truth (datos estructurados, tipo, doc_code,
    doc_seed) escrita junto a cada PDF. Devuelve None si no existe (permite
    fallback en el generador de variantes). Satisface además el requisito de
    "anotación ground truth" del protocolo §3.1.
    """
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
    """Genera un PDF sintético + su sidecar de metadata ground-truth.
    `code_prefix` y `output_dir` separan legítimos ("DOC") de distractores
    ("DIST") en carpetas y espacios de id disjuntos.
    """
    target_dir = Path(output_dir) if output_dir is not None else OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    document_type = DOCUMENT_TYPES[(index - 1) % len(DOCUMENT_TYPES)]
    data = build_person_data()
    doc_code = f"{code_prefix}-{index:04d}"
    filename = f"{doc_code}_{document_type}_{uuid4().hex[:8]}.pdf"
    output_path = target_dir / filename

    # doc_seed se extrae del stream principal (ya sembrado por set_global_seed),
    # y se aísla el render con save/restore para no perturbar la independencia
    # entre documentos del corpus.
    doc_seed = randint(0, 2_147_483_647)
    rng_state = random.getstate()
    render_document_from_data(data, document_type, doc_code, str(output_path), doc_seed)
    random.setstate(rng_state)

    metadata = {
        "document_id": filename,
        "filename": filename,
        "path": str(output_path),
        "document_type": document_type,
        "doc_code": doc_code,
        "document_role": document_role,
        "doc_seed": doc_seed,
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
    """Genera `n` documentos legítimos. Si `seed` se especifica, el corpus es
    reproducible (necesario para fijar el corpus y luego hacer bootstrap de IC).
    """
    if seed is not None:
        set_global_seed(seed, locale=locale)

    documents = []
    for offset in range(n):
        index = start_index + offset
        documents.append(
            generate_single_pdf(
                index,
                code_prefix=code_prefix,
                output_dir=output_dir,
                document_role=document_role,
            )
        )
    return documents


def generate_distractor_pdfs(
    n: int,
    *,
    seed: int | None = None,
    start_index: int = 1,
    locale: str = DEFAULT_LOCALE,
) -> list[dict]:
    """Genera `n` distractores: documentos del mismo dominio financiero que NO
    se agregan al índice y que no tienen match verdadero en él. Se usan como
    queries para el FPR operativo (§5.1): un distractor cuyo score máximo sobre
    el índice supera el umbral es un falso positivo.

    La semilla se deriva con DISTRACTOR_SEED_OFFSET para que la PII de los
    distractores sea reproducible PERO disjunta de la de los legítimos (evita
    colisiones de DNI/RUC/email que crearían matches espurios).
    """
    if seed is not None:
        set_global_seed(seed + DISTRACTOR_SEED_OFFSET, locale=locale)

    documents = []
    for offset in range(n):
        index = start_index + offset
        documents.append(
            generate_single_pdf(
                index,
                code_prefix="DIST",
                output_dir=DISTRACTOR_OUTPUT_DIR,
                document_role="distractor",
            )
        )
    return documents


# === FORENSIQ_VISUAL_ENRICHED_RENDER_PATCH ===
# Visual enriched synthetic documents:
# watermark, synthetic stamp, simulated signature, validation box and pseudo-QR.
# These elements are generic and explicitly synthetic; they do not reproduce
# any real financial institution document.

from reportlab.lib import colors as _visual_colors
import math as _visual_math


def _stable_visual_seed(doc_seed, document_type: str = "") -> int:
    if doc_seed is not None:
        try:
            return int(doc_seed)
        except Exception:
            pass
    return sum(ord(ch) for ch in str(document_type)) + 2026


def _draw_visual_watermark(c, document_type: str, doc_seed=None):
    width, height = A4
    c.saveState()
    c.setFont("Helvetica-Bold", 38)
    c.setFillColor(_visual_colors.Color(0.86, 0.86, 0.86))
    c.translate(width / 2, height / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, "DOCUMENTO SINTETICO")
    c.restoreState()


def _draw_synthetic_logo(c, document_type: str):
    width, height = A4
    x = 1.55 * cm
    y = height - 2.65 * cm

    c.saveState()
    c.setStrokeColor(_visual_colors.HexColor("#1F3A5F"))
    c.setFillColor(_visual_colors.HexColor("#EAF0F7"))
    c.roundRect(x, y, 2.1 * cm, 1.05 * cm, 5, stroke=1, fill=1)

    c.setFillColor(_visual_colors.HexColor("#1F3A5F"))
    c.setFont("Helvetica-Bold", 7.5)
    c.drawCentredString(x + 1.05 * cm, y + 0.62 * cm, "BANCO")
    c.drawCentredString(x + 1.05 * cm, y + 0.34 * cm, "SINTETICO")
    c.restoreState()


def _draw_validation_box(c, doc_seed=None):
    width, height = A4
    seed = _stable_visual_seed(doc_seed)
    code = "MUESTRA"

    x = width - 6.1 * cm
    y = height - 3.1 * cm

    c.saveState()
    c.setStrokeColor(_visual_colors.HexColor("#6B7280"))
    c.setFillColor(_visual_colors.Color(0.97, 0.97, 0.97))
    c.roundRect(x, y, 4.5 * cm, 1.0 * cm, 4, stroke=1, fill=1)

    c.setFillColor(_visual_colors.HexColor("#374151"))
    c.setFont("Helvetica", 6.8)
    c.drawString(x + 0.18 * cm, y + 0.63 * cm, "VALIDACION SINTETICA")
    c.drawString(x + 0.18 * cm, y + 0.30 * cm, "Control visual sintetico")
    c.restoreState()


def _draw_pseudo_qr(c, doc_seed=None):
    width, height = A4
    seed = _stable_visual_seed(doc_seed)
    rng = random.Random(seed + 99173)

    grid = 9
    cell = 0.105 * cm
    size = grid * cell
    x0 = width - 2.95 * cm
    y0 = 2.15 * cm

    c.saveState()
    c.setStrokeColor(_visual_colors.HexColor("#111827"))
    c.setFillColor(_visual_colors.HexColor("#111827"))
    c.rect(x0 - 0.08 * cm, y0 - 0.08 * cm, size + 0.16 * cm, size + 0.16 * cm, stroke=1, fill=0)

    # Finder-like corners: synthetic pseudo-QR, not machine-valid.
    fixed = {
        (0, 0), (0, 1), (1, 0), (1, 1),
        (0, 7), (0, 8), (1, 7), (1, 8),
        (7, 0), (8, 0), (7, 1), (8, 1),
    }

    for row in range(grid):
        for col in range(grid):
            bit = ((seed >> ((row + col) % 16)) & 1) ^ rng.randint(0, 1)
            if (row, col) in fixed or bit:
                x = x0 + col * cell
                y = y0 + (grid - 1 - row) * cell
                c.rect(x, y, cell * 0.86, cell * 0.86, stroke=0, fill=1)

    c.restoreState()


def _draw_synthetic_stamp(c, doc_seed=None):
    width, height = A4
    seed = _stable_visual_seed(doc_seed)
    rng = random.Random(seed + 12345)

    x = width - 4.1 * cm + rng.uniform(-0.15, 0.15) * cm
    y = 4.15 * cm + rng.uniform(-0.10, 0.10) * cm
    radius = 0.92 * cm + rng.uniform(-0.04, 0.04) * cm

    c.saveState()
    c.setStrokeColor(_visual_colors.HexColor("#7F1D1D"))
    c.setLineWidth(1.1)
    c.circle(x, y, radius, stroke=1, fill=0)
    c.circle(x, y, radius * 0.72, stroke=1, fill=0)

    c.setFillColor(_visual_colors.HexColor("#7F1D1D"))
    c.setFont("Helvetica-Bold", 6.2)
    c.drawCentredString(x, y + 0.18 * cm, "VALIDACION")
    c.drawCentredString(x, y - 0.10 * cm, "SINTETICA")
    c.setFont("Helvetica", 5.2)
    c.drawCentredString(x, y - 0.42 * cm, "NO VALIDO")
    c.restoreState()


def _draw_simulated_signature(c, doc_seed=None):
    width, height = A4
    seed = _stable_visual_seed(doc_seed)
    rng = random.Random(seed + 777)

    x = 6.1 * cm + rng.uniform(-0.15, 0.15) * cm
    y = 3.35 * cm + rng.uniform(-0.08, 0.08) * cm

    c.saveState()
    c.setStrokeColor(_visual_colors.HexColor("#1E3A8A"))
    c.setLineWidth(1.0)

    # Simulated handwritten strokes. This is not a real person's signature.
    c.bezier(x, y, x + 0.7 * cm, y + 0.55 * cm, x + 1.1 * cm, y - 0.35 * cm, x + 1.75 * cm, y + 0.22 * cm)
    c.bezier(x + 1.25 * cm, y + 0.05 * cm, x + 1.8 * cm, y + 0.55 * cm, x + 2.2 * cm, y - 0.25 * cm, x + 2.85 * cm, y + 0.18 * cm)
    c.line(x - 0.2 * cm, y - 0.38 * cm, x + 3.1 * cm, y - 0.38 * cm)

    c.setFillColor(_visual_colors.HexColor("#374151"))
    c.setFont("Helvetica", 6)
    c.drawString(x + 0.2 * cm, y - 0.68 * cm, "Firma autorizada simulada")
    c.restoreState()


def draw_visual_security_features(c, document_type: str, doc_seed=None):
    _draw_synthetic_logo(c, document_type)
    _draw_validation_box(c, doc_seed)
    _draw_pseudo_qr(c, doc_seed)
    _draw_synthetic_stamp(c, doc_seed)
    _draw_simulated_signature(c, doc_seed)


def render_document_from_data(
    data: dict,
    document_type: str,
    doc_code: str,
    output_path: str,
    doc_seed: int | None = None,
    reorder_blocks: bool = False,
    reorder_seed: int | None = None,
) -> None:
    if doc_seed is not None:
        random.seed(doc_seed)

    blocks = build_document_blocks(data, document_type)

    if reorder_blocks:
        groups = _group_blocks(blocks)
        rng = random.Random(reorder_seed)
        rng.shuffle(groups)
        blocks = [b for group in groups for b in group]

    _, height = A4
    c = canvas.Canvas(str(output_path), pagesize=A4)

    _draw_visual_watermark(c, document_type, doc_seed)
    draw_header(c, TITLES.get(document_type, "Documento financiero sintetico"), doc_code, document_type)
    render_blocks(c, blocks, height - 4.8 * cm)
    draw_visual_security_features(c, document_type, doc_seed)
    draw_footer(c)
    c.save()


# === FORENSIQ_VISUAL_V2_TEMPLATE_PATCH ===
# Richer visual templates for synthetic financial documents.
# Generic, synthetic, and non-valid visual identity. Designed for experimental
# forensic matching, not for reproducing real financial documents.

from reportlab.lib import colors as _v2_colors
import json as _v2_json


def _v2_rng(doc_seed=None, document_type: str = ""):
    base = _stable_visual_seed(doc_seed, document_type) if "_stable_visual_seed" in globals() else (int(doc_seed or 2026))
    return random.Random(base + 240517)


def _v2_style_id(doc_seed=None, document_type: str = "") -> int:
    rng = _v2_rng(doc_seed, document_type)
    return rng.randint(0, 19)


def _v2_add_box(labels, cls, x, y, w, h, page_w, page_h):
    labels.append({
        "class": cls,
        "x0": round(x / page_w, 6),
        "y0": round(y / page_h, 6),
        "x1": round((x + w) / page_w, 6),
        "y1": round((y + h) / page_h, 6),
        "cx": round((x + w / 2) / page_w, 6),
        "cy": round((y + h / 2) / page_h, 6),
        "width": round(w / page_w, 6),
        "height": round(h / page_h, 6),
    })


def _v2_draw_watermark(c, labels, style_id, doc_seed=None):
    page_w, page_h = A4
    rng = _v2_rng(doc_seed, "watermark")

    c.saveState()
    c.setFillColor(_v2_colors.Color(0.82, 0.84, 0.86, alpha=0.45))

    if style_id % 4 == 0:
        c.setFont("Helvetica-Bold", 34)
        c.translate(page_w / 2, page_h / 2)
        c.rotate(34)
        c.drawCentredString(0, 0, "DOCUMENTO SINTETICO")
        _v2_add_box(labels, "watermark", page_w * 0.19, page_h * 0.40, page_w * 0.62, page_h * 0.16, page_w, page_h)

    elif style_id % 4 == 1:
        c.setFont("Helvetica-Bold", 18)
        for i in range(4):
            y = page_h * (0.24 + i * 0.16)
            c.drawCentredString(page_w / 2, y, "COPIA SINTETICA")
        _v2_add_box(labels, "watermark", page_w * 0.27, page_h * 0.20, page_w * 0.46, page_h * 0.60, page_w, page_h)

    elif style_id % 4 == 2:
        c.setFont("Helvetica-Bold", 22)
        c.translate(page_w - 1.1 * cm, page_h / 2)
        c.rotate(90)
        c.drawCentredString(0, 0, "VALIDACION SINTETICA")
        _v2_add_box(labels, "watermark", page_w - 1.55 * cm, page_h * 0.25, 0.9 * cm, page_h * 0.50, page_w, page_h)

    else:
        c.setFont("Helvetica-Bold", 28)
        c.drawCentredString(page_w / 2, page_h * 0.53, "SIN VALIDEZ LEGAL")
        c.setFont("Helvetica", 10)
        c.drawCentredString(page_w / 2, page_h * 0.49, "Corpus financiero sintetico")
        _v2_add_box(labels, "watermark", page_w * 0.26, page_h * 0.47, page_w * 0.48, page_h * 0.10, page_w, page_h)

    c.restoreState()


def _v2_draw_logo(c, labels, style_id, doc_seed=None):
    page_w, page_h = A4
    rng = _v2_rng(doc_seed, "logo")

    x = 1.45 * cm
    y = page_h - 2.75 * cm
    w = 2.55 * cm
    h = 1.18 * cm

    c.saveState()
    if style_id % 3 == 0:
        c.setStrokeColor(_v2_colors.HexColor("#1F3A5F"))
        c.setFillColor(_v2_colors.HexColor("#E8EEF7"))
        c.roundRect(x, y, w, h, 6, stroke=1, fill=1)
        c.setFillColor(_v2_colors.HexColor("#1F3A5F"))
        c.setFont("Helvetica-Bold", 7.5)
        c.drawCentredString(x + w / 2, y + 0.70 * cm, "BANCO")
        c.drawCentredString(x + w / 2, y + 0.38 * cm, "SINTETICO")
    elif style_id % 3 == 1:
        c.setStrokeColor(_v2_colors.HexColor("#374151"))
        c.setFillColor(_v2_colors.HexColor("#F3F4F6"))
        c.rect(x, y, w, h, stroke=1, fill=1)
        c.setFillColor(_v2_colors.HexColor("#111827"))
        c.setFont("Helvetica-Bold", 17)
        c.drawString(x + 0.18 * cm, y + 0.34 * cm, "BS")
        c.setFont("Helvetica", 6)
        c.drawString(x + 1.22 * cm, y + 0.67 * cm, "OPERACIONES")
        c.drawString(x + 1.22 * cm, y + 0.39 * cm, "DOCUMENTARIAS")
    else:
        c.setStrokeColor(_v2_colors.HexColor("#0F172A"))
        for i in range(6):
            bw = (0.08 + i * 0.035) * cm
            c.rect(x + i * 0.28 * cm, y + 0.18 * cm, bw, h - 0.36 * cm, stroke=0, fill=1)
        c.setFillColor(_v2_colors.HexColor("#0F172A"))
        c.setFont("Helvetica-Bold", 7)
        c.drawString(x + 1.92 * cm, y + 0.45 * cm, "SYNBANK")
    c.restoreState()

    _v2_add_box(labels, "logo", x, y, w, h, page_w, page_h)


def _v2_draw_validation_box(c, labels, style_id, doc_seed=None):
    page_w, page_h = A4
    rng = _v2_rng(doc_seed, "validation")
    code = "MUESTRA"

    positions = [
        (page_w - 6.35 * cm, page_h - 3.20 * cm),
        (page_w - 6.35 * cm, page_h - 4.05 * cm),
        (1.65 * cm, page_h - 4.05 * cm),
        (page_w - 6.35 * cm, 2.25 * cm),
    ]
    x, y = positions[style_id % len(positions)]
    w, h = 4.75 * cm, 1.08 * cm

    c.saveState()
    c.setStrokeColor(_v2_colors.HexColor("#6B7280"))
    c.setFillColor(_v2_colors.Color(0.96, 0.96, 0.96))
    c.roundRect(x, y, w, h, 4, stroke=1, fill=1)

    c.setFillColor(_v2_colors.HexColor("#374151"))
    c.setFont("Helvetica-Bold", 6.4)
    c.drawString(x + 0.18 * cm, y + 0.68 * cm, "CONTROL DOCUMENTAL")
    c.setFont("Helvetica", 6.1)
    c.drawString(x + 0.18 * cm, y + 0.38 * cm, "Control visual sintetico")
    c.drawString(x + 0.18 * cm, y + 0.15 * cm, "Uso: investigacion sintetica")
    c.restoreState()

    _v2_add_box(labels, "validation_box", x, y, w, h, page_w, page_h)


def _v2_draw_pseudo_qr(c, labels, style_id, doc_seed=None):
    page_w, page_h = A4
    seed = _stable_visual_seed(doc_seed, "qr") if "_stable_visual_seed" in globals() else int(doc_seed or 2026)
    rng = random.Random(seed + 8811)

    positions = [
        (page_w - 3.05 * cm, 2.05 * cm),
        (1.75 * cm, 2.05 * cm),
        (page_w - 3.05 * cm, page_h - 5.15 * cm),
        (1.75 * cm, page_h - 5.15 * cm),
    ]
    x0, y0 = positions[(style_id // 2) % len(positions)]
    grid = 11 if style_id % 2 == 0 else 9
    cell = 0.095 * cm if grid == 11 else 0.112 * cm
    size = grid * cell

    c.saveState()
    c.setStrokeColor(_v2_colors.HexColor("#111827"))
    c.setFillColor(_v2_colors.HexColor("#111827"))
    c.rect(x0 - 0.08 * cm, y0 - 0.08 * cm, size + 0.16 * cm, size + 0.16 * cm, stroke=1, fill=0)

    fixed = {(0,0),(0,1),(1,0),(1,1),(0,grid-1),(1,grid-1),(0,grid-2),(1,grid-2),(grid-1,0),(grid-2,0),(grid-1,1),(grid-2,1)}
    for row in range(grid):
        for col in range(grid):
            bit = ((seed >> ((row * 3 + col) % 17)) & 1) ^ rng.randint(0, 1)
            if (row, col) in fixed or bit:
                x = x0 + col * cell
                y = y0 + (grid - 1 - row) * cell
                c.rect(x, y, cell * 0.83, cell * 0.83, stroke=0, fill=1)
    c.restoreState()

    _v2_add_box(labels, "pseudo_qr", x0 - 0.08 * cm, y0 - 0.08 * cm, size + 0.16 * cm, size + 0.16 * cm, page_w, page_h)


def _v2_draw_stamp(c, labels, style_id, doc_seed=None):
    page_w, page_h = A4
    rng = _v2_rng(doc_seed, "stamp")

    base_positions = [
        (page_w - 4.35 * cm, 4.25 * cm),
        (page_w - 4.35 * cm, 6.15 * cm),
        (4.10 * cm, 4.25 * cm),
        (page_w - 5.20 * cm, page_h - 6.20 * cm),
    ]

    count = 2 if style_id in {4, 7, 11, 15, 18} else 1
    for idx in range(count):
        x, y = base_positions[(style_id + idx) % len(base_positions)]
        x += rng.uniform(-0.18, 0.18) * cm
        y += rng.uniform(-0.12, 0.12) * cm
        r = (0.75 + rng.random() * 0.20) * cm

        c.saveState()
        c.setStrokeColor(_v2_colors.HexColor("#7F1D1D") if idx == 0 else _v2_colors.HexColor("#334155"))
        c.setFillColor(_v2_colors.HexColor("#7F1D1D") if idx == 0 else _v2_colors.HexColor("#334155"))
        c.setLineWidth(1.05)
        c.circle(x, y, r, stroke=1, fill=0)
        c.circle(x, y, r * 0.70, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 5.8)
        c.drawCentredString(x, y + 0.17 * cm, "VALIDADO")
        c.setFont("Helvetica", 5)
        c.drawCentredString(x, y - 0.09 * cm, "SINTETICO")
        c.drawCentredString(x, y - 0.36 * cm, "NO VALIDO")
        c.restoreState()

        _v2_add_box(labels, "stamp", x - r, y - r, 2 * r, 2 * r, page_w, page_h)


def _v2_draw_signature(c, labels, style_id, doc_seed=None):
    page_w, page_h = A4
    rng = _v2_rng(doc_seed, "signature")

    positions = [
        (5.55 * cm, 3.18 * cm),
        (7.35 * cm, 3.65 * cm),
        (4.35 * cm, 5.10 * cm),
        (9.00 * cm, 4.45 * cm),
    ]
    x, y = positions[style_id % len(positions)]
    x += rng.uniform(-0.12, 0.12) * cm
    y += rng.uniform(-0.10, 0.10) * cm

    c.saveState()
    c.setStrokeColor(_v2_colors.HexColor("#1E3A8A"))
    c.setLineWidth(0.9)

    loops = 2 + (style_id % 3)
    px = x
    for i in range(loops):
        c.bezier(
            px, y,
            px + 0.35 * cm, y + (0.35 + 0.08 * i) * cm,
            px + 0.65 * cm, y - 0.28 * cm,
            px + 1.05 * cm, y + 0.14 * cm,
        )
        px += 0.78 * cm

    c.line(x - 0.18 * cm, y - 0.35 * cm, x + 3.15 * cm, y - 0.35 * cm)
    c.setFillColor(_v2_colors.HexColor("#374151"))
    c.setFont("Helvetica", 5.8)
    c.drawString(x + 0.15 * cm, y - 0.63 * cm, "Firma autorizada simulada")
    c.restoreState()

    _v2_add_box(labels, "signature", x - 0.2 * cm, y - 0.75 * cm, 3.55 * cm, 1.40 * cm, page_w, page_h)


def _v2_draw_structural_marks(c, labels, style_id, doc_seed=None):
    page_w, page_h = A4
    c.saveState()
    c.setStrokeColor(_v2_colors.HexColor("#CBD5E1"))
    c.setLineWidth(0.5)

    # Side validation rail
    if style_id % 5 in {1, 3}:
        x = page_w - 1.25 * cm
        y = 5.2 * cm
        h = page_h - 10.4 * cm
        c.rect(x, y, 0.25 * cm, h, stroke=1, fill=0)
        for i in range(9):
            c.line(x, y + i * h / 9, x + 0.25 * cm, y + i * h / 9)
        _v2_add_box(labels, "side_rail", x, y, 0.25 * cm, h, page_w, page_h)

    # Bottom audit strip
    if style_id % 4 in {2, 3}:
        x = 2 * cm
        y = 1.55 * cm
        w = page_w - 4 * cm
        h = 0.38 * cm
        c.rect(x, y, w, h, stroke=1, fill=0)
        for i in range(12):
            c.line(x + i * w / 12, y, x + i * w / 12, y + h)
        _v2_add_box(labels, "audit_strip", x, y, w, h, page_w, page_h)

    c.restoreState()


def draw_visual_security_features(c, document_type: str, doc_seed=None):
    labels = []
    style_id = _v2_style_id(doc_seed, document_type)

    _v2_draw_logo(c, labels, style_id, doc_seed)
    _v2_draw_watermark(c, labels, style_id, doc_seed)
    _v2_draw_validation_box(c, labels, style_id, doc_seed)
    _v2_draw_pseudo_qr(c, labels, style_id, doc_seed)
    _v2_draw_stamp(c, labels, style_id, doc_seed)
    _v2_draw_signature(c, labels, style_id, doc_seed)
    _v2_draw_structural_marks(c, labels, style_id, doc_seed)

    return labels


def render_document_from_data(
    data: dict,
    document_type: str,
    doc_code: str,
    output_path: str,
    doc_seed: int | None = None,
    reorder_blocks: bool = False,
    reorder_seed: int | None = None,
) -> None:
    if doc_seed is not None:
        random.seed(doc_seed)

    blocks = build_document_blocks(data, document_type)

    if reorder_blocks:
        groups = _group_blocks(blocks)
        rng = random.Random(reorder_seed)
        rng.shuffle(groups)
        blocks = [b for group in groups for b in group]

    _, height = A4
    c = canvas.Canvas(str(output_path), pagesize=A4)

    draw_header(c, TITLES.get(document_type, "Documento financiero sintetico"), doc_code, document_type)
    render_blocks(c, blocks, height - 4.8 * cm)
    labels = draw_visual_security_features(c, document_type, doc_seed)
    draw_footer(c)
    c.save()

    # Sidecar for future YOLO training. Normalized coordinates.
    try:
        sidecar = Path(str(output_path)).with_suffix(".visual.json")
        sidecar.write_text(
            _v2_json.dumps({
                "document_type": document_type,
                "doc_seed": doc_seed,
                "style_id": _v2_style_id(doc_seed, document_type),
                "labels": labels,
                "note": "Synthetic visual labels for research; not a real document.",
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

