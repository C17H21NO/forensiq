from types import SimpleNamespace

import mimetypes
import time
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.services.ocr_service import is_tesseract_available
from app.services.upload_validation import validate_upload_file
from app.services.reference_file_service import (
    resolve_reference_file,
    reference_storage_status,
    delete_reference_file,
)
from app.services.storage_service import storage
from app.services.contextual_evidence import (
    build_contextual_evidence,
    
    mask_text_for_response,
)
from app.config import settings
from app.services.nlp_entity_service import (
    detect_spacy_entities,
    is_spacy_available,
    
)
from app.security_policy import (
    USER_MANAGEMENT_ROLES,
    REFERENCE_MANAGEMENT_ROLES,
    HISTORY_MANAGEMENT_ROLES,
    DOCUMENT_ANALYSIS_ROLES,
    MATCHING_ROLES,
    REFERENCE_READ_ROLES,
    HISTORY_READ_ROLES,
    SYSTEM_INFORMATION_ROLES,
    EXPERIMENTAL_ROLES,
)
from app.database import get_db
from app.services.reference_repository import (
    save_reference_document_db,
    list_reference_documents_db,
    clear_reference_documents_db,
    delete_reference_document_db,
    get_reference_document_db,
    update_reference_storage_metadata_db,
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
from app.services.fingerprint import (
    build_fingerprint,
    build_production_fingerprint,
)
from app.services.matcher import (
    add_reference_document,
    list_reference_documents,
    clear_reference_index,
    match_against_references,
    match_against_references_production,
    get_reference_document_by_id,
)
from app.services.evaluation import (
    run_evaluation,
    run_evaluation_summary_only,
    save_evaluation_summary_to_file,
)
from app.services.variant_generator import generate_variant_from_pdf

from app.models import UserDB
from app.services.auth_service import (
    create_access_token,
    decode_access_token,
    verify_password,
    hash_password,
    password_hash_needs_upgrade,
)
from app.services.user_repository import (
    create_user,
    get_user_by_username,
    list_users,
    serialize_user,
    update_user_password_hash,
)
from fastapi.responses import JSONResponse

from app.logging_config import (
    configure_logging,
    get_logger,
)

from app.services.health_service import (
    run_readiness_checks,
)
configure_logging()

logger = get_logger(
    "forensiq.api"
)

# === FORENSIQ_VISUAL_API_SUMMARY_PATCH ===
# Human-readable visual/layout summary for analyst-facing responses.

def summarize_visual_layout(layout_blocks, fingerprint=None):
    """
    Resume únicamente la evidencia visual/estructural del documento.

    Este resumen no participa en el ranking Top-k.
    Se presenta como información auxiliar para la revisión humana.
    """

    layout_blocks = layout_blocks or []

    text_blocks = [
        block
        for block in layout_blocks
        if block.get("block_type", "text") == "text"
    ]

    graphic_blocks = [
        block
        for block in layout_blocks
        if block.get("block_type") == "graphic"
    ]

    image_blocks = [
        block
        for block in layout_blocks
        if block.get("block_type") == "image"
    ]

    visual_blocks = graphic_blocks + image_blocks

    layout_features = {}

    if fingerprint:
        layout_features = (
            fingerprint.get("layout_features", {}) or {}
        )

    visual_to_text_ratio = layout_features.get(
        "visual_to_text_ratio",
        len(visual_blocks) / max(len(text_blocks), 1),
    )

    visual_area = layout_features.get(
        "visual_area",
        sum(
            float(block.get("area", 0.0))
            for block in visual_blocks
        ),
    )

    if image_blocks and len(text_blocks) <= 2:
        visual_condition_code = "scan_like"

        visual_condition = (
            "El documento presenta características compatibles con contenido "
            "rasterizado o escaneado. Parte de la información visual puede "
            "encontrarse contenida dentro de una imagen."
        )

    elif len(visual_blocks) >= 10:
        visual_condition_code = "visual_enriched"

        visual_condition = (
            "Se detectó una cantidad relevante de elementos visuales o "
            "gráficos en el documento."
        )

    elif len(visual_blocks) > 0:
        visual_condition_code = "some_visual_elements"

        visual_condition = (
            "Se detectaron algunos elementos visuales o gráficos en el "
            "documento."
        )

    else:
        visual_condition_code = "no_relevant_visual_elements"

        visual_condition = (
            "No se detectaron elementos visuales o gráficos relevantes. "
            "La información estructural disponible se conserva únicamente "
            "como evidencia auxiliar."
        )

    return {
        "layout_block_count": len(layout_blocks),
        "text_block_count": len(text_blocks),
        "graphic_block_count": len(graphic_blocks),
        "image_block_count": len(image_blocks),
        "visual_block_count": len(visual_blocks),

        "visual_to_text_ratio": round(
            float(visual_to_text_ratio),
            4,
        ),

        "visual_area": round(
            float(visual_area),
            4,
        ),

        "layout_feature_count": len(layout_features),

        "visual_condition_code": visual_condition_code,
        "visual_condition": visual_condition,

        "evidence_role": "auxiliary",
        "affects_ranking": False,
    }


def explain_match_scores(scores):
    """
    Genera una explicación coherente con el modelo productivo OE3.

    El ranking se determina exclusivamente mediante similitud textual.
    Layout y PII se muestran como evidencia auxiliar/contextual y no
    modifican la posición del candidato.
    """

    scores = scores or {}

    ranking_score = float(
        scores.get(
            "ranking_score",
            scores.get("pii_context_score", scores.get("pii_score", 0.0))
        )
        or 0.0
    )

    layout_score = float(
        scores.get("layout_score", 0.0) or 0.0
    )

    pii_context_score = float(
        scores.get(
            "pii_context_score",
            scores.get("pii_score", 0.0),
        )
        or 0.0
    )

    if ranking_score >= 0.75:
        explanation = (
            "El candidato presenta una similitud textual alta con el "
            "documento sospechoso."
        )
        level = "high"

    elif ranking_score >= 0.50:
        explanation = (
            "El candidato presenta una similitud textual moderada con el "
            "documento sospechoso."
        )
        level = "medium"

    elif ranking_score >= 0.25:
        explanation = (
            "El candidato presenta una similitud textual limitada con el "
            "documento sospechoso."
        )
        level = "low"

    else:
        explanation = (
            "El candidato presenta una similitud textual baja con el "
            "documento sospechoso."
        )
        level = "very_low"

    return {
        # Campos productivos
        "ranking_basis": "text",
        "ranking_score": round(ranking_score, 4),
        "similarity_level": level,
        "explanation": explanation,

        "auxiliary_evidence": {
            "layout_score": round(layout_score, 4),
            "pii_context_score": round(pii_context_score, 4),
        },

        "auxiliary_note": (
            "La similitud estructural y la coincidencia de PII se presentan "
            "como información auxiliar para la revisión humana y no modifican "
            "el orden del ranking."
        ),

        # Compatibilidad temporal con el frontend TP1.
        "dominant_signal": "texto",
        "dominant_score": round(ranking_score, 4),
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



class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    full_name: str
    role: str
    password: str


ROLE_DESCRIPTIONS = {
    "ADMIN": "Administra usuarios, referencias, corpus sintético, evaluaciones e historial.",
    "ANALYST": (
        "Ejecuta análisis forense y matching Top-k "
        "sobre documentos sospechosos."
    ),
    "DPO": "Revisa historial, PII detectada y riesgos de identidad sin administrar el índice.",
}

security = HTTPBearer(auto_error=False)
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> UserDB:
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="No autenticado.",
        )

    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Esquema de autenticación inválido.",
        )

    token = credentials.credentials

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail="Token inválido o expirado.",
        )

    username = payload.get("sub")

    user = get_user_by_username(
        db,
        username or "",
    )

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="Usuario no válido o inactivo.",
        )

    return user


