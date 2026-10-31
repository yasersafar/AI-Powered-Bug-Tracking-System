from fastapi import FastAPI

from app.api import auth, projects
from app.core.database import Base, engine
from app import models  # noqa: F401  (registers the tables on Base)

# Create database tables on startup.
# (In development this is enough; later this is replaced by Alembic migrations.)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AI-Powered Bug Tracking System",
    version="0.1.0",
)

app.include_router(auth.router)
app.include_router(projects.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
