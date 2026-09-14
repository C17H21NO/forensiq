from pathlib import Path
from uuid import uuid4
import shutil
import time
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from app.services.ocr_service import is_tesseract_available

from app.services.nlp_entity_service import (
    detect_spacy_entities,
    is_spacy_available,
)

from app.database import init_db, get_db
from app.services.reference_repository import (
    save_reference_document_db,
    list_reference_documents_db,
    clear_reference_documents_db,
)

from app.services.analysis_history_repository import (
    save_analysis_history_db,
    list_analysis_history_db,
    clear_analysis_history_db,
)
from app.services.synthetic_generator import generate_synthetic_pdfs
from app.services.extractor import (
    extract_text,
    extract_text_details,
    extract_layout_blocks,
)
from app.services.pii_detector import detect_pii_masked
from app.services.fingerprint import build_fingerprint
from app.services.matcher import (
    add_reference_document,
    list_reference_documents,
    clear_reference_index,
    match_against_references,
    get_reference_document_by_id,
)
from app.services.evaluation import (
    run_evaluation,
    run_evaluation_summary_only,
    save_evaluation_summary_to_file,
)
from app.services.variant_generator import generate_variant_from_pdf

BASE_DIR = Path(__file__).resolve().parents[1]
UPLOAD_DIR = BASE_DIR / "app" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# === FORENSIQ_VISUAL_API_SUMMARY_PATCH ===
# Human-readable visual/layout summary for analyst-facing responses.

def summarize_visual_layout(layout_blocks, fingerprint=None):
    layout_blocks = layout_blocks or []

    text_blocks = [b for b in layout_blocks if b.get("block_type", "text") == "text"]
    graphic_blocks = [b for b in layout_blocks if b.get("block_type") == "graphic"]
    image_blocks = [b for b in layout_blocks if b.get("block_type") == "image"]
    visual_blocks = graphic_blocks + image_blocks

    layout_features = {}
    if fingerprint:
        layout_features = fingerprint.get("layout_features", {}) or {}

    visual_to_text_ratio = layout_features.get(
        "visual_to_text_ratio",
        len(visual_blocks) / max(len(text_blocks), 1),
    )

    visual_area = layout_features.get(
        "visual_area",
        sum(float(b.get("area", 0.0)) for b in visual_blocks),
    )

    if image_blocks and len(image_blocks) >= 1 and len(text_blocks) <= 2:
        visual_condition = "Documento posiblemente rasterizado o escaneado: gran parte del contenido visual puede estar dentro de una imagen."
    elif len(visual_blocks) >= 10:
        visual_condition = "Documento con se?ales visuales/gr?ficas enriquecidas detectables."
    elif len(visual_blocks) > 0:
        visual_condition = "Documento con algunas se?ales visuales/gr?ficas detectables."
    else:
        visual_condition = "No se detectaron se?ales visuales/gr?ficas relevantes; el an?lisis depende principalmente de texto, PII y layout textual."

    return {
        "layout_block_count": len(layout_blocks),
        "text_block_count": len(text_blocks),
        "graphic_block_count": len(graphic_blocks),
        "image_block_count": len(image_blocks),
        "visual_block_count": len(visual_blocks),
        "visual_to_text_ratio": round(float(visual_to_text_ratio), 4),
        "visual_area": round(float(visual_area), 4),
        "layout_feature_count": len(layout_features),
        "visual_condition": visual_condition,
    }


def explain_match_scores(scores):
    scores = scores or {}

    text_score = float(scores.get("selected_text_score", scores.get("text_score", 0.0)) or 0.0)
    layout_score = float(scores.get("layout_score", 0.0) or 0.0)
    pii_score = float(scores.get("pii_score", 0.0) or 0.0)

    parts = {
        "texto": text_score,
        "layout_visual": layout_score,
        "pii": pii_score,
    }

    dominant = max(parts, key=parts.get)
    dominant_score = parts[dominant]

    if dominant_score < 0.15:
        explanation = "Coincidencia d?bil: ninguna modalidad aporta una se?al fuerte."
    elif dominant == "texto":
        explanation = "Coincidencia explicada principalmente por similitud textual."
    elif dominant == "pii":
        explanation = "Coincidencia explicada principalmente por entidades PII detectadas."
    else:
        explanation = "Coincidencia explicada principalmente por estructura/layout visual."

    return {
        "dominant_signal": dominant,
        "dominant_score": round(dominant_score, 4),
        "explanation": explanation,
    }


