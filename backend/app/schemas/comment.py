from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import MultiLine, UserSummary


class CommentCreate(BaseModel):
    """A new comment (FR-09)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"body": "Reproduced on v3.8.1; the stack trace is attached."}]
        },
    )

    body: Annotated[MultiLine, Field(min_length=1, max_length=10000)]


class CommentRead(BaseModel):
    """A comment with its author and time."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    bug_id: int
    author: UserSummary | None
    body: str
    created_at: datetime