def require_roles(*allowed_roles: str):
    allowed = {role.upper() for role in allowed_roles}

    def dependency(current_user: UserDB = Depends(get_current_user)) -> UserDB:
        if current_user.role.upper() not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Acceso denegado. Rol requerido: {', '.join(sorted(allowed))}.",
            )
        return current_user

    return dependency
def rebuild_production_reference_index(
    db: Session,
) -> dict:
    """
    Reconstruye el índice productivo OE3 desde la base de datos.

    Prioridad de archivo físico:
        1. storage_key
        2. stored_path legacy como fallback

    Contrato productivo:
        - Texto: ranking.
        - Layout: evidencia auxiliar.
        - PII: contexto.
        - SBERT: no se ejecuta.
    """

    clear_reference_index()

    documents = list_reference_documents_db(db)

    loaded = 0
    layout_unavailable = 0
    storage_key_used = 0
    legacy_fallback_used = 0
    missing_files = 0

    for document in documents:
        text = document.get("text") or ""

        pii_entities = (
            document.get("pii_entities")
            or detect_pii_masked(text)
        )

        layout_blocks = []

        # -------------------------------------------------------------
        # El repository actual devuelve diccionarios.
        # Para resolver storage necesitamos el objeto ORM.
        # -------------------------------------------------------------
        orm_document = get_reference_document_db(
            db,
            document.get("document_id", ""),
        )

        reference_path = None
        resolved_via = None

        if orm_document is not None:
            try:
                (
                    reference_path,
                    resolved_via,
                ) = resolve_reference_file(
                    orm_document
                )

            except FileNotFoundError:
                reference_path = None
                resolved_via = None

        # -------------------------------------------------------------
        # Evidencia estructural auxiliar
        # -------------------------------------------------------------
        if reference_path is not None:
            try:
                layout_blocks = extract_layout_blocks(
                    str(reference_path)
                )

            except Exception:
                layout_unavailable += 1
                layout_blocks = []

        else:
            layout_unavailable += 1
            missing_files += 1

        if resolved_via == "storage_key":
            storage_key_used += 1

        elif resolved_via == "stored_path_legacy":
            legacy_fallback_used += 1

        # -------------------------------------------------------------
        # Huella productiva
        # -------------------------------------------------------------
        fingerprint = build_production_fingerprint(
            text,
            pii_entities,
            layout_blocks,
        )

        # -------------------------------------------------------------
        # Incorporamos metadatos seguros de storage al índice RAM.
        # stored_path se mantiene temporalmente por compatibilidad.
        # -------------------------------------------------------------
        storage_metadata = {}

        if orm_document is not None:
            storage_metadata = {
                "storage_key": orm_document.storage_key,
                "sha256": orm_document.sha256,
                "size_bytes": orm_document.size_bytes,
                "mime_type": orm_document.mime_type,
            }

        production_document = {
            **document,
            **storage_metadata,

            "text": text,
            "text_length": len(text),

            "pii_entities": pii_entities,
            "pii_count": len(pii_entities),

            "fingerprint": fingerprint,
        }

        add_reference_document(
            production_document
        )

        loaded += 1

    return {
        "total_in_db": len(documents),
        "loaded": loaded,

        "layout_unavailable": layout_unavailable,

        "storage_key_used": storage_key_used,
        "legacy_fallback_used": legacy_fallback_used,
        "missing_files": missing_files,
    }
app = FastAPI(
    title=settings.app_name,
    description=(
        "API de soporte al análisis forense documental mediante "
        "ranking Top-k y evidencia contextual."
    ),
    version=settings.app_version,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.on_event("startup")
def on_startup():
    from app.database import SessionLocal

    db = SessionLocal()

    try:
        reference_stats = rebuild_production_reference_index(db)

        logger.info(
            (
                "Índice productivo cargado: "
                "%s referencias | "
                "storage_key=%s | "
                "legacy=%s | "
                "missing=%s | "
                "layout_unavailable=%s"
            ),
            reference_stats["loaded"],
            reference_stats["storage_key_used"],
            reference_stats["legacy_fallback_used"],
            reference_stats["missing_files"],
            reference_stats["layout_unavailable"],
        )

    finally:
        db.close()
@app.get("/health/live")
def health_live():
    """
    Indica únicamente que el proceso FastAPI está vivo.
    """

    return {
        "status": "alive",
    }
@app.get("/health/ready")
def health_ready(
    db: Session = Depends(
        get_db
    ),
):
    """
    Indica si ForensiQ está listo para procesar solicitudes.

    Comprueba:
    - base de datos
    - almacenamiento
    - sincronización BD / índice RAM
    """

    checks = run_readiness_checks(
        db
    )

    if not checks["ready"]:
        logger.error(
            (
                "Readiness failed | "
                "database=%s | "
                "storage=%s | "
                "reference_index=%s"
            ),
            checks["database"],
            checks["storage"],
            checks["reference_index"],
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
            },
        )

    return {
        "status": "ready",
    }
