import logging
import re

from sqlalchemy.orm import Session

from app.models.notion import NotionConnection
from app.services.smtp_service import send_error_email_sync

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(
    r"(?<![A-Z0-9._%+-])"
    r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})"
    r"(?![A-Z0-9._%+-])",
    re.IGNORECASE,
)


def normalize_email(email: str | None) -> str | None:
    if not email:
        return None

    normalized = email.strip().lower()
    if not EMAIL_PATTERN.fullmatch(normalized):
        return None
    return normalized


def get_user_notification_email(db: Session, user_id: int) -> str | None:
    notion_connection = (
        db.query(NotionConnection)
        .filter(NotionConnection.user_id == user_id)
        .one_or_none()
    )
    if notion_connection is None:
        return None

    return normalize_email(notion_connection.owner_user_email)


def send_user_processing_error_email(
    user_id: int,
    error: Exception,
    *,
    user_message: str | None = None,
    context: str = "Kakao message processing",
) -> bool:
    try:
        from database import SessionLocal

        db = SessionLocal()
        try:
            recipient_email = get_user_notification_email(db, int(user_id))
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to resolve notification email. user_id=%s", user_id)
        return False

    if not recipient_email:
        logger.warning("No notification email registered. user_id=%s", user_id)
        return False

    return send_error_email_sync(
        error,
        recipient_email=recipient_email,
        user_message=user_message,
        context=context,
    )