def enrich_matches_for_analyst(matches):
    enriched = []
    for item in matches or []:
        scores = item.get("scores", {})
        enriched.append({
            **item,
            "analyst_explanation": explain_match_scores(scores),
        })
    return enriched


app = FastAPI(
    title="ForensiQ Fingerprint API",
    description="API para huella semántica multimodal y matching forense de documentos.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.on_event("startup")
def on_startup():
    init_db()

@app.get("/")
def health_check():
    return {
        "status": "ok",
        "message": "ForensiQ backend running",
    }


@app.post("/synthetic/generate")
def generate_synthetic_documents(n: int = 10):
    documents = generate_synthetic_pdfs(n)
    return {
        "generated": len(documents),
        "documents": documents,
    }


@app.post("/documents/analyze")
def analyze_document(file: UploadFile = File(...)):
    file_suffix = Path(file.filename).suffix.lower()
    stored_filename = f"{uuid4().hex}{file_suffix}"
    stored_path = UPLOAD_DIR / stored_filename

    with stored_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    extraction = extract_text_details(str(stored_path))
    text = extraction["text"]
    pii_entities = detect_pii_masked(text)
    nlp_entities = detect_spacy_entities(text)

    layout_blocks = extract_layout_blocks(str(stored_path))
    fingerprint = build_fingerprint(text, pii_entities, layout_blocks)

    return {
        "filename": file.filename,
        "stored_filename": stored_filename,
        "text_length": len(text),
        "text_preview": text[:700],
        "pii_count": len(pii_entities),
        "pii_entities": pii_entities,
        "layout_block_count": len(layout_blocks),
        "fingerprint_summary": fingerprint["summary"],
        "visual_summary": summarize_visual_layout(layout_blocks, fingerprint),
        "layout_features": fingerprint["layout_features"],
        "pii_features": fingerprint["pii_features"],
        "nlp_entity_count": len(nlp_entities),
        "nlp_entities": nlp_entities,  
        "extraction_mode": extraction["extraction_mode"],
        "ocr_used": extraction["ocr_used"],
        "ocr_available": extraction["ocr_available"],
    }
@app.post("/references/upload")
def upload_reference_document(file: UploadFile = File(...),db: Session = Depends(get_db),):
    original_filename = file.filename or ""

    if original_filename.upper().startswith("VARIANT_"):
        raise HTTPException(
            status_code=400,
            detail=(
                "El archivo parece ser una variante sospechosa. "
                "Las variantes no deben cargarse como documentos legítimos de referencia."
            ),
        )
    file_suffix = Path(file.filename).suffix.lower()
    stored_filename = f"{uuid4().hex}{file_suffix}"
    stored_path = UPLOAD_DIR / stored_filename
    
    with stored_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    text = extract_text(str(stored_path))
    pii_entities = detect_pii_masked(text)
    layout_blocks = extract_layout_blocks(str(stored_path))
    fingerprint = build_fingerprint(text, pii_entities, layout_blocks)

    document = {
        "document_id": stored_filename,
        "filename": file.filename,
        "stored_path": str(stored_path),
        "text": text,
        "text_length": len(text),
        "pii_entities": pii_entities,
        "pii_count": len(pii_entities),
        "fingerprint": fingerprint,
    }

    add_reference_document(document)
    save_reference_document_db(db, document)
    
    return {
        "message": "Documento legítimo agregado al índice de referencia.",
        "document_id": document["document_id"],
        "filename": document["filename"],
        "text_length": document["text_length"],
        "pii_count": document["pii_count"],
        "fingerprint_summary": fingerprint["summary"],
    }
@app.get("/references")
def get_references():
    references = list_reference_documents()

    documents = []

    for ref in references:
        text = ref.get("text", "")
        pii_entities = ref.get("pii_entities", [])

        text_length = ref.get("text_length")
        if text_length is None:
            text_length = len(text)

        pii_count = ref.get("pii_count")
        if pii_count is None:
            pii_count = len(pii_entities)

        fingerprint = ref.get("fingerprint", {})
        fingerprint_summary = fingerprint.get("summary", {})

        documents.append({
            "document_id": ref.get("document_id"),
            "filename": ref.get("filename"),
            "text_length": text_length,
            "pii_count": pii_count,
            "fingerprint_summary": fingerprint_summary,
        })

    return {
        "total": len(references),
        "documents": documents,
    }
@app.delete("/references")
def delete_references(db: Session = Depends(get_db)):
    clear_reference_index()
    deleted_from_db = clear_reference_documents_db(db)
    return {
        "message": "Índice de referencias limpiado.",
        "deleted_from_memory": True,
        "deleted_from_db": deleted_from_db,
    }
@app.post("/documents/match")
def match_suspicious_document(
    file: UploadFile = File(...),
    top_k: int = 5,
    db: Session = Depends(get_db),
):
    start_time = time.perf_counter()

    file_suffix = Path(file.filename).suffix.lower()
    stored_filename = f"{uuid4().hex}{file_suffix}"
    stored_path = UPLOAD_DIR / stored_filename

    with stored_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    extraction = extract_text_details(str(stored_path))
    text = extraction["text"]
    pii_entities = detect_pii_masked(text)
    nlp_entities = detect_spacy_entities(text)

    layout_blocks = extract_layout_blocks(str(stored_path))
    fingerprint = build_fingerprint(text, pii_entities, layout_blocks)

    matches = match_against_references(
        fingerprint,
        top_k=top_k,
        use_hybrid_text=True,
    )

    latency_ms = (time.perf_counter() - start_time) * 1000

    result = {
        "filename": file.filename,
        "stored_filename": stored_filename,
        "stored_path": str(stored_path),

        "text_length": len(text),
        "text_preview": text[:1200],

        "extraction_mode": extraction["extraction_mode"],
        "ocr_used": extraction["ocr_used"],
        "ocr_available": extraction["ocr_available"],

        "pii_count": len(pii_entities),
        "pii_entities": pii_entities[:50],

        "nlp_entity_count": len(nlp_entities),
        "nlp_entities": nlp_entities[:50],

        "layout_block_count": len(layout_blocks),
        "layout_block_count": len(layout_blocks),
        "fingerprint_summary": fingerprint["summary"],
        "visual_summary": summarize_visual_layout(layout_blocks, fingerprint),
        "layout_features": fingerprint["layout_features"],
        "pii_features": fingerprint["pii_features"],

        "top_k": top_k,
        "latency_ms": round(latency_ms, 2),
        "matches": matches,
    }

    save_analysis_history_db(db, result, latency_ms=latency_ms)

    return result
    
@app.post("/synthetic/variant")
def generate_suspicious_variant(
    file: UploadFile = File(...),
    transformation_type: str = "combined",
):
    file_suffix = Path(file.filename).suffix.lower()
    stored_filename = f"{uuid4().hex}{file_suffix}"
    stored_path = UPLOAD_DIR / stored_filename

    with stored_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    variant = generate_variant_from_pdf(
        str(stored_path),
        transformation_type=transformation_type,
    )

    return {
        "message": "Variante sospechosa generada.",
        "source_uploaded_filename": file.filename,
        "transformation_type": transformation_type,
        "variant": variant,
    }
@app.get("/system/capabilities")
def get_system_capabilities():
    return {
        "backend": "active",
        "ocr_tesseract_available": is_tesseract_available(),
        "text_extraction": "direct_text_with_ocr_fallback",
        "layout": "pymupdf_text_blocks_plus_visual_graphics",
        "visual_descriptor": "pymupdf_graphic_objects_density_grid",
        "semantic_encoder": "sbert_384d",
        "pii_detector": "regex_rules",
        "spacy_available": is_spacy_available(),
        "spacy_model": "es_core_news_sm",
        "yolo11": "not_enabled_future_extension",
        "experimental_modes": {
            "standard": "T1-T8 + M1-M10",
            "visual_enriched": "V1-V4",
            "scan_ocr_stress": "S1-S4"
        },
    }
@app.post("/evaluation/run")
def run_experimental_evaluation():
    return run_evaluation()

@app.post("/references/bootstrap-synthetic")
def bootstrap_synthetic_references(n: int = 30, clear_existing: bool = True, db: Session = Depends(get_db)):
    if clear_existing:
        clear_reference_index()
        clear_reference_documents_db(db)
    generated_documents = generate_synthetic_pdfs(n)
    added_documents = []

    for generated in generated_documents:
        file_path = generated["path"]
        filename = generated["filename"]

        text = extract_text(file_path)
        pii_entities = detect_pii_masked(text)
        layout_blocks = extract_layout_blocks(file_path)
        fingerprint = build_fingerprint(text, pii_entities, layout_blocks)

        document = {
            "document_id": filename,
            "filename": filename,
            "stored_path": file_path,
            "text": text,
            "text_length": len(text),
            "pii_entities": pii_entities,
            "pii_count": len(pii_entities),
            "fingerprint": fingerprint,
        }

        add_reference_document(document)
        save_reference_document_db(db, document)
        added_documents.append({
            "document_id": document["document_id"],
            "filename": document["filename"],
            "text_length": document["text_length"],
            "pii_count": document["pii_count"],
            "fingerprint_summary": fingerprint["summary"],
        })

    return {
        "message": "Corpus sintético generado y cargado al índice de referencia.",
        "generated": len(generated_documents),
        "added_to_reference_index": len(added_documents),
        "clear_existing": clear_existing,
        "documents": added_documents,
    }
@app.post("/evaluation/summary")
def run_experimental_evaluation_summary():
    return run_evaluation_summary_only()
@app.post("/evaluation/save-summary")
def save_experimental_evaluation_summary():
    return save_evaluation_summary_to_file()
@app.post("/references/{document_id}/variant")
def generate_variant_from_reference(
    document_id: str,
    transformation_type: str = "combined",
):
    reference = get_reference_document_by_id(document_id)

    if reference is None:
        return {
            "error": "Documento de referencia no encontrado.",
            "document_id": document_id,
            "hint": "Verifica que el documento exista en GET /references.",
        }

    variant = generate_variant_from_pdf(
        reference["stored_path"],
        transformation_type=transformation_type,
    )

    return {
        "message": "Variante sospechosa generada desde documento indexado.",
        "document_id": document_id,
        "source_filename": reference["filename"],
        "transformation_type": transformation_type,
        "variant": variant,
    }
@app.post("/references/{document_id}/variant-and-match")
def generate_variant_and_match_from_reference(
    document_id: str,
    transformation_type: str = "combined",
    top_k: int = 5,
):
    reference = get_reference_document_by_id(document_id)

    if reference is None:
        return {
            "error": "Documento de referencia no encontrado.",
            "document_id": document_id,
            "hint": "Verifica que el documento exista en GET /references.",
        }

    variant = generate_variant_from_pdf(
        reference["stored_path"],
        transformation_type=transformation_type,
    )

    text = extract_text(variant["variant_path"])
    pii_entities = detect_pii_masked(text)
    layout_blocks = extract_layout_blocks(variant["variant_path"])
    fingerprint = build_fingerprint(text, pii_entities, layout_blocks)

    matches = match_against_references(
        fingerprint,
        top_k=top_k,
        use_hybrid_text=True,
    )

    rank_position = None
    for index, match in enumerate(matches, start=1):
        if match["document_id"] == document_id:
            rank_position = index
            break

    return {
        "message": "Variante generada y comparada contra el índice.",
        "source_document_id": document_id,
        "source_filename": reference["filename"],
        "transformation_type": transformation_type,
        "variant": variant,
        "text_length": len(text),
        "pii_count": len(pii_entities),
        "layout_block_count": len(layout_blocks),
        "fingerprint_summary": fingerprint["summary"],
        "visual_summary": summarize_visual_layout(layout_blocks, fingerprint),
        "top_k": top_k,
        "rank_position": rank_position,
        "top_1_hit": rank_position == 1,
        "top_5_hit": rank_position is not None and rank_position <= 5,
        "matches": enrich_matches_for_analyst(matches),
    }
@app.post("/references/load-from-db")
def load_references_from_db(db: Session = Depends(get_db)):
    clear_reference_index()

    documents = list_reference_documents_db(db)

    for document in documents:
        add_reference_document(document)

    return {
        "message": "Índice de referencias recargado desde SQLite.",
        "total": len(documents),
        "documents": [
            {
                "document_id": document["document_id"],
                "filename": document["filename"],
                "text_length": len(document.get("text", "")),
                "fingerprint_summary": document["fingerprint"].get("summary", {}),
            }
            for document in documents
        ],
    }
@app.get("/analysis/history")
def get_analysis_history(db: Session = Depends(get_db)):
    history = list_analysis_history_db(db)

    return {
        "total": len(history),
        "items": history,
    }


@app.delete("/analysis/history")
def clear_analysis_history(db: Session = Depends(get_db)):
    deleted = clear_analysis_history_db(db)

    return {
        "message": "Historial de análisis limpiado.",
        "deleted": deleted,
    }