from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base
from app.config import CONFIG


def _normalize_db_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


# The database is chosen by the ENVIRONMENT variable, so nobody has to edit this
# file (and forget to switch it back) when deploying:
#   ENVIRONMENT=production  ->  PostgreSQL from DB_URL
#   anything else           ->  local SQLite file (database.db)
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


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()