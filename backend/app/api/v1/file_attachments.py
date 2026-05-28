from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.app_settings import AppSettings
from app.models.file_attachment import FileAttachment
from app.models.user import User
from app.services.event_bus import event_bus
from app.services.permission_service import PermissionService

router = APIRouter(tags=["file-attachments"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "image/png",
    "image/jpeg",
    "image/svg+xml",
    "text/plain",
}


@router.get("/cards/{card_id}/file-attachments")
async def list_file_attachments(
    card_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await PermissionService.require_permission(db, user, "documents.view")
    result = await db.execute(
        select(FileAttachment)
        .where(FileAttachment.card_id == uuid.UUID(card_id))
        .order_by(FileAttachment.created_at.desc())
    )
    files = result.scalars().all()

    # Batch-resolve creator names
    creator_ids = {f.created_by for f in files if f.created_by}
    creator_names: dict[uuid.UUID, str] = {}
    if creator_ids:
        user_result = await db.execute(select(User).where(User.id.in_(creator_ids)))
        for u in user_result.scalars().all():
            creator_names[u.id] = u.display_name

    return [
        {
            "id": str(f.id),
            "card_id": str(f.card_id),
            "name": f.name,
            "mime_type": f.mime_type,
            "size": f.size,
            "category": f.category,
            "created_by": str(f.created_by) if f.created_by else None,
            "creator_name": creator_names.get(f.created_by) if f.created_by else None,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }
        for f in files
    ]


@router.post("/cards/{card_id}/file-attachments", status_code=201)
async def upload_file_attachment(
    card_id: str,
    file: UploadFile,
    category: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    card_uuid = uuid.UUID(card_id)
    if not await PermissionService.check_permission(
        db, user, "documents.manage", card_uuid, "card.manage_documents"
    ):
        raise HTTPException(403, "Not enough permissions")

    settings_result = await db.execute(select(AppSettings).where(AppSettings.id == "default"))
    settings_row = settings_result.scalar_one_or_none()
    general = (settings_row.general_settings if settings_row else None) or {}
    if not general.get("fileUploadsEnabled", True):
        raise HTTPException(403, "File uploads are disabled by the administrator")

    # Validate MIME type
    content_type = file.content_type or ""
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            400,
            f"File type '{content_type}' is not allowed. "
            f"Accepted: PDF, DOCX, XLSX, PPTX, PNG, JPG, SVG, TXT.",
        )

    # Read file content with size limit
    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(
            400, f"File exceeds maximum size of {MAX_FILE_SIZE // (1024 * 1024)} MB"
        )

    attachment = FileAttachment(
        card_id=card_uuid,
        name=file.filename or "untitled",
        mime_type=content_type,
        size=len(data),
        data=data,
        category=category,
        created_by=user.id,
    )
    db.add(attachment)
    await db.flush()
    await event_bus.publish(
        "file.uploaded",
        {
            "attachment_id": str(attachment.id),
            "name": attachment.name,
            "mime_type": attachment.mime_type,
            "size": attachment.size,
            "category": attachment.category,
            "summary": attachment.name,
        },
        db=db,
        card_id=card_uuid,
        user_id=user.id,
    )
    await db.commit()
    await db.refresh(attachment)

    return {
        "id": str(attachment.id),
        "card_id": str(attachment.card_id),
        "name": attachment.name,
        "mime_type": attachment.mime_type,
        "size": attachment.size,
        "category": attachment.category,
        "created_by": str(attachment.created_by),
        "created_at": attachment.created_at.isoformat() if attachment.created_at else None,
    }


@router.get("/file-attachments/{attachment_id}/download")
async def download_file_attachment(
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await PermissionService.require_permission(db, user, "documents.view")
    result = await db.execute(
        select(FileAttachment).where(FileAttachment.id == uuid.UUID(attachment_id))
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(404, "File attachment not found")

    # RFC 6266 / RFC 5987: HTTP header values must be Latin-1 encodable, so a
    # raw filename with non-Latin-1 characters (Cyrillic, CJK, emoji, ...) would
    # crash the response serializer with UnicodeEncodeError. Emit an ASCII
    # fallback plus a percent-encoded UTF-8 form that modern browsers prefer.
    ascii_fallback = attachment.name.encode("ascii", "replace").decode("ascii")
    ascii_fallback = ascii_fallback.replace("\\", "_").replace('"', "_")
    encoded_name = quote(attachment.name, safe="")
    disposition = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded_name}"
    return Response(
        content=attachment.data,
        media_type=attachment.mime_type,
        headers={"Content-Disposition": disposition},
    )


@router.delete("/file-attachments/{attachment_id}", status_code=204)
async def delete_file_attachment(
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(FileAttachment).where(FileAttachment.id == uuid.UUID(attachment_id))
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(404, "File attachment not found")

    if not await PermissionService.check_permission(
        db,
        user,
        "documents.manage",
        attachment.card_id,
        "card.manage_documents",
    ):
        raise HTTPException(403, "Not enough permissions")
    await event_bus.publish(
        "file.deleted",
        {
            "attachment_id": str(attachment.id),
            "name": attachment.name,
            "mime_type": attachment.mime_type,
            "size": attachment.size,
            "summary": attachment.name,
        },
        db=db,
        card_id=attachment.card_id,
        user_id=user.id,
    )
    await db.delete(attachment)
    await db.commit()
