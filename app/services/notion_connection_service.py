import logging
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.notion import NotionConnection
from app.services.auth_service import get_user_by_user_name
from app.services.notion_service import NotionService, NotionServiceError
from app.services.user_notification_service import normalize_email

logger = logging.getLogger(__name__)

AUTO_PARENT_PAGE_TITLE = "A-ka"
AUTO_PARENT_PAGE_CONTENT = "A-ka가 요약 결과를 저장하는 페이지입니다."


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
    parent_page_id: str | None = None,
) -> NotionConnection:
    owner = token_payload.get("owner") or {}
    duplicated_template_id = token_payload.get("duplicated_template_id")
    workspace_id, owner_user_id, owner_user_email = _owner_identity_from_token_payload(
        token_payload
    )

    duplicate = find_duplicate_notion_owner_connection(
        db=db,
        user_id=user_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        owner_user_email=owner_user_email,
    )
    if duplicate is not None:
        raise NotionServiceError(
            "This Notion account is already connected to another user.",
            status_code=409,
        )

    connection = get_notion_connection(db, user_id)

    values = {
        "workspace_id": workspace_id,
        "workspace_name": token_payload.get("workspace_name"),
        "workspace_icon": token_payload.get("workspace_icon"),
        "bot_id": token_payload["bot_id"],
        "access_token": token_payload["access_token"],
        "refresh_token": token_payload.get("refresh_token"),
        "duplicated_template_id": duplicated_template_id,
        "owner_type": owner.get("type"),
        "owner_user_id": owner_user_id,
        "owner_user_email": owner_user_email,
    }
    normalized_parent_page_id = NotionService._normalize_page_id(parent_page_id) or None

    if connection is None:
        connection = NotionConnection(
            user_id=user_id,
            parent_page_id=normalized_parent_page_id
            or NotionService._normalize_page_id(duplicated_template_id)
            or None,
            **values,
        )
        db.add(connection)
    else:
        for key, value in values.items():
            setattr(connection, key, value)
        if normalized_parent_page_id:
            connection.parent_page_id = normalized_parent_page_id
        if duplicated_template_id:
            connection.parent_page_id = NotionService._normalize_page_id(
                duplicated_template_id
            )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise NotionServiceError(
            "This Notion account is already connected to another user.",
            status_code=409,
        ) from exc

    db.refresh(connection)
    return connection


def connect_notion_account(
    db: Session,
    user_id: int,
    token_payload: dict[str, Any],
) -> NotionConnection:
    duplicate = find_duplicate_notion_owner_connection_for_token_payload(
        db,
        user_id,
        token_payload,
    )
    if duplicate is not None:
        raise NotionServiceError(
            "This Notion account is already connected to another user.",
            status_code=409,
        )

    existing_connection = get_notion_connection(db, user_id)
    parent_page_id = _existing_parent_page_id_for_same_owner(
        existing_connection,
        token_payload,
    )
    if not parent_page_id:
        parent_page_id = create_auto_parent_page(token_payload["access_token"])

    connection = upsert_notion_connection(
        db,
        user_id,
        token_payload,
        parent_page_id=parent_page_id,
    )
    return ensure_auto_parent_page(db, connection)


def create_auto_parent_page(
    access_token: str,
) -> str | None:
    service = NotionService(api_key=access_token)
    created_page = service.create_workspace_page(
        title=AUTO_PARENT_PAGE_TITLE,
        content=AUTO_PARENT_PAGE_CONTENT,
    )
    page_id = created_page.get("id")
    return NotionService._normalize_page_id(page_id)


def is_same_notion_owner(
    connection: NotionConnection,
    token_payload: dict[str, Any],
) -> bool:
    workspace_id, owner_user_id, owner_user_email = _owner_identity_from_token_payload(
        token_payload
    )
    if connection.workspace_id != workspace_id:
        return False

    if owner_user_id and owner_user_id == connection.owner_user_id:
        return True
    if owner_user_email and owner_user_email == normalize_email(
        connection.owner_user_email
    ):
        return True
    return False


def ensure_auto_parent_page(
    db: Session,
    connection: NotionConnection,
) -> NotionConnection:
    if connection.parent_page_id:
        return connection

    try:
        page_id = create_auto_parent_page(connection.access_token)
    except NotionServiceError as exc:
        logger.warning(
            "Failed to auto-create Notion parent page. user_id=%s error=%s",
            connection.user_id,
            exc,
        )
        return connection

    if not page_id:
        return connection

    return set_parent_page_id(db, connection, page_id)


def find_duplicate_notion_owner_connection(
    db: Session,
    user_id: int,
    workspace_id: str,
    owner_user_id: str | None,
    owner_user_email: str | None,
) -> NotionConnection | None:
    query = db.query(NotionConnection).filter(
        NotionConnection.workspace_id == workspace_id,
        NotionConnection.user_id != user_id,
    )

    if owner_user_id:
        return (
            query.filter(NotionConnection.owner_user_id == owner_user_id)
            .order_by(NotionConnection.user_id)
            .first()
        )

    if owner_user_email:
        return (
            query.filter(
                NotionConnection.owner_user_id.is_(None),
                func.lower(NotionConnection.owner_user_email) == owner_user_email,
            )
            .order_by(NotionConnection.user_id)
            .first()
        )

    return None


def find_duplicate_notion_owner_connection_for_token_payload(
    db: Session,
    user_id: int,
    token_payload: dict[str, Any],
) -> NotionConnection | None:
    workspace_id, owner_user_id, owner_user_email = _owner_identity_from_token_payload(
        token_payload
    )
    return find_duplicate_notion_owner_connection(
        db=db,
        user_id=user_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        owner_user_email=owner_user_email,
    )


def _existing_parent_page_id_for_same_owner(
    connection: NotionConnection | None,
    token_payload: dict[str, Any],
) -> str | None:
    if connection is None or not connection.parent_page_id:
        return None
    if not is_same_notion_owner(connection, token_payload):
        return None
    return connection.parent_page_id


def _owner_identity_from_token_payload(
    token_payload: dict[str, Any],
) -> tuple[str, str | None, str | None]:
    owner = token_payload.get("owner") or {}
    owner_user = owner.get("user") if isinstance(owner.get("user"), dict) else {}
    person = (
        owner_user.get("person")
        if isinstance(owner_user.get("person"), dict)
        else {}
    )
    return (
        token_payload["workspace_id"],
        owner_user.get("id"),
        normalize_email(person.get("email")),
    )


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
