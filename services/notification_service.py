"""
NotificationService — thin helper that other routers import to fire notifications
without coupling tightly to the database layer.

Usage (inside any router / background task):
    from services.notification_service import notify

    await notify(
        teacher_id="...",
        title="Paper published",
        message="Chapter 5 Quiz is now visible to students.",
        notification_type="paper_published",
        metadata={"paper_id": "...", "paper_title": "Chapter 5 Quiz"},
    )
"""
import logging
from typing import Optional
from services.database import get_database

logger = logging.getLogger(__name__)


async def notify(
    teacher_id: str,
    title: str,
    message: str,
    notification_type: str = "system",
    metadata: Optional[dict] = None,
) -> None:
    """
    Fire-and-forget helper. Errors are caught and logged so they never
    interrupt the calling request.
    """
    try:
        db = await get_database()
        await db.create_notification({
            "user_id": teacher_id,
            "title": title,
            "message": message,
            "notification_type": notification_type,
            "metadata": metadata or {},
        })
    except Exception as exc:
        logger.warning(f"Failed to create notification for teacher {teacher_id}: {exc}")
