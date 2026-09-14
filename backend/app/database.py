from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings


engine_options = {}

# SQLite necesita este argumento.
# PostgreSQL u otros motores no.
if settings.database_url.startswith("sqlite"):
    engine_options["connect_args"] = {
        "check_same_thread": False,
    }


engine = create_engine(
    settings.database_url,
    **engine_options,
)


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


Base = declarative_base()


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models

    Base.metadata.create_all(
        bind=engine
    )