@app.get("/")
def root():
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "status": "running",
    }


@app.post("/auth/login")
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    # -------------------------------------------------------------------------
    # 1. Buscar usuario
    # -------------------------------------------------------------------------
    user = get_user_by_username(
        db,
        payload.username,
    )

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="Credenciales inválidas.",
        )

    # -------------------------------------------------------------------------
    # 2. Verificar contraseña
    #
    # verify_password soporta:
    # - PBKDF2 actual
    # - SHA-256 legacy TP1 mientras esté permitida la migración
    # -------------------------------------------------------------------------
    password_is_valid = verify_password(
        payload.password,
        user.username,
        user.password_hash,
    )

    if not password_is_valid:
        raise HTTPException(
            status_code=401,
            detail="Credenciales inválidas.",
        )

    # -------------------------------------------------------------------------
    # 3. Migración transparente del hash
    #
    # Solamente ocurre DESPUÉS de verificar correctamente la contraseña.
    #
    # Nunca migramos un hash durante un login fallido.
    # -------------------------------------------------------------------------
    

    if password_hash_needs_upgrade(
        user.password_hash
    ):
        upgraded_hash = hash_password(
            payload.password
        )

        user = update_user_password_hash(
            db=db,
            user=user,
            new_password_hash=upgraded_hash,
        )

        

    # -------------------------------------------------------------------------
    # 4. Emitir token
    # -------------------------------------------------------------------------
    token = create_access_token(
        {
            "sub": user.username,
            "role": user.role,
        }
    )

    return {
        "access_token": token,
        "token_type": "bearer",

        "user": serialize_user(user),
        "roles": ROLE_DESCRIPTIONS,

        # Campo temporal útil para comprobar la migración.
        # Lo eliminaremos antes de producción.
    }

@app.get("/auth/me")
def auth_me(current_user: UserDB = Depends(get_current_user)):
    return serialize_user(current_user)


@app.get("/users")
def get_users(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(
        require_roles(*USER_MANAGEMENT_ROLES)
    ),
):
    users = list_users(db)

    return {
        "users": [
            serialize_user(user)
            for user in users
        ]
    }


@app.post("/users")
def create_app_user(
    payload: CreateUserRequest,
    current_user: UserDB = Depends(
    require_roles(*USER_MANAGEMENT_ROLES)
),
    db: Session = Depends(get_db),
):
    role = payload.role.upper().strip()
    if role not in ROLE_DESCRIPTIONS:
        raise HTTPException(status_code=400, detail="Rol inválido. Use ADMIN, ANALYST o DPO.")

    if get_user_by_username(db, payload.username) is not None:
        raise HTTPException(status_code=400, detail="El usuario ya existe.")

    user = create_user(
        db=db,
        username=payload.username,
        full_name=payload.full_name,
        role=role,
        password=payload.password,
    )
    return {"message": "Usuario creado.", "user": serialize_user(user)}



@app.post("/synthetic/generate")
def generate_synthetic_documents(n: int = 10, current_user: UserDB = Depends(
    require_roles(*EXPERIMENTAL_ROLES)
)):
    documents = generate_synthetic_pdfs(n)
    return {
        "generated": len(documents),
        "documents": documents,
    }


@app.post("/documents/analyze")
def analyze_document(
    file: UploadFile = File(...),
    current_user: UserDB = Depends(
        require_roles(
            *DOCUMENT_ANALYSIS_ROLES
        )
    ),
):
    # -------------------------------------------------------------------------
    # 1. Validar archivo
    # -------------------------------------------------------------------------
    upload_info = validate_upload_file(
        file
    )

    stored_object = None

    try:
        # ---------------------------------------------------------------------
        # 2. Almacenar mediante StorageService
        # ---------------------------------------------------------------------
        stored_object = storage.save_upload(
            upload=file,
            namespace="analysis",
        )

        stored_path = (
            stored_object.absolute_path
        )

        # ---------------------------------------------------------------------
        # 3. Extracción
        # ---------------------------------------------------------------------
        extraction = extract_text_details(
            str(stored_path)
        )

        text = extraction["text"]

        if not text or not text.strip():
            logger.exception(
                "Error inesperado procesando documents/analyze."
            )
            raise HTTPException(
                status_code=422,
                detail=(
                    "No fue posible extraer contenido textual útil "
                    "del documento."
                ),
            )

        # ---------------------------------------------------------------------
        # 4. Evidencia contextual
        # ---------------------------------------------------------------------
        pii_entities = detect_pii_masked(
            text
        )

        nlp_entities = detect_spacy_entities(
            text
        )

        contextual_evidence = (
            build_contextual_evidence(
                text=text,
                pii_entities=pii_entities,
                nlp_entities=nlp_entities,
            )
        )

        safe_text_preview = (
            mask_text_for_response(
                text=text,
                pii_entities=pii_entities,
            )
        )

        # ---------------------------------------------------------------------
        # 5. Evidencia estructural auxiliar
        # ---------------------------------------------------------------------
        layout_blocks = (
            extract_layout_blocks(
                str(stored_path)
            )
        )

        # ---------------------------------------------------------------------
        # 6. Huella productiva
        # ---------------------------------------------------------------------
        fingerprint = (
            build_production_fingerprint(
                text,
                pii_entities,
                layout_blocks,
            )
        )

        return {
            "filename": (
                upload_info[
                    "original_filename"
                ]
            ),

            "stored_filename": (
                stored_object.stored_filename
            ),

            "file_info": {
                "extension": (
                    upload_info["extension"]
                ),

                "size_bytes": (
                    stored_object.size_bytes
                ),

                "size_mb": round(
                    stored_object.size_bytes
                    / (1024 * 1024),
                    4,
                ),

                "sha256": (
                    stored_object.sha256
                ),
            },

            "text_length": len(text),

            "text_preview": (
                safe_text_preview[:1200]
            ),

            "pii_count": (
                contextual_evidence[
                    "pii"
                ]["count"]
            ),

            "contextual_evidence": (
                contextual_evidence
            ),

            "layout_block_count": (
                len(layout_blocks)
            ),

            "fingerprint_summary": (
                fingerprint["summary"]
            ),

            "visual_summary": (
                summarize_visual_layout(
                    layout_blocks,
                    fingerprint,
                )
            ),

            "nlp_entity_count": (
                len(nlp_entities)
            ),

            "extraction_mode": (
                extraction[
                    "extraction_mode"
                ]
            ),

            "ocr_used": (
                extraction["ocr_used"]
            ),

            "ocr_available": (
                extraction[
                    "ocr_available"
                ]
            ),
        }

    except HTTPException:
        # Análisis fallido:
        # no conservamos un archivo que no pudo procesarse.
        if stored_object is not None:
            try:
                storage.delete(
                    stored_object.storage_key
                )
            except Exception:
                pass

        raise

    except Exception as exc:
        if stored_object is not None:
            try:
                storage.delete(
                    stored_object.storage_key
                )
            except Exception:
                pass

        raise HTTPException(
            status_code=500,
            detail=(
                "Ocurrió un error durante "
                "el análisis del documento."
            ),
        ) from exc
