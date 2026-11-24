from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.common import UserSummary


class AttachmentRead(BaseModel):
    """A file attached to a bug (FR-14). Downloaded through its own endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    bug_id: int
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    uploader: UserSummary | None
    created_at: datetime
