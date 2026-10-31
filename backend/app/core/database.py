from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# SQLite needs this flag so FastAPI can use one connection across threads.
connect_args = (
    {"check_same_thread": False}
    if settings.DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autoflush=False, autocommit=False, bind=engine)

Base = declarative_base()


def get_db():
    """Give each request its own database session, then close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
