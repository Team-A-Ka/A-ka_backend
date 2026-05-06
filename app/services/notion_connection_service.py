from typing import Any

from sqlalchemy.orm import Session

from app.models.notion import NotionConnection
from app.services.auth_service import get_user_by_user_name
from app.services.notion_service import NotionService, NotionServiceError


def get_notion_connection(db: Session, user_id: int) -> NotionConnection | None:
    return (
        db.query(NotionConnection)
        .filter(NotionConnection.user_id == user_id)
        .one_or_none()
    )


def resolve_internal_user_id(db: Session, user_id: int | str | None) -> int | None:
    if user_id is None:
        return None

    try:
        return int(user_id)
    except (TypeError, ValueError):
        pass

    user = get_user_by_user_name(db, str(user_id))
    return user.id if user is not None else None


def upsert_notion_connection(
    db: Session,
    user_id: int,
    token_payload: dict[str, Any],
) -> NotionConnection:
    connection = get_notion_connection(db, user_id)
    owner = token_payload.get("owner") or {}
    owner_user = owner.get("user") if isinstance(owner.get("user"), dict) else {}
    person = owner_user.get("person") if isinstance(owner_user.get("person"), dict) else {}
    duplicated_template_id = token_payload.get("duplicated_template_id")

    values = {
        "workspace_id": token_payload["workspace_id"],
        "workspace_name": token_payload.get("workspace_name"),
        "workspace_icon": token_payload.get("workspace_icon"),
        "bot_id": token_payload["bot_id"],
        "access_token": token_payload["access_token"],
        "refresh_token": token_payload.get("refresh_token"),
        "duplicated_template_id": duplicated_template_id,
        "owner_type": owner.get("type"),
        "owner_user_id": owner_user.get("id"),
        "owner_user_email": person.get("email"),
    }

    if connection is None:
        connection = NotionConnection(
            user_id=user_id,
            parent_page_id=NotionService._normalize_page_id(duplicated_template_id)
            or None,
            **values,
        )
        db.add(connection)
    else:
        for key, value in values.items():
            setattr(connection, key, value)
        if duplicated_template_id:
            connection.parent_page_id = NotionService._normalize_page_id(
                duplicated_template_id
            )

    db.commit()
    db.refresh(connection)
    return connection


def update_notion_tokens(
    db: Session,
    connection: NotionConnection,
    token_payload: dict[str, Any],
) -> NotionConnection:
    connection.access_token = token_payload["access_token"]
    connection.refresh_token = token_payload.get("refresh_token")
    db.commit()
    db.refresh(connection)
    return connection


def set_parent_page_id(
    db: Session,
    connection: NotionConnection,
    parent_page_id: str,
) -> NotionConnection:
    connection.parent_page_id = NotionService._normalize_page_id(parent_page_id)
    db.commit()
    db.refresh(connection)
    return connection


def delete_notion_connection(db: Session, connection: NotionConnection) -> None:
    db.delete(connection)
    db.commit()


def create_summary_page_for_user(
    db: Session,
    user_id: int,
    title: str,
    summary: str,
    source_url: str | None = None,
) -> dict[str, Any] | None:
    connection = get_notion_connection(db, user_id)
    if connection is None or not connection.parent_page_id:
        return None

    service = NotionService(api_key=connection.access_token)
    try:
        return service.create_summary_page(
            title=title,
            summary=summary,
            parent_page_id=connection.parent_page_id,
            source_url=source_url,
        )
    except NotionServiceError as exc:
        if exc.status_code != 401 or not connection.refresh_token:
            raise

    refreshed = NotionService().refresh_oauth_token(connection.refresh_token)
    connection = update_notion_tokens(db, connection, refreshed)
    return NotionService(api_key=connection.access_token).create_summary_page(
        title=title,
        summary=summary,
        parent_page_id=connection.parent_page_id,
        source_url=source_url,
    )