@app.post("/references/upload")
def upload_reference_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(
        require_roles(
            *REFERENCE_MANAGEMENT_ROLES
        )
    ),
):
    # -------------------------------------------------------------------------
    # 1. Validar archivo
    # -------------------------------------------------------------------------
    upload_info = validate_upload_file(
        file
    )

    original_filename = upload_info[
        "original_filename"
    ]

    if original_filename.upper().startswith(
        "VARIANT_"
    ):
        logger.exception(
            "Error inesperado procesando references/upload."
        )
        raise HTTPException(
            status_code=400,
            detail=(
                "El archivo parece ser una variante sospechosa. "
                "Las variantes no deben cargarse como documentos "
                "legítimos de referencia."
            ),
        )

    stored_object = None
    document_id = None
    db_persisted = False

    try:
        # ---------------------------------------------------------------------
        # 2. Almacenamiento mediante StorageService
        # ---------------------------------------------------------------------
        stored_object = storage.save_upload(
            upload=file,
            namespace="references",
        )

        stored_path = (
            stored_object.absolute_path
        )

        stored_filename = (
            stored_object.stored_filename
        )

        document_id = stored_filename

        mime_type = (
            file.content_type
            or mimetypes.guess_type(
                original_filename
            )[0]
            or "application/octet-stream"
        )

        # ---------------------------------------------------------------------
        # 3. Extraer texto
        # ---------------------------------------------------------------------
        text = extract_text(
            str(stored_path)
        )

        if not text or not text.strip():
            raise HTTPException(
                status_code=422,
                detail=(
                    "No fue posible extraer contenido textual útil "
                    "del documento."
                ),
            )

        # ---------------------------------------------------------------------
        # 4. Evidencias
        # ---------------------------------------------------------------------
        pii_entities = detect_pii_masked(
            text
        )

        layout_blocks = extract_layout_blocks(
            str(stored_path)
        )

        # ---------------------------------------------------------------------
        # 5. Huella productiva OE3
        # ---------------------------------------------------------------------
        fingerprint = (
            build_production_fingerprint(
                text,
                pii_entities,
                layout_blocks,
            )
        )

        # ---------------------------------------------------------------------
        # 6. Documento interno
        #
        # stored_path se mantiene solo por compatibilidad temporal.
        # storage_key es la referencia principal.
        # ---------------------------------------------------------------------
        document = {
            "document_id": document_id,
            "filename": original_filename,

            "stored_path": str(
                stored_path
            ),

            "storage_key": (
                stored_object.storage_key
            ),

            "sha256": (
                stored_object.sha256
            ),

            "size_bytes": (
                stored_object.size_bytes
            ),

            "mime_type": mime_type,

            "text": text,
            "text_length": len(text),

            "pii_entities": pii_entities,
            "pii_count": len(
                pii_entities
            ),

            "fingerprint": fingerprint,
        }

        # ---------------------------------------------------------------------
        # 7. Persistencia
        # ---------------------------------------------------------------------
        save_reference_document_db(
            db,
            document,
        )

        db_persisted = True

        updated_document = (
            update_reference_storage_metadata_db(
                db=db,
                document_id=document_id,
                storage_key=(
                    stored_object.storage_key
                ),
                sha256=(
                    stored_object.sha256
                ),
                size_bytes=(
                    stored_object.size_bytes
                ),
                mime_type=mime_type,
            )
        )

        if updated_document is None:
            raise RuntimeError(
                "No fue posible actualizar los "
                "metadatos de almacenamiento."
            )

        # Solo después de persistir correctamente
        # incorporamos el documento al índice RAM.
        add_reference_document(
            document
        )

        return {
            "message": (
                "Documento legítimo agregado "
                "al índice de referencia."
            ),

            "document_id": document_id,
            "filename": original_filename,

            "file_info": {
                "extension": (
                    upload_info["extension"]
                ),

                "size_bytes": (
                    stored_object.size_bytes
                ),

                "size_mb": round(
                    stored_object.size_bytes
                    / (1024 * 1024),
                    4,
                ),

                "mime_type": mime_type,
                "sha256": (
                    stored_object.sha256
                ),
            },

            "storage": {
                "storage_key": (
                    stored_object.storage_key
                ),

                "file_available": True,
                "resolved_via": (
                    "storage_key"
                ),
            },

            "text_length": len(text),

            "pii_count": len(
                pii_entities
            ),

            "fingerprint_summary": (
                fingerprint["summary"]
            ),

            "ranking_model": (
                fingerprint.get(
                    "ranking_model"
                )
            ),

            "evidence_roles": (
                fingerprint.get(
                    "evidence_roles"
                )
            ),
        }

    except HTTPException:
        # -------------------------------------------------------------
        # Rollback lógico si ya se había persistido.
        # -------------------------------------------------------------
        if (
            db_persisted
            and document_id
        ):
            try:
                delete_reference_document_db(
                    db,
                    document_id,
                )
            except Exception:
                pass

        # -------------------------------------------------------------
        # Limpieza física segura.
        # -------------------------------------------------------------
        if stored_object is not None:
            try:
                storage.delete(
                    stored_object.storage_key
                )
            except Exception:
                pass

        raise

    except Exception as exc:
        if (
            db_persisted
            and document_id
        ):
            try:
                delete_reference_document_db(
                    db,
                    document_id,
                )
            except Exception:
                pass

        if stored_object is not None:
            try:
                storage.delete(
                    stored_object.storage_key
                )
            except Exception:
                pass

        raise HTTPException(
            status_code=500,
            detail=(
                "Ocurrió un error al procesar "
                "el documento de referencia."
            ),
        ) from exc
