"""FastAPI app. Run it with:  uvicorn app.main:app --reload  (from the backend/ folder)."""

from itertools import count

from fastapi import FastAPI

from app.schemas import BugCreate, BugOut
from app.severity import classify_severity

app = FastAPI(title="AI-Powered Bug Tracking System")

# Temporary id counter for the skeleton.
# TODO(#11, MohammedAfSaleh): replace with a `bugs` table in PostgreSQL (see .env.example).
_next_id = count(1)


@app.get("/health")
def health() -> dict[str, str]:
    """Quick check that the server is running."""
    return {"status": "ok"}


@app.post("/bugs", response_model=BugOut, status_code=201)
def create_bug(bug: BugCreate) -> BugOut:
    """Receive a bug from the VS Code form and return it with a severity label."""
    severity = classify_severity(bug.title, bug.description)
    # TODO(#11, MohammedAfSaleh): save the bug (with its severity) to the database
    #   and return the id the database gives it.
    return BugOut(id=next(_next_id), title=bug.title, description=bug.description, severity=severity)
