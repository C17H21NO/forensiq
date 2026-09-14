"""
doc_seed_decoupling.py
======================

PROPÓSITO
---------
Probar (y, si se confirma, corregir) si el aporte del canal de LAYOUT en la
huella multimodal es real o es un ARTEFACTO del generador: el "leak de doc_seed".

DIAGNÓSTICO
-----------
En el generador sintético, TODO el mobiliario visual de un documento
(style_id, jitter del sello, patrón del pseudo-QR, firma simulada, posiciones de
cajas) se deriva de `_stable_visual_seed(doc_seed)`. Las VARIANTES se
re-renderizan reutilizando el `doc_seed` del PADRE para reproducir el contenido
no-determinista (filas de tablas). El efecto colateral es que la variante hereda
TAMBIÉN el mobiliario visual EXACTO del padre:

    - mismo style_id,
    - mismo patrón de celdas del pseudo-QR,
    - mismo jitter de posición/ radio del sello,
    - misma firma y mismas posiciones de cajas.

El extractor de layout captura sello / QR / imágenes como bloques `graphic` e
`image`. Por lo tanto el descriptor de layout se vuelve una CLAVE CASI ÚNICA
derivada de `doc_seed`: idéntica entre variante y padre, distinta frente a
cualquier otro legítimo (otro `doc_seed`). Un grid search que maximiza Recall@1
sobre un mix con texto/PII degradados pondrá racionalmente casi todo el peso en
layout (w_layout = 0.80). Eso NO es robustez forense: un falsificador real no
reproduce el jitter del sello ni el patrón del QR. El corpus lo regala.

Es el MISMO leak de identidad que ya corregimos en los distractores
(PII-as-key), ahora en el canal de layout.

QUÉ HACE ESTE MÓDULO
--------------------
1. `furniture_seed_override(visual_seed)`: context manager que desacopla el
   mobiliario visual del `doc_seed` del padre SIN tocar la reproducción del
   contenido (las filas de tabla siguen saliendo del `doc_seed` del padre, por lo
   que la variante difiere del padre SOLO en lo transformado, como debe ser).
2. `independent_visual_seed(...)`: semilla visual determinista por caso.
3. `generate_variant_decoupled(...)`: drop-in de `generate_variant_from_pdf` con
   el mobiliario desacoplado.
4. `__main__`: arnés A/B que genera 1 padre + 2 variantes (furniture acoplado vs
   desacoplado), extrae sus bloques de layout y muestra que bajo ACOPLE los
   bloques graphic/image son idénticos al padre (leak) y bajo DESACOPLE difieren.

CÓMO USARLO PARA LA ABLACIÓN (lo importante para el paper)
----------------------------------------------------------
En `evaluation.prepare_corpus`, reemplazar la línea:

    variant = generate_variant_from_pdf(ref["stored_path"], transformation, seed=case_seed)

por:

    from app.services.doc_seed_decoupling import generate_variant_decoupled
    variant = generate_variant_decoupled(
        ref["stored_path"], transformation,
        case_seed=case_seed, parent_doc_id=ref["document_id"],
    )

Luego re-correr el experimento con `weight_mode="grid_search"` en DOS condiciones:

    (A) Flujo actual  -> furniture ACOPLADO  (control).
    (B) Este módulo   -> furniture DESACOPLADO.

LECTURA DEL RESULTADO:
    - Si en (B) el `w_layout` colapsa (p. ej. de 0.80 a ~0.2-0.3) y la diferencia
      Recall@1 G vs E (+0.175) se evapora o pierde significancia -> el aporte del
      layout era furniture leak. La claim "el layout aporta" NO es publicable tal
      cual; el layout sirve, a lo sumo, como estructura de bloques de TEXTO.
    - Si en (B) `w_layout` sigue alto y G > E se mantiene significativo -> el
      aporte es REAL (estructura, no mobiliario) y es defendible ante el jurado.

NOTA: este módulo es no invasivo (monkeypatch acotado vía context manager). Si el
resultado (B) valida el aporte, conviene promover `visual_seed` a parámetro de
primer nivel de `render_document_from_data` en una refactorización posterior.
"""

from __future__ import annotations

import contextlib
import hashlib
from pathlib import Path
from typing import Iterator, Optional

from app.services import synthetic_generator as sg
from app.services.variant_generator import generate_variant_from_pdf


# --------------------------------------------------------------------------- #
# 1) Semilla visual independiente, determinista por caso
# --------------------------------------------------------------------------- #
def independent_visual_seed(case_seed: int, parent_doc_id: str,
                            transformation_type: str) -> int:
    """Semilla visual reproducible y *desacoplada* del doc_seed del padre.

    Depende de (case_seed, parent_doc_id, transformation_type) pero NO del
    doc_seed del padre, de modo que el mobiliario de la variante no coincide con
    el del padre. Es estable entre corridas (clave para reproducir IC/bootstrap).
    """
    payload = f"VISUAL|{case_seed}|{parent_doc_id}|{transformation_type}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)  # entero de 32 bits


