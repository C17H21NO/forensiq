from pathlib import Path
import fitz  # PyMuPDF
from docx import Document
from app.services.ocr_service import extract_text_with_ocr_fallback

def extract_text_from_pdf(file_path: str) -> str:
    text_parts = []

    with fitz.open(file_path) as pdf:
        for page in pdf:
            text_parts.append(page.get_text())

    return "\n".join(text_parts).strip()


def extract_text_from_docx(file_path: str) -> str:
    document = Document(file_path)
    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    return "\n".join(paragraphs).strip()
def extract_text_details(file_path: str) -> dict:
    path = Path(file_path)
    suffix = path.suffix.lower()

    direct_text = ""

    if suffix == ".pdf":
        direct_text = extract_text_from_pdf(file_path)

    elif suffix == ".docx":
        direct_text = extract_text_from_docx(file_path)

    elif suffix in [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"]:
        direct_text = ""

    else:
        raise ValueError(f"Formato no soportado para extracción de texto: {suffix}")

    ocr_result = extract_text_with_ocr_fallback(
        file_path=file_path,
        direct_text=direct_text,
        min_chars=40,
    )

    return {
        "text": ocr_result["text"],
        "extraction_mode": ocr_result["mode"],
        "ocr_used": ocr_result["ocr_used"],
        "ocr_available": ocr_result["ocr_available"],
        "text_length": len(ocr_result["text"]),
    }

def extract_text(file_path: str) -> str:
    return extract_text_details(file_path)["text"]

def extract_layout_blocks_from_pdf(file_path: str) -> list[dict]:
    blocks = []

    with fitz.open(file_path) as pdf:
        for page_index, page in enumerate(pdf):
            page_width = page.rect.width
            page_height = page.rect.height

            raw_blocks = page.get_text("blocks")

            for block in raw_blocks:
                x0, y0, x1, y1, text, block_no, block_type = block

                clean_text = " ".join(str(text).split())

                if not clean_text:
                    continue

                block_width = max(x1 - x0, 0)
                block_height = max(y1 - y0, 0)
                block_area = block_width * block_height
                page_area = page_width * page_height if page_width and page_height else 1

                blocks.append({
                    "page_index": page_index,
                    "x0": x0 / page_width if page_width else 0,
                    "y0": y0 / page_height if page_height else 0,
                    "x1": x1 / page_width if page_width else 0,
                    "y1": y1 / page_height if page_height else 0,
                    "width": block_width / page_width if page_width else 0,
                    "height": block_height / page_height if page_height else 0,
                    "area": block_area / page_area,
                    "text_length": len(clean_text),
                    "has_digits": any(char.isdigit() for char in clean_text),
                    "has_colon": ":" in clean_text,
                    "line_count": clean_text.count("\n") + 1,
                })

    return blocks


def extract_layout_blocks(file_path: str) -> list[dict]:
    file_path_lower = file_path.lower()

    if file_path_lower.endswith(".pdf"):
        return extract_layout_blocks_from_pdf(file_path)

    return []


# === FORENSIQ_VISUAL_LAYOUT_EXTRACTION_PATCH ===
# Extends layout extraction with vector drawings and image regions.

def _append_layout_block(blocks, page_index, page_width, page_height, x0, y0, x1, y1, **extra):
    block_width = max(x1 - x0, 0)
    block_height = max(y1 - y0, 0)
    block_area = block_width * block_height
    page_area = page_width * page_height if page_width and page_height else 1

    item = {
        "page_index": page_index,
        "x0": x0 / page_width if page_width else 0,
        "y0": y0 / page_height if page_height else 0,
        "x1": x1 / page_width if page_width else 0,
        "y1": y1 / page_height if page_height else 0,
        "width": block_width / page_width if page_width else 0,
        "height": block_height / page_height if page_height else 0,
        "area": block_area / page_area,
    }
    item.update(extra)
    blocks.append(item)


def extract_layout_blocks_from_pdf(file_path: str) -> list[dict]:
    blocks = []

    with fitz.open(file_path) as pdf:
        for page_index, page in enumerate(pdf):
            page_width = page.rect.width
            page_height = page.rect.height

            # Text blocks
            raw_blocks = page.get_text("blocks")
            for block in raw_blocks:
                x0, y0, x1, y1, text, block_no, block_type = block
                clean_text = " ".join(str(text).split())

                if not clean_text:
                    continue

                _append_layout_block(
                    blocks,
                    page_index,
                    page_width,
                    page_height,
                    x0,
                    y0,
                    x1,
                    y1,
                    block_type="text",
                    text_length=len(clean_text),
                    has_digits=any(char.isdigit() for char in clean_text),
                    has_colon=":" in clean_text,
                    line_count=clean_text.count("\n") + 1,
                )

            # Vector drawings: lines, rectangles, circles, pseudo-QR cells, signature strokes, stamp.
            try:
                drawings = page.get_drawings()
            except Exception:
                drawings = []

            for drawing in drawings:
                rect = drawing.get("rect")
                if rect is None:
                    continue

                x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
                if x1 <= x0 or y1 <= y0:
                    continue

                items = drawing.get("items", []) or []
                _append_layout_block(
                    blocks,
                    page_index,
                    page_width,
                    page_height,
                    x0,
                    y0,
                    x1,
                    y1,
                    block_type="graphic",
                    text_length=0,
                    has_digits=False,
                    has_colon=False,
                    line_count=len(items),
                    drawing_items=len(items),
                    has_fill=drawing.get("fill") is not None,
                    stroke_width=float(drawing.get("width") or 0.0),
                )

            # Images if present
            try:
                images = page.get_images(full=True)
            except Exception:
                images = []

            for img in images:
                try:
                    xref = img[0]
                    rects = page.get_image_rects(xref)
                except Exception:
                    rects = []

                for rect in rects:
                    x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
                    if x1 <= x0 or y1 <= y0:
                        continue

                    _append_layout_block(
                        blocks,
                        page_index,
                        page_width,
                        page_height,
                        x0,
                        y0,
                        x1,
                        y1,
                        block_type="image",
                        text_length=0,
                        has_digits=False,
                        has_colon=False,
                        line_count=0,
                        drawing_items=0,
                        has_fill=True,
                        stroke_width=0.0,
                    )

    return blocks

