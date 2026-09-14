from pathlib import Path
import shutil
from typing import Dict, Any

import fitz  # PyMuPDF
from PIL import Image


def is_tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_image(image: Image.Image, lang: str = "spa+eng") -> str:
    try:
        import pytesseract

        return pytesseract.image_to_string(image, lang=lang) or ""
    except Exception as exc:
        print(f"[OCR] Error procesando imagen: {exc}")
        return ""


def ocr_image_file(file_path: str, lang: str = "spa+eng") -> str:
    try:
        image = Image.open(file_path).convert("RGB")
        return ocr_image(image, lang=lang)
    except Exception as exc:
        print(f"[OCR] Error abriendo imagen {file_path}: {exc}")
        return ""


def ocr_pdf_file(file_path: str, lang: str = "spa+eng", max_pages: int = 5) -> str:
    texts = []

    try:
        doc = fitz.open(file_path)

        for page_index, page in enumerate(doc):
            if page_index >= max_pages:
                break

            # Render con zoom para mejorar OCR
            matrix = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=matrix, alpha=False)

            image = Image.frombytes(
                "RGB",
                [pix.width, pix.height],
                pix.samples,
            )

            page_text = ocr_image(image, lang=lang)

            if page_text.strip():
                texts.append(page_text)

        doc.close()

    except Exception as exc:
        print(f"[OCR] Error procesando PDF {file_path}: {exc}")

    return "\n".join(texts)


def extract_text_with_ocr_fallback(
    file_path: str,
    direct_text: str = "",
    min_chars: int = 40,
) -> Dict[str, Any]:
    """
    Si direct_text tiene suficiente contenido, lo conserva.
    Si direct_text está vacío o es muy corto, intenta OCR local.
    """

    suffix = Path(file_path).suffix.lower()
    direct_text = direct_text or ""

    if len(direct_text.strip()) >= min_chars:
        return {
            "text": direct_text,
            "mode": "direct_text",
            "ocr_used": False,
            "ocr_available": is_tesseract_available(),
        }

    ocr_text = ""

    if suffix == ".pdf":
        ocr_text = ocr_pdf_file(file_path)
    elif suffix in [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"]:
        ocr_text = ocr_image_file(file_path)

    if len(ocr_text.strip()) > len(direct_text.strip()):
        return {
            "text": ocr_text,
            "mode": "ocr_fallback",
            "ocr_used": True,
            "ocr_available": is_tesseract_available(),
        }

    return {
        "text": direct_text,
        "mode": "direct_text_empty_or_low_quality",
        "ocr_used": False,
        "ocr_available": is_tesseract_available(),
    }