# --------------------------------------------------------------------------- #
# 2) Context manager: desacopla SOLO el mobiliario visual
# --------------------------------------------------------------------------- #
@contextlib.contextmanager
def furniture_seed_override(visual_seed: int) -> Iterator[None]:
    """Hace que el mobiliario visual dependa de `visual_seed` y no del doc_seed.

    Funciona parcheando `synthetic_generator._stable_visual_seed`, que es la
    ÚNICA fuente de aleatoriedad del mobiliario (style_id, sello, QR, firma,
    posiciones). El contenido (filas de tabla) NO pasa por esta función: usa
    `random.seed(doc_seed)` directamente en `render_document_from_data`, así que
    la reproducción del contenido del padre queda intacta.

    Se mezcla `document_type` para que tipos distintos sigan teniendo mobiliario
    distinto, manteniendo la independencia respecto a la identidad del padre.
    """
    original = sg._stable_visual_seed

    def _patched(doc_seed=None, document_type: str = "") -> int:  # noqa: ANN001
        base = int(visual_seed)
        if document_type:
            base += sum(ord(ch) for ch in str(document_type))
        return int(base)

    sg._stable_visual_seed = _patched
    try:
        yield
    finally:
        sg._stable_visual_seed = original


# --------------------------------------------------------------------------- #
# 3) Drop-in de generate_variant_from_pdf con mobiliario desacoplado
# --------------------------------------------------------------------------- #
def generate_variant_decoupled(
    file_path: str,
    transformation_type: str = "combined",
    *,
    case_seed: int,
    parent_doc_id: Optional[str] = None,
) -> dict:
    """Igual que `generate_variant_from_pdf`, pero el mobiliario visual de la
    variante usa una semilla INDEPENDIENTE del doc_seed del padre.

    El contenido sigue reproduciéndose desde el doc_seed del padre (la variante
    difiere del padre solo en lo transformado). El resultado incluye
    `visual_seed_decoupled=True` para trazabilidad.
    """
    parent_id = parent_doc_id or Path(file_path).name
    vseed = independent_visual_seed(case_seed, parent_id, transformation_type)

    with furniture_seed_override(vseed):
        result = generate_variant_from_pdf(
            file_path, transformation_type, seed=case_seed
        )

    if isinstance(result, dict):
        result["visual_seed_decoupled"] = True
        result["visual_seed"] = vseed
    return result


# --------------------------------------------------------------------------- #
# 4) Arnés A/B de demostración del leak (correr en el entorno con dependencias)
# --------------------------------------------------------------------------- #
def _graphic_image_signature(blocks: list[dict]) -> list[tuple]:
    """Firma geométrica redondeada de los bloques graphic/image (el mobiliario).
    Si dos documentos comparten esta firma, comparten el mobiliario visual."""
    sig = []
    for b in blocks:
        if b.get("block_type") in {"graphic", "image"}:
            sig.append((
                b.get("block_type"),
                round(float(b.get("x0", 0)), 4),
                round(float(b.get("y0", 0)), 4),
                round(float(b.get("x1", 0)), 4),
                round(float(b.get("y1", 0)), 4),
            ))
    return sorted(sig)


def _demo() -> None:
    """Demostración mínima:
      1) genera 1 documento legítimo (padre),
      2) genera la MISMA variante con furniture ACOPLADO y con DESACOPLADO,
      3) compara la firma geométrica del mobiliario contra el padre.
    Esperado:
      - ACOPLADO   -> firma de graphic/image IDÉNTICA al padre (leak).
      - DESACOPLADO -> firma DISTINTA del padre.
    """
    from app.services.synthetic_generator import generate_synthetic_pdfs
    from app.services.extractor import extract_layout_blocks

    transformation = "mask_pii"  # caso donde el layout es el canal sobreviviente
    case_seed = 1234

    print("== Generando documento padre ==")
    parent = generate_synthetic_pdfs(1, seed=99)[0]
    parent_path = parent["path"]
    parent_id = parent["document_id"]
    parent_sig = _graphic_image_signature(extract_layout_blocks(parent_path))
    print(f"  padre: {parent_id}  | bloques graphic/image: {len(parent_sig)}")

    print("\n== Variante con furniture ACOPLADO (flujo actual) ==")
    v_coupled = generate_variant_from_pdf(parent_path, transformation, seed=case_seed)
    sig_coupled = _graphic_image_signature(extract_layout_blocks(v_coupled["variant_path"]))
    same_coupled = sig_coupled == parent_sig
    print(f"  ¿mobiliario IDÉNTICO al padre?  -> {same_coupled}  (esperado: True = LEAK)")

    print("\n== Variante con furniture DESACOPLADO (este módulo) ==")
    v_dec = generate_variant_decoupled(
        parent_path, transformation, case_seed=case_seed, parent_doc_id=parent_id
    )
    sig_dec = _graphic_image_signature(extract_layout_blocks(v_dec["variant_path"]))
    same_dec = sig_dec == parent_sig
    print(f"  ¿mobiliario IDÉNTICO al padre?  -> {same_dec}  (esperado: False = corregido)")

    print("\n== Veredicto ==")
    if same_coupled and not same_dec:
        print("  CONFIRMADO: el mobiliario visual era una clave heredada del doc_seed.")
        print("  Re-correr el grid search en ambas condiciones y comparar w_layout y G vs E.")
    elif not same_coupled:
        print("  El padre no expone mobiliario graphic/image comparable; revisar el extractor.")
    else:
        print("  El desacople no cambió la firma; revisar que _stable_visual_seed sea la fuente única.")


if __name__ == "__main__":
    try:
        _demo()
    except Exception as exc:  # dependencias ausentes en este entorno, etc.
        print(f"[demo no ejecutada] {type(exc).__name__}: {exc}")
        print("Correr en el entorno con reportlab + PyMuPDF instalados.")
