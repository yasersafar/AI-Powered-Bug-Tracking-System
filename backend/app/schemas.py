"""Request and response shapes for the API (Pydantic models)."""

from pydantic import BaseModel, Field


class BugCreate(BaseModel):
    """What the VS Code form sends to POST /bugs."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    # TODO(#10/#11): add more fields when the form has them (steps to reproduce, project, ...).


class BugOut(BaseModel):
    """What POST /bugs sends back to the extension."""

    id: int
    title: str
    description: str
    severity: str
