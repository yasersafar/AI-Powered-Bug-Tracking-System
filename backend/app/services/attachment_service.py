"""Bug attachments (FR-14, NFR-07).

* Size is enforced while streaming (never trusts Content-Length).
* The real type is detected from the bytes with libmagic and checked against an allow-list;
  the client's declared type and the file extension are ignored.
* Files are stored under a random 32-hex-character key inside `attachment_dir`. The user's file
  name is only kept as metadata, so path traversal is impossible by construction.
"""

import hashlib
import os
import re
import secrets
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import BinaryIO

import magic
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import AppError
from app.models import Attachment, Bug, ProjectRole, User
from app.services import audit_service
from app.services.access import ProjectAccess, forbidden

ALLOWED_TYPES: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "application/pdf",
        "text/plain",
        "text/csv",
        "application/json",
        "application/zip",
        "application/gzip",
        "application/x-gzip",
    }
)
_CHUNK = 64 * 1024
_SNIFF_BYTES = 8192
_STORAGE_KEY = re.compile(r"^[0-9a-f]{32}$")
_UNSAFE_NAME_CHARS = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')


def sanitize_filename(name: str | None) -> str:
    """Keep only a safe display name: no directories, control or reserved characters."""
    base = unicodedata.normalize("NFC", name or "")
    base = base.replace("\\", "/").rsplit("/", 1)[-1]
    base = _UNSAFE_NAME_CHARS.sub("_", base).strip(" .")
    if not base:
        base = "attachment"
    if len(base) > 200:
        stem, dot, ext = base.rpartition(".")
        base = (stem[: 200 - len(ext) - 1] + dot + ext) if dot and len(ext) <= 16 else base[:200]
    return base


def storage_path(directory: Path, key: str) -> Path:
    if not _STORAGE_KEY.fullmatch(key):
        raise ValueError("invalid storage key")
    root = directory.resolve()
    path = (root / key).resolve()
    if path.parent != root:
        raise ValueError("storage path escapes the attachment directory")
    return path


def save_upload(
    db: Session,
    access: ProjectAccess,
    bug: Bug,
    uploader: User,
    stream: BinaryIO,
    filename: str | None,
    directory: Path,
    max_bytes: int,
) -> Attachment:
    directory.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(16)
    final_path = storage_path(directory, key)
    temp_path = final_path.with_name(f"{key}.part")

    digest = hashlib.sha256()
    size = 0
    head = b""
    try:
        with temp_path.open("xb") as out:
            while chunk := stream.read(_CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise AppError(
                        status.HTTP_413_CONTENT_TOO_LARGE,
                        "payload_too_large",
                        f"Attachments are limited to {max_bytes // (1024 * 1024)} MB",
                        {"max_bytes": max_bytes},
                    )
                if len(head) < _SNIFF_BYTES:
                    head += chunk[: _SNIFF_BYTES - len(head)]
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise AppError(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "empty_file", "The uploaded file is empty"
            )
        detected = magic.from_buffer(head, mime=True)
        if detected not in ALLOWED_TYPES:
            raise AppError(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                "unsupported_media_type",
                f"File type {detected} is not allowed",
                {"detected": detected, "allowed": sorted(ALLOWED_TYPES)},
            )
        os.replace(temp_path, final_path)
    finally:
        temp_path.unlink(missing_ok=True)

    attachment = Attachment(
        bug_id=bug.id,
        uploader_id=uploader.id,
        original_filename=sanitize_filename(filename),
        storage_key=key,
        content_type=detected,
        size_bytes=size,
        sha256=digest.hexdigest(),
    )
    db.add(attachment)
    try:
        db.flush()
        audit_service.record(
            db,
            uploader,
            "attachment_added",
            bug_id=bug.id,
            field="attachment",
            new=attachment.original_filename,
        )
        db.commit()
    except Exception:
        db.rollback()
        final_path.unlink(missing_ok=True)
        raise
    return get_attachment(db, attachment.id)


def get_attachment(db: Session, attachment_id: int) -> Attachment:
    attachment = db.scalar(
        select(Attachment)
        .where(Attachment.id == attachment_id)
        .options(selectinload(Attachment.uploader))
    )
    if attachment is None:
        raise AppError(status.HTTP_404_NOT_FOUND, "not_found", "Attachment not found")
    return attachment


def list_attachments(db: Session, bug_id: int) -> Sequence[Attachment]:
    return db.scalars(
        select(Attachment)
        .where(Attachment.bug_id == bug_id)
        .options(selectinload(Attachment.uploader))
        .order_by(Attachment.created_at, Attachment.id)
    ).all()


def delete_attachment(
    db: Session, access: ProjectAccess, attachment: Attachment, directory: Path
) -> None:
    if not (
        access.has_role(ProjectRole.PROJECT_MANAGER) or attachment.uploader_id == access.user.id
    ):
        raise forbidden("Only the uploader or a Project Manager can delete this attachment")
    audit_service.record(
        db,
        access.user,
        "attachment_removed",
        bug_id=attachment.bug_id,
        field="attachment",
        old=attachment.original_filename,
    )
    path = storage_path(directory, attachment.storage_key)
    db.delete(attachment)
    db.commit()
    path.unlink(missing_ok=True)
