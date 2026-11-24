"""Bug comments (FR-09)."""

from fastapi import APIRouter, status

from app.core.deps import CurrentUser, DbSession
from app.schemas.comment import CommentCreate, CommentRead
from app.services import comment_service
from app.services.access import bug_access

router = APIRouter(prefix="/bugs/{bug_id}/comments", tags=["comments"])


@router.get("", response_model=list[CommentRead], summary="Comments, oldest first")
def list_comments(bug_id: int, user: CurrentUser, db: DbSession) -> list[CommentRead]:
    bug, _ = bug_access(db, user, bug_id)
    return [CommentRead.model_validate(c) for c in comment_service.list_comments(db, bug.id)]


@router.post(
    "", response_model=CommentRead, status_code=status.HTTP_201_CREATED, summary="Add a comment"
)
def add_comment(bug_id: int, data: CommentCreate, user: CurrentUser, db: DbSession) -> CommentRead:
    bug, _ = bug_access(db, user, bug_id, write=True)
    return CommentRead.model_validate(comment_service.add_comment(db, bug, user, data.body))
