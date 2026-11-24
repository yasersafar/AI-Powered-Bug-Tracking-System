"""Flat, chronological bug comments (FR-09)."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Bug, Comment, User


def list_comments(db: Session, bug_id: int) -> Sequence[Comment]:
    return db.scalars(
        select(Comment)
        .where(Comment.bug_id == bug_id)
        .options(selectinload(Comment.author))
        .order_by(Comment.created_at, Comment.id)
    ).all()


def add_comment(db: Session, bug: Bug, author: User, body: str) -> Comment:
    comment = Comment(bug_id=bug.id, author_id=author.id, body=body)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment
