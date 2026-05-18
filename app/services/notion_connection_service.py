import logging
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.notion import NotionConnection
from app.services.auth_service import get_user_by_user_name
from app.services.notion_service import NotionService, NotionServiceError
from app.services.user_notification_service import normalize_email

logger = logging.getLogger("aka.notion")

AUTO_PARENT_PAGE_TITLE = "A-ka"
AUTO_PARENT_PAGE_CONTENT = "A-ka가 요약 결과를 저장하는 페이지입니다."
SUMMARY_DATABASE_TITLE = "A-ka 요약 저장소"


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


def resolve_recipient_email(user_id: int | str | None) -> str | None:
    """user_id → internal_user_id → NotionConnection.owner_user_email 일괄 조회.

    SMTP 발송 전 사용자의 노션 연동 이메일을 가져오는 공통 헬퍼.
    실패 시 None 반환 (호출자가 발송 스킵 처리).
    """
    from database import SessionLocal

    db = SessionLocal()
    try:
        internal_user_id = resolve_internal_user_id(db, user_id)
        if not internal_user_id:
            return None
        conn = get_notion_connection(db, internal_user_id)
        return conn.owner_user_email if conn else None
    except Exception as exc:
        logger.warning(
            "Failed to resolve recipient email. user_id=%s error=%s",
            user_id,
            exc,
        )
        return None
    finally:
        db.close()


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
            _assign_parent_page_id(connection, normalized_parent_page_id)
        if duplicated_template_id:
            _assign_parent_page_id(
                connection,
                NotionService._normalize_page_id(duplicated_template_id),
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
    connection = upsert_notion_connection(
        db,
        user_id,
        token_payload,
        parent_page_id=parent_page_id,
    )

    if not connection.parent_page_id:
        connection = ensure_auto_parent_page(db, connection)
    if connection.parent_page_id:
        connection = ensure_summary_database(db, connection)
    return connection


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
        service = NotionService(api_key=connection.access_token)
        try:
            service.retrieve_page(connection.parent_page_id)
            return connection
        except NotionServiceError as exc:
            if exc.status_code != 404:
                logger.warning(
                    "Notion parent page verification failed. user_id=%s status=%s: %s",
                    connection.user_id,
                    exc.status_code,
                    exc,
                )
                return connection
            logger.warning(
                "Stored Notion parent page no longer exists (404). user_id=%s — "
                "clearing and recreating auto parent.",
                connection.user_id,
            )
            _assign_parent_page_id(connection, None)
            db.commit()
            db.refresh(connection)

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


def ensure_summary_database(
    db: Session,
    connection: NotionConnection,
    *,
    raise_errors: bool = False,
) -> NotionConnection:
    connection = ensure_auto_parent_page(db, connection)
    if not connection.parent_page_id:
        return connection

    service = NotionService(api_key=connection.access_token)

    if connection.summary_database_id and connection.summary_data_source_id:
        try:
            database_payload = service.retrieve_database(
                connection.summary_database_id
            )
        except NotionServiceError as exc:
            if exc.status_code == 404:
                logger.warning(
                    "Stored Notion summary database no longer exists (404). "
                    "Clearing ids. user_id=%s",
                    connection.user_id,
                )
                connection = _clear_summary_database_ids(db, connection)
            else:
                # 검증 API(403/5xx/일시 오류 등)가 막혀도 저장 시도는 이어가야 함.
                # 여기서 raise 하면 상위에서 일반 Exception 으로 삼켜져 등록 실패만 보이는 경우가 많음.
                logger.warning(
                    "Could not verify Notion summary database; using stored ids. "
                    "user_id=%s status=%s: %s",
                    connection.user_id,
                    exc.status_code,
                    exc,
                )
                return connection
        else:
            fresh_ds = NotionService.extract_data_source_id(database_payload)
            if fresh_ds and fresh_ds != connection.summary_data_source_id:
                connection.summary_data_source_id = fresh_ds
                db.commit()
                db.refresh(connection)
            _ensure_summary_database_configuration(
                service, connection, raise_errors=raise_errors
            )
            return connection

    if connection.summary_data_source_id:
        _ensure_summary_database_configuration(
            service, connection, raise_errors=raise_errors
        )
        return connection

    try:
        database = service.create_summary_database(
            parent_page_id=connection.parent_page_id,
            title=SUMMARY_DATABASE_TITLE,
        )
    except NotionServiceError as exc:
        if exc.status_code == 404 and connection.parent_page_id:
            logger.warning(
                "Stored Notion parent page is unavailable. Recreating parent page. "
                "user_id=%s parent_page_id=%s",
                connection.user_id,
                connection.parent_page_id,
            )
            _assign_parent_page_id(connection, None)
            db.commit()
            db.refresh(connection)
            connection = ensure_auto_parent_page(db, connection)
            if not connection.parent_page_id:
                if raise_errors:
                    raise
                return connection

            try:
                database = service.create_summary_database(
                    parent_page_id=connection.parent_page_id,
                    title=SUMMARY_DATABASE_TITLE,
                )
            except NotionServiceError as retry_exc:
                logger.warning(
                    "Failed to recreate Notion summary database. user_id=%s error=%s",
                    connection.user_id,
                    retry_exc,
                )
                if raise_errors:
                    raise
                return connection
        else:
            logger.warning(
                "Failed to create Notion summary database. user_id=%s error=%s",
                connection.user_id,
                exc,
            )
            if raise_errors:
                raise
            return connection
    database_id = NotionService._normalize_page_id(database.get("id")) or None
    data_source_id = NotionService.extract_data_source_id(database)
    if not data_source_id and database_id:
        try:
            database = service.retrieve_database(database_id)
            data_source_id = NotionService.extract_data_source_id(database)
        except NotionServiceError:
            data_source_id = ""

    if not database_id or not data_source_id:
        message = "Notion summary database was created without a data source id."
        logger.warning(
            "%s user_id=%s database_id=%s",
            message,
            connection.user_id,
            database_id,
        )
        if raise_errors:
            raise NotionServiceError(message)
        return connection

    connection.summary_database_id = database_id
    connection.summary_data_source_id = data_source_id
    db.commit()
    db.refresh(connection)
    _ensure_summary_database_configuration(
        service, connection, raise_errors=raise_errors
    )
    return connection


def _ensure_summary_database_configuration(
    service: NotionService,
    connection: NotionConnection,
    *,
    raise_errors: bool,
) -> None:
    if not connection.summary_data_source_id:
        return

    try:
        service.ensure_summary_database_schema(connection.summary_data_source_id)
    except NotionServiceError as exc:
        logger.warning(
            "Could not ensure Notion summary database schema. "
            "user_id=%s data_source_id=%s status=%s: %s",
            connection.user_id,
            connection.summary_data_source_id,
            exc.status_code,
            exc,
        )
        if raise_errors:
            raise
        return

    if not connection.summary_database_id:
        return

    try:
        service.ensure_hit_count_sorted_view(
            database_id=connection.summary_database_id,
            data_source_id=connection.summary_data_source_id,
        )
    except NotionServiceError as exc:
        logger.warning(
            "Could not ensure Notion hit-count sorted view. "
            "user_id=%s database_id=%s data_source_id=%s status=%s: %s",
            connection.user_id,
            connection.summary_database_id,
            connection.summary_data_source_id,
            exc.status_code,
            exc,
        )


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
    _assign_parent_page_id(connection, NotionService._normalize_page_id(parent_page_id))
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
    body_summary: str | None = None,
    source_url: str | None = None,
    category: str | None = None,
    hit_count: int | None = 1,
) -> dict[str, Any] | None:
    connection = get_notion_connection(db, user_id)
    if connection is None:
        return None

    try:
        return _create_summary_database_item_for_connection(
            db=db,
            connection=connection,
            title=title,
            summary=summary,
            body_summary=body_summary,
            source_url=source_url,
            category=category,
            hit_count=hit_count,
        )
    except NotionServiceError as exc:
        if exc.status_code == 404:
            logger.warning(
                "Stored Notion summary database is unavailable. Recreating it. "
                "user_id=%s data_source_id=%s",
                connection.user_id,
                connection.summary_data_source_id,
            )
            connection = _clear_summary_database_ids(db, connection)
            return _create_summary_database_item_for_connection(
                db=db,
                connection=connection,
                title=title,
                summary=summary,
                body_summary=body_summary,
                source_url=source_url,
                category=category,
                hit_count=hit_count,
            )

        if exc.status_code != 401 or not connection.refresh_token:
            raise

    refreshed = NotionService().refresh_oauth_token(connection.refresh_token)
    connection = update_notion_tokens(db, connection, refreshed)
    try:
        return _create_summary_database_item_for_connection(
            db=db,
            connection=connection,
            title=title,
            summary=summary,
            body_summary=body_summary,
            source_url=source_url,
            category=category,
            hit_count=hit_count,
        )
    except NotionServiceError as exc:
        if exc.status_code != 404:
            raise

        logger.warning(
            "Stored Notion summary database is unavailable after token refresh. "
            "Recreating it. user_id=%s data_source_id=%s",
            connection.user_id,
            connection.summary_data_source_id,
        )
        connection = _clear_summary_database_ids(db, connection)
        return _create_summary_database_item_for_connection(
            db=db,
            connection=connection,
            title=title,
            summary=summary,
            body_summary=body_summary,
            source_url=source_url,
            category=category,
            hit_count=hit_count,
        )


def _create_summary_database_item_for_connection(
    db: Session,
    connection: NotionConnection,
    title: str,
    summary: str,
    body_summary: str | None,
    source_url: str | None,
    category: str | None,
    hit_count: int | None,
) -> dict[str, Any] | None:
    connection = ensure_summary_database(db, connection, raise_errors=True)
    if not connection.summary_data_source_id:
        return None

    service = NotionService(api_key=connection.access_token)
    if source_url:
        existing_pages = service.find_summary_database_items_by_source_url(
            connection.summary_data_source_id,
            source_url,
        )
        if existing_pages:
            existing_page = existing_pages[0]
            page_id = existing_page.get("id")
            if page_id and hit_count is not None:
                updated_page = service.update_summary_database_item_hit_count(
                    page_id,
                    hit_count,
                )
                _archive_duplicate_summary_pages(service, existing_pages[1:])
                updated_page["_a_ka_action"] = "updated_hit_count"
                return updated_page

            _archive_duplicate_summary_pages(service, existing_pages[1:])
            existing_page["_a_ka_action"] = "existing"
            return existing_page

    created_page = service.create_summary_database_item(
        data_source_id=connection.summary_data_source_id,
        title=title,
        summary=summary,
        body_summary=body_summary,
        category=category,
        source_url=source_url,
        hit_count=hit_count,
    )
    created_page["_a_ka_action"] = "created"
    return created_page


def _archive_duplicate_summary_pages(
    service: NotionService,
    duplicate_pages: list[dict[str, Any]],
) -> None:
    for page in duplicate_pages:
        page_id = page.get("id")
        if not page_id:
            continue
        try:
            service.archive_page(page_id)
        except NotionServiceError as exc:
            logger.warning(
                "Failed to archive duplicate Notion summary row. page_id=%s status=%s: %s",
                page_id,
                exc.status_code,
                exc,
            )


def _clear_summary_database_ids(
    db: Session,
    connection: NotionConnection,
) -> NotionConnection:
    connection.summary_database_id = None
    connection.summary_data_source_id = None
    db.commit()
    db.refresh(connection)
    return connection


def _assign_parent_page_id(
    connection: NotionConnection,
    parent_page_id: str | None,
) -> None:
    normalized_parent_page_id = NotionService._normalize_page_id(parent_page_id)
    if connection.parent_page_id == normalized_parent_page_id:
        return

    connection.parent_page_id = normalized_parent_page_id or None
    connection.summary_database_id = None
    connection.summary_data_source_id = None