@app.get("/references")
def get_references(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(
        require_roles(
            *REFERENCE_READ_ROLES
        )
    ),
):
    references = list_reference_documents()

    documents = []

    for ref in references:
        text = ref.get(
            "text",
            "",
        )

        pii_entities = ref.get(
            "pii_entities",
            [],
        )

        text_length = ref.get(
            "text_length"
        )

        if text_length is None:
            text_length = len(text)

        pii_count = ref.get(
            "pii_count"
        )

        if pii_count is None:
            pii_count = len(
                pii_entities
            )

        fingerprint = ref.get(
            "fingerprint",
            {},
        )

        fingerprint_summary = (
            fingerprint.get(
                "summary",
                {},
            )
        )

        document_id = ref.get(
            "document_id"
        )

        orm_document = (
            get_reference_document_db(
                db,
                document_id or "",
            )
        )

        if orm_document is not None:
            storage_info = (
                reference_storage_status(
                    orm_document
                )
            )

        else:
            storage_info = {
                "storage_key": None,
                "sha256": None,
                "size_bytes": None,
                "mime_type": None,
                "file_available": False,
                "resolved_via": None,
            }

        documents.append(
            {
                "document_id": document_id,

                "filename": ref.get(
                    "filename"
                ),

                "text_length": text_length,

                "pii_count": pii_count,

                "fingerprint_summary": (
                    fingerprint_summary
                ),

                "storage": storage_info,
            }
        )

    return {
        "total": len(references),
        "documents": documents,
    }
@app.delete("/references/{document_id}")
def delete_reference_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(
        require_roles(
            *REFERENCE_MANAGEMENT_ROLES
        )
    ),
):
    # -------------------------------------------------------------------------
    # 1. Recuperar referencia antes de eliminarla.
    # -------------------------------------------------------------------------
    orm_document = (
        get_reference_document_db(
            db,
            document_id,
        )
    )

    if orm_document is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Documento de referencia "
                "no encontrado."
            ),
        )

    # Creamos un snapshot desacoplado del ORM.
    # Así el commit/delete de SQLAlchemy no afecta
    # los datos que necesitamos para limpiar storage.
    cleanup_snapshot = SimpleNamespace(
        document_id=(
            orm_document.document_id
        ),

        storage_key=(
            orm_document.storage_key
        ),

        stored_path=(
            orm_document.stored_path
        ),
    )

    deleted_filename = (
        orm_document.filename
    )

    # -------------------------------------------------------------------------
    # 2. Eliminar registro de BD.
    # -------------------------------------------------------------------------
    deleted_document = (
        delete_reference_document_db(
            db,
            document_id,
        )
    )

    if deleted_document is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Documento de referencia "
                "no encontrado."
            ),
        )

    # -------------------------------------------------------------------------
    # 3. Limpiar almacenamiento físico.
    #
    # storage_key es prioritario.
    # stored_path solo actúa como fallback legacy.
    # -------------------------------------------------------------------------
    try:
        file_cleanup = (
            delete_reference_file(
                cleanup_snapshot
            )
        )

    except Exception:
        file_cleanup = {
            "deleted": False,
            "source": None,
        }

    # -------------------------------------------------------------------------
    # 4. Reconstruir índice RAM.
    # -------------------------------------------------------------------------
    stats = (
        rebuild_production_reference_index(
            db
        )
    )

    return {
        "message": (
            "Documento de referencia eliminado."
        ),

        "deleted_document_id": (
            document_id
        ),

        "deleted_filename": (
            deleted_filename
        ),

        "file_cleanup": (
            file_cleanup
        ),

        "remaining_references": (
            stats["loaded"]
        ),
    }
@app.delete("/references")
def clear_references(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(
        require_roles(
            *REFERENCE_MANAGEMENT_ROLES
        )
    ),
):
    # -------------------------------------------------------------------------
    # 1. Tomar snapshots antes de eliminar la BD.
    # -------------------------------------------------------------------------
    db_documents = (
        list_reference_documents_db(
            db
        )
    )

    cleanup_snapshots = []

    for document in db_documents:
        orm_document = (
            get_reference_document_db(
                db,
                document.get(
                    "document_id",
                    "",
                ),
            )
        )

        if orm_document is None:
            continue

        cleanup_snapshots.append(
            SimpleNamespace(
                document_id=(
                    orm_document.document_id
                ),

                storage_key=(
                    orm_document.storage_key
                ),

                stored_path=(
                    orm_document.stored_path
                ),
            )
        )

    # -------------------------------------------------------------------------
    # 2. Limpiar BD.
    # -------------------------------------------------------------------------
    deleted_from_db = (
        clear_reference_documents_db(
            db
        )
    )

    clear_reference_index()

    # -------------------------------------------------------------------------
    # 3. Limpiar archivos administrados.
    # -------------------------------------------------------------------------
    files_deleted = 0
    files_not_deleted = 0

    for snapshot in cleanup_snapshots:
        try:
            result = (
                delete_reference_file(
                    snapshot
                )
            )

            if result.get(
                "deleted"
            ):
                files_deleted += 1

            else:
                files_not_deleted += 1

        except Exception:
            files_not_deleted += 1

    return {
        "message": (
            "Índice de referencias limpiado."
        ),

        "deleted_from_memory": True,
        "deleted_from_db": (
            deleted_from_db
        ),

        "storage_cleanup": {
            "files_deleted": (
                files_deleted
            ),

            "files_not_deleted": (
                files_not_deleted
            ),
        },
    }
