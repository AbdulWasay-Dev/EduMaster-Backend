"""
Notifications API – real database-backed, synced with all app features.
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from utils.security import get_current_teacher
from services.database import get_database, DatabaseService

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Pydantic models ──────────────────────────────────────────────────────────

class NotificationOut(BaseModel):
    id: str
    type: str          # aliased from notification_type
    title: str
    message: str
    is_read: bool
    metadata: Optional[dict] = None
    created_at: str

    class Config:
        from_attributes = True


class CreateNotificationRequest(BaseModel):
    """Used internally / by other routers to inject notifications."""
    title: str
    message: str
    notification_type: str = "system"
    metadata: Optional[dict] = None


def _row_to_out(row: dict) -> dict:
    """Normalise a DB row to the frontend-expected shape."""
    meta = row.get("metadata")
    if isinstance(meta, str):
        import json
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    return {
        "id": str(row["id"]),
        "type": str(row.get("notification_type", "system")),
        "title": row.get("title", ""),
        "message": row.get("message", ""),
        "is_read": bool(row.get("is_read", False)),
        "metadata": meta or {},
        "created_at": str(row.get("created_at", "")),
    }


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/")
async def list_notifications(
    unread_only: bool = Query(False, description="Return only unread notifications"),
    limit: int = Query(100, le=200),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_teacher),
    db: DatabaseService = Depends(get_database),
):
    """List notifications for the authenticated teacher."""
    rows = await db.get_notifications(
        user_id=current_user["id"],
        only_unread=unread_only,
        limit=limit,
        offset=offset,
    )
    notifications = [_row_to_out(r) for r in rows]
    unread_count = await db.get_unread_count(current_user["id"])
    return {
        "notifications": notifications,
        "unread_count": unread_count,
        "total": len(notifications),
    }


@router.get("/unread-count")
async def get_unread_count(
    current_user: dict = Depends(get_current_teacher),
    db: DatabaseService = Depends(get_database),
):
    """Fast endpoint for the bell badge — just returns the count."""
    count = await db.get_unread_count(current_user["id"])
    return {"unread_count": count}


@router.post("/")
async def create_notification(
    payload: CreateNotificationRequest,
    current_user: dict = Depends(get_current_teacher),
    db: DatabaseService = Depends(get_database),
):
    """
    Teachers can create custom/manual notifications.
    Other routers also call db.create_notification() directly.
    """
    row = await db.create_notification({
        "user_id": current_user["id"],
        "title": payload.title,
        "message": payload.message,
        "notification_type": payload.notification_type,
        "metadata": payload.metadata or {},
    })
    if not row:
        raise HTTPException(status_code=500, detail="Failed to create notification")
    return _row_to_out(row)


@router.put("/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    current_user: dict = Depends(get_current_teacher),
    db: DatabaseService = Depends(get_database),
):
    """Mark a single notification as read."""
    ok = await db.mark_notification_read(notification_id, current_user["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found or access denied")
    return {"success": True, "id": notification_id}


@router.put("/mark-all-read")
async def mark_all_read(
    current_user: dict = Depends(get_current_teacher),
    db: DatabaseService = Depends(get_database),
):
    """Mark ALL unread notifications as read."""
    count = await db.mark_all_notifications_read(current_user["id"])
    return {"success": True, "marked_count": count}


@router.delete("/clear-read")
async def clear_read_notifications(
    current_user: dict = Depends(get_current_teacher),
    db: DatabaseService = Depends(get_database),
):
    """Delete all already-read notifications to keep the inbox tidy."""
    count = await db.delete_all_read_notifications(current_user["id"])
    return {"success": True, "deleted_count": count}


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_teacher),
    db: DatabaseService = Depends(get_database),
):
    """Delete a single notification."""
    ok = await db.delete_notification(notification_id, current_user["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found or access denied")
    return {"success": True, "deleted": notification_id}
