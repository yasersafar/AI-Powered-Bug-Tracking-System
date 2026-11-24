"""Bug attachments (FR-14): upload, list, download (project members only), delete."""

from typing import Annotated

from fastapi import APIRouter, File, UploadFile, status
from fastapi.responses import FileResponse

from app.core.deps import AppSettings, CurrentUser, DbSession
from app.core.errors import ErrorResponse
from app.schemas.attachment import AttachmentRead
from app.services import attachment_service
from app.services.access import bug_access

router = APIRouter(tags=["attachments"])


@router.post(
    "/bugs/{bug_id}/attachments",
    response_model=AttachmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an attachment (max 10 MB; images, PDF, text, CSV, JSON, ZIP, GZIP)",
    responses={
        413: {"model": ErrorResponse, "description": "File larger than the limit"},
        415: {"model": ErrorResponse, "description": "File type not allowed"},
    },
)
def upload_attachment(
    bug_id: int,
    file: Annotated[UploadFile, File(description="The file to attach")],
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> AttachmentRead:
    bug, access = bug_access(db, user, bug_id, write=True)
    attachment = attachment_service.save_upload(
        db,
        access,
        bug,
        user,
        file.file,
        file.filename,
        settings.attachment_dir,
        settings.attachment_max_bytes,
    )
    return AttachmentRead.model_validate(attachment)


@router.get(
    "/bugs/{bug_id}/attachments",
    response_model=list[AttachmentRead],
    summary="List a bug's attachments",
)
def list_attachments(bug_id: int, user: CurrentUser, db: DbSession) -> list[AttachmentRead]:
    bug, _ = bug_access(db, user, bug_id)
    return [
        AttachmentRead.model_validate(a) for a in attachment_service.list_attachments(db, bug.id)
    ]


@router.get(
    "/attachments/{attachment_id}/download",
    response_class=FileResponse,
    summary="Download an attachment (project members only)",
)
def download_attachment(
    attachment_id: int, user: CurrentUser, db: DbSession, settings: AppSettings
) -> FileResponse:
    attachment = attachment_service.get_attachment(db, attachment_id)
    bug_access(db, user, attachment.bug_id)
    path = attachment_service.storage_path(settings.attachment_dir, attachment.storage_key)
    return FileResponse(
        path,
        media_type=attachment.content_type,
        filename=attachment.original_filename,
        content_disposition_type="attachment",
    )


@router.delete(
    "/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an attachment (uploader or Project Manager)",
)
def delete_attachment(
    attachment_id: int, user: CurrentUser, db: DbSession, settings: AppSettings
) -> None:
    attachment = attachment_service.get_attachment(db, attachment_id)
    _, access = bug_access(db, user, attachment.bug_id, write=True)
    attachment_service.delete_attachment(db, access, attachment, settings.attachment_dir)