@app.post("/documents/match")
def match_suspicious_document(
    file: UploadFile = File(...),
    top_k: int = 5,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(
        require_roles(
            *MATCHING_ROLES
        )
    ),
):
    start_time = time.perf_counter()

    # -------------------------------------------------------------------------
    # 1. Validaciones
    # -------------------------------------------------------------------------
    if top_k < 1 or top_k > 20:
        logger.exception(
            "Error inesperado procesando documents/match."
        )
        raise HTTPException(
            status_code=400,
            detail=(
                "top_k debe estar entre 1 y 20."
            ),
        )

    upload_info = validate_upload_file(
        file
    )

    stored_object = None

    try:
        # ---------------------------------------------------------------------
        # 2. Storage
        # ---------------------------------------------------------------------
        stored_object = storage.save_upload(
            upload=file,
            namespace="analysis",
        )

        stored_path = (
            stored_object.absolute_path
        )

        # ---------------------------------------------------------------------
        # 3. Extracción
        # ---------------------------------------------------------------------
        extraction = extract_text_details(
            str(stored_path)
        )

        text = extraction["text"]

        if not text or not text.strip():
            raise HTTPException(
                status_code=422,
                detail=(
                    "No fue posible extraer contenido textual útil "
                    "del documento."
                ),
            )

        # ---------------------------------------------------------------------
        # 4. Evidencia contextual
        # ---------------------------------------------------------------------
        pii_entities = detect_pii_masked(
            text
        )

        nlp_entities = detect_spacy_entities(
            text
        )

        contextual_evidence = (
            build_contextual_evidence(
                text=text,
                pii_entities=pii_entities,
                nlp_entities=nlp_entities,
            )
        )

        safe_text_preview = (
            mask_text_for_response(
                text=text,
                pii_entities=pii_entities,
            )
        )

        # ---------------------------------------------------------------------
        # 5. Evidencia estructural auxiliar
        # ---------------------------------------------------------------------
        layout_blocks = (
            extract_layout_blocks(
                str(stored_path)
            )
        )

        # ---------------------------------------------------------------------
        # 6. Huella productiva
        # ---------------------------------------------------------------------
        fingerprint = (
            build_production_fingerprint(
                text,
                pii_entities,
                layout_blocks,
            )
        )

        # ---------------------------------------------------------------------
        # 7. Ranking Top-k
        # ---------------------------------------------------------------------
        matches = (
            match_against_references_production(
                fingerprint,
                top_k=top_k,
            )
        )

        enriched_matches = (
            enrich_matches_for_analyst(
                matches
            )
        )

        latency_ms = (
            time.perf_counter()
            - start_time
        ) * 1000

        # ---------------------------------------------------------------------
        # 8. Resultado seguro
        # ---------------------------------------------------------------------
        result = {
            "filename": (
                upload_info[
                    "original_filename"
                ]
            ),

            "stored_filename": (
                stored_object.stored_filename
            ),

            "file_info": {
                "extension": (
                    upload_info["extension"]
                ),

                "size_bytes": (
                    stored_object.size_bytes
                ),

                "size_mb": round(
                    stored_object.size_bytes
                    / (1024 * 1024),
                    4,
                ),

                "sha256": (
                    stored_object.sha256
                ),
            },

            "text_length": len(text),

            "text_preview": (
                safe_text_preview[:1200]
            ),

            "extraction_mode": (
                extraction[
                    "extraction_mode"
                ]
            ),

            "ocr_used": (
                extraction["ocr_used"]
            ),

            "ocr_available": (
                extraction[
                    "ocr_available"
                ]
            ),

            "pii_count": (
                contextual_evidence[
                    "pii"
                ]["count"]
            ),

            "contextual_evidence": (
                contextual_evidence
            ),

            "nlp_entity_count": (
                len(nlp_entities)
            ),

            "layout_block_count": (
                len(layout_blocks)
            ),

            "visual_summary": (
                summarize_visual_layout(
                    layout_blocks,
                    fingerprint,
                )
            ),

            "fingerprint_summary": (
                fingerprint["summary"]
            ),

            "ranking_model": (
                fingerprint.get(
                    "ranking_model"
                )
            ),

            "evidence_roles": (
                fingerprint.get(
                    "evidence_roles"
                )
            ),

            "top_k": top_k,

            "returned_candidates": (
                len(enriched_matches)
            ),

            "latency_ms": round(
                latency_ms,
                2,
            ),

            "matches": (
                enriched_matches
            ),
        }

        # ---------------------------------------------------------------------
        # 9. Historial
        # ---------------------------------------------------------------------
        save_analysis_history_db(
            db,
            result,
            latency_ms=latency_ms,
        )

        return result

    except HTTPException:
        if stored_object is not None:
            try:
                storage.delete(
                    stored_object.storage_key
                )
            except Exception:
                pass

        raise

    except Exception as exc:
        if stored_object is not None:
            try:
                storage.delete(
                    stored_object.storage_key
                )
            except Exception:
                pass

        raise HTTPException(
            status_code=500,
            detail=(
                "Ocurrió un error durante "
                "el procesamiento del documento."
            ),
        ) from exc
    
@app.post("/synthetic/variant")
def generate_suspicious_variant(
    file: UploadFile = File(...),
    transformation_type: str = "combined",
    current_user: UserDB = Depends(
        require_roles(
            *EXPERIMENTAL_ROLES
        )
    ),
):
    upload_info = validate_upload_file(
        file
    )

    stored_object = None

    try:
        stored_object = storage.save_upload(
            upload=file,
            namespace="temporary",
        )

        variant = generate_variant_from_pdf(
            str(
                stored_object.absolute_path
            ),
            transformation_type=(
                transformation_type
            ),
        )

        return {
            "message": (
                "Variante sospechosa generada."
            ),

            "source_uploaded_filename": (
                upload_info[
                    "original_filename"
                ]
            ),

            "transformation_type": (
                transformation_type
            ),

            "variant": variant,
        }

    finally:
        # El archivo fuente solo era necesario
        # para generar la variante.
        if stored_object is not None:
            try:
                storage.delete(
                    stored_object.storage_key
                )
            except Exception:
                pass
