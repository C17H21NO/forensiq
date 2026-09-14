from datetime import datetime

from app.database import Base
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
)

class ReferenceDocumentDB(Base):
    __tablename__ = "reference_documents"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(String, unique=True, index=True, nullable=False)
    filename = Column(String, nullable=False)
    stored_path = Column(String, nullable=False)

    # Nuevos metadatos de almacenamiento
    storage_key = Column(String, nullable=True)
    sha256 = Column(String(64), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    mime_type = Column(String, nullable=True)

    text = Column(Text, nullable=True)
    pii_entities_json = Column(Text, nullable=True)
    fingerprint_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
class AnalysisHistoryDB(Base):
    __tablename__ = "analysis_history"

    id = Column(Integer, primary_key=True, index=True)

    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=True)

    pii_count = Column(Integer, default=0)
    latency_ms = Column(String, nullable=True)

    best_match_document_id = Column(String, nullable=True)
    best_match_filename = Column(String, nullable=True)
    best_match_score = Column(String, nullable=True)

    matches_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # ADMIN, ANALYST, DPO
    password_hash = Column(String, nullable=False)
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
