from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from .models import Base
from app.config import CONFIG


def _normalize_db_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url

if CONFIG.ENVIRONMENT.lower() == "production":
    SQLALCHEMY_DATABASE_URL = _normalize_db_url(CONFIG.DB_URL)
else:
    SQLALCHEMY_DATABASE_URL = "sqlite:///./database.db"

IS_SQLITE = SQLALCHEMY_DATABASE_URL.startswith("sqlite")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
    pool_pre_ping=not IS_SQLITE,
    pool_recycle=-1 if IS_SQLITE else 300,
    **({} if IS_SQLITE else {"pool_size": 20, "max_overflow": 20}),
)

# Shows in the server log which database is in use (never prints credentials).
print(f"[database] using {engine.url.get_backend_name()}")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _ensure_columns():
    """create_all() only creates missing tables, never missing columns. Add new columns here."""
    inspector = inspect(engine)
    if "assignments" in inspector.get_table_names():
        existing = {c["name"] for c in inspector.get_columns("assignments")}
        if "grading_criteria" not in existing:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE assignments ADD COLUMN grading_criteria TEXT"))


def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()