@app.get("/system/capabilities")
def get_system_capabilities(
    current_user: UserDB = Depends(
        require_roles(*SYSTEM_INFORMATION_ROLES)
    )
):
    return {
        "backend": "active",

        "production_pipeline": {
            "ranking_model": "lexical_text_similarity_v1",

            "text_representation": (
                "normalized_term_frequency_with_cosine_similarity"
            ),

            "ranking_basis": "text",

            "layout_role": "auxiliary_evidence",
            "pii_role": "context_only",

            "semantic_embeddings_used": False,
            "weighted_multimodal_fusion_used": False,

            "automatic_match_decision": False,
            "output_type": "top_k_candidate_ranking",
        },

        "document_processing": {
            "text_extraction": "direct_text_with_ocr_fallback",
            "ocr_tesseract_available": is_tesseract_available(),

            "layout_extraction": (
                "pymupdf_text_blocks_plus_visual_graphics"
            ),

            "visual_descriptor": (
                "pymupdf_graphic_objects_density_grid"
            ),
        },

        "contextual_analysis": {
            "pii_detector": "regex_rules",
            "pii_affects_ranking": False,

            "spacy_available": is_spacy_available(),
            "spacy_model": "es_core_news_sm",
        },

        "experimental_features": {
            "available_to_admin": True,
            "used_by_production_ranking": False,
        },
    }
@app.post("/evaluation/run")
def run_experimental_evaluation(
    current_user: UserDB = Depends(
        require_roles(*EXPERIMENTAL_ROLES)
    )
):
    return run_evaluation()

@app.post("/references/bootstrap-synthetic")
def bootstrap_synthetic_references(
    n: int = 30,
    clear_existing: bool = False,
    confirm_clear: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(
        require_roles(
            *EXPERIMENTAL_ROLES
        )
    ),
):
    # -------------------------------------------------------------------------
    # 1. Validaciones
    # -------------------------------------------------------------------------
    if n < 1 or n > 500:
        raise HTTPException(
            status_code=400,
            detail=(
                "n debe estar entre 1 y 500."
            ),
        )

    # El corpus jamás se borra simplemente por un boolean.
    if clear_existing:
        if (
            confirm_clear
            != "DELETE_REFERENCE_CORPUS"
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Para eliminar el corpus actual debe "
                    "enviar confirm_clear="
                    "DELETE_REFERENCE_CORPUS."
                ),
            )

        # -------------------------------------------------------------
        # Tomar snapshots antes de borrar.
        # -------------------------------------------------------------
        db_documents = (
            list_reference_documents_db(
                db
            )
        )

        cleanup_snapshots = []

        for document in db_documents:
            orm_document = (
                get_reference_document_db(
                    db,
                    document.get(
                        "document_id",
                        "",
                    ),
                )
            )

            if orm_document is None:
                continue

            cleanup_snapshots.append(
                SimpleNamespace(
                    document_id=(
                        orm_document.document_id
                    ),
                    storage_key=(
                        orm_document.storage_key
                    ),
                    stored_path=(
                        orm_document.stored_path
                    ),
                )
            )

        clear_reference_documents_db(
            db
        )

        clear_reference_index()

        for snapshot in cleanup_snapshots:
            try:
                delete_reference_file(
                    snapshot
                )
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # 2. Generar documentos sintéticos
    # -------------------------------------------------------------------------
    generated_documents = (
        generate_synthetic_pdfs(
            n
        )
    )

    added_documents = []

    for generated in generated_documents:
        generated_path = generated[
            "path"
        ]

        original_filename = generated[
            "filename"
        ]

        stored_object = None
        document_id = None
        db_persisted = False

        try:
            # -------------------------------------------------------------
            # 3. Incorporar archivo generado a StorageService
            # -------------------------------------------------------------
            stored_object = (
                storage.save_local_file(
                    source_path=(
                        generated_path
                    ),
                    namespace="references",
                )
            )

            document_id = (
                stored_object.stored_filename
            )

            mime_type = (
                mimetypes.guess_type(
                    original_filename
                )[0]
                or "application/pdf"
            )

            # -------------------------------------------------------------
            # 4. Extracción / fingerprint
            # -------------------------------------------------------------
            text = extract_text(
                str(
                    stored_object.absolute_path
                )
            )

            if (
                not text
                or not text.strip()
            ):
                raise RuntimeError(
                    "El documento sintético "
                    "no contiene texto útil."
                )

            pii_entities = (
                detect_pii_masked(
                    text
                )
            )

            layout_blocks = (
                extract_layout_blocks(
                    str(
                        stored_object.absolute_path
                    )
                )
            )

            fingerprint = (
                build_production_fingerprint(
                    text,
                    pii_entities,
                    layout_blocks,
                )
            )

            document = {
                "document_id": (
                    document_id
                ),

                "filename": (
                    original_filename
                ),

                # Compatibilidad temporal.
                "stored_path": str(
                    stored_object.absolute_path
                ),

                "storage_key": (
                    stored_object.storage_key
                ),

                "sha256": (
                    stored_object.sha256
                ),

                "size_bytes": (
                    stored_object.size_bytes
                ),

                "mime_type": (
                    mime_type
                ),

                "text": text,

                "text_length": (
                    len(text)
                ),

                "pii_entities": (
                    pii_entities
                ),

                "pii_count": (
                    len(pii_entities)
                ),

                "fingerprint": (
                    fingerprint
                ),
            }

            # -------------------------------------------------------------
            # 5. Persistencia
            # -------------------------------------------------------------
            save_reference_document_db(
                db,
                document,
            )

            db_persisted = True

            updated_document = (
                update_reference_storage_metadata_db(
                    db=db,
                    document_id=(
                        document_id
                    ),
                    storage_key=(
                        stored_object.storage_key
                    ),
                    sha256=(
                        stored_object.sha256
                    ),
                    size_bytes=(
                        stored_object.size_bytes
                    ),
                    mime_type=(
                        mime_type
                    ),
                )
            )

            if updated_document is None:
                raise RuntimeError(
                    "No fue posible persistir "
                    "los metadatos storage."
                )

            add_reference_document(
                document
            )

            added_documents.append(
                {
                    "document_id": (
                        document_id
                    ),

                    "filename": (
                        original_filename
                    ),

                    "text_length": (
                        len(text)
                    ),

                    "pii_count": (
                        len(pii_entities)
                    ),

                    "storage_key": (
                        stored_object.storage_key
                    ),

                    "fingerprint_summary": (
                        fingerprint[
                            "summary"
                        ]
                    ),
                }
            )

        except Exception:
            if (
                db_persisted
                and document_id
            ):
                try:
                    delete_reference_document_db(
                        db,
                        document_id,
                    )
                except Exception:
                    pass

            if stored_object is not None:
                try:
                    storage.delete(
                        stored_object.storage_key
                    )
                except Exception:
                    pass

            raise

    return {
        "message": (
            "Corpus sintético generado y "
            "cargado al índice experimental."
        ),

        "generated": (
            len(generated_documents)
        ),

        "added_to_reference_index": (
            len(added_documents)
        ),

        "clear_existing": (
            clear_existing
        ),

        "documents": (
            added_documents
        ),
    }
@app.post("/evaluation/summary")
def run_experimental_evaluation_summary(current_user: UserDB = Depends(
    require_roles(*EXPERIMENTAL_ROLES)
)):
    return run_evaluation_summary_only()
@app.post("/evaluation/save-summary")
def save_experimental_evaluation_summary(current_user: UserDB = Depends(
    require_roles(*EXPERIMENTAL_ROLES)
)):
    return save_evaluation_summary_to_file()
@app.post("/references/{document_id}/variant")
def generate_variant_from_reference(
    document_id: str,
    transformation_type: str = "combined",
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(
        require_roles(
            *EXPERIMENTAL_ROLES
        )
    ),
):
    orm_document = (
        get_reference_document_db(
            db,
            document_id,
        )
    )

    if orm_document is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Documento de referencia "
                "no encontrado."
            ),
        )

    try:
        source_path, resolved_via = (
            resolve_reference_file(
                orm_document
            )
        )

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                "El archivo físico asociado "
                "a la referencia no está disponible."
            ),
        ) from exc

    variant = generate_variant_from_pdf(
        str(source_path),
        transformation_type=(
            transformation_type
        ),
    )

    return {
        "message": (
            "Variante sospechosa generada "
            "desde documento indexado."
        ),

        "document_id": (
            document_id
        ),

        "source_filename": (
            orm_document.filename
        ),

        "source_resolved_via": (
            resolved_via
        ),

        "transformation_type": (
            transformation_type
        ),

        "variant": variant,
    }
@app.post(
    "/references/{document_id}/variant-and-match"
)
def generate_variant_and_match_from_reference(
    document_id: str,
    transformation_type: str = "combined",
    top_k: int = 5,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(
        require_roles(
            *EXPERIMENTAL_ROLES
        )
    ),
):
    if top_k < 1 or top_k > 20:
        raise HTTPException(
            status_code=400,
            detail=(
                "top_k debe estar entre 1 y 20."
            ),
        )

    orm_document = (
        get_reference_document_db(
            db,
            document_id,
        )
    )

    if orm_document is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Documento de referencia "
                "no encontrado."
            ),
        )

    try:
        source_path, resolved_via = (
            resolve_reference_file(
                orm_document
            )
        )

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                "El archivo físico asociado "
                "a la referencia no está disponible."
            ),
        ) from exc

    variant = generate_variant_from_pdf(
        str(source_path),
        transformation_type=(
            transformation_type
        ),
    )

    text = extract_text(
        variant["variant_path"]
    )

    pii_entities = detect_pii_masked(
        text
    )

    layout_blocks = (
        extract_layout_blocks(
            variant["variant_path"]
        )
    )

    fingerprint = (
        build_production_fingerprint(
            text,
            pii_entities,
            layout_blocks,
        )
    )

    matches = (
        match_against_references_production(
            fingerprint,
            top_k=top_k,
        )
    )

    rank_position = None

    for index, match in enumerate(
        matches,
        start=1,
    ):
        if (
            match["document_id"]
            == document_id
        ):
            rank_position = index
            break

    enriched_matches = (
        enrich_matches_for_analyst(
            matches
        )
    )

    return {
        "message": (
            "Variante generada y comparada "
            "contra el índice."
        ),

        "source_document_id": (
            document_id
        ),

        "source_filename": (
            orm_document.filename
        ),

        "source_resolved_via": (
            resolved_via
        ),

        "transformation_type": (
            transformation_type
        ),

        "variant": variant,

        "text_length": len(text),

        "pii_count": len(
            pii_entities
        ),

        "layout_block_count": (
            len(layout_blocks)
        ),

        "fingerprint_summary": (
            fingerprint["summary"]
        ),

        "ranking_model": (
            fingerprint.get(
                "ranking_model"
            )
        ),

        "evidence_roles": (
            fingerprint.get(
                "evidence_roles"
            )
        ),

        "visual_summary": (
            summarize_visual_layout(
                layout_blocks,
                fingerprint,
            )
        ),

        "top_k": top_k,

        "rank_position": (
            rank_position
        ),

        "top_1_hit": (
            rank_position == 1
        ),

        "top_k_hit": (
            rank_position is not None
        ),

        "top_5_hit": (
            rank_position is not None
            and rank_position <= 5
        ),

        "matches": (
            enriched_matches
        ),
    }
@app.post("/references/load-from-db")
def load_references_from_db(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(
        require_roles(*REFERENCE_MANAGEMENT_ROLES)
    ),
):
    stats = rebuild_production_reference_index(db)

    references = list_reference_documents()

    return {
        "message": "Índice productivo de referencias reconstruido desde SQLite.",
        "ranking_model": "lexical_text_similarity_v1",
        "evidence_roles": {
            "text": "ranking",
            "layout": "auxiliary",
            "pii": "context_only",
        },
        "total": stats["loaded"],
        "layout_unavailable": stats["layout_unavailable"],
        "documents": [
            {
                "document_id": document.get("document_id"),
                "filename": document.get("filename"),
                "text_length": len(document.get("text", "")),
                "fingerprint_summary": (
                    document.get("fingerprint", {}).get("summary", {})
                ),
            }
            for document in references
        ],
    }
@app.get("/analysis/history")
def get_analysis_history(db: Session = Depends(get_db), current_user: UserDB = Depends(
    require_roles(*HISTORY_READ_ROLES)
)):
    history = list_analysis_history_db(db)

    return {
        "total": len(history),
        "items": history,
    }


@app.delete("/analysis/history")
def clear_analysis_history(db: Session = Depends(get_db), current_user: UserDB = Depends(
    require_roles(*HISTORY_MANAGEMENT_ROLES)
)):
    deleted = clear_analysis_history_db(db)

    return {
        "message": "Historial de análisis limpiado.",
        "deleted": deleted,
    }