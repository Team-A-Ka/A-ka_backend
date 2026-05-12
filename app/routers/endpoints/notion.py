import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.auth_dependencies import get_current_user
from app.models.notion import NotionConnection
from app.models.user import User
from app.schemas.notion import (
    NotionOAuthCallbackResponse,
    NotionOAuthStartResponse,
    NotionPageCreateRequest,
    NotionPageCreateResponse,
    NotionParentPageOption,
    NotionParentPageOptionsResponse,
    NotionParentPageRequest,
    NotionSearchRequest,
    NotionSearchResponse,
    NotionSearchResult,
    NotionUserConnectionResponse,
)
from app.services.auth_service import get_user_by_id
from app.services.notion_connection_service import (
    connect_notion_account,
    create_summary_page_for_user,
    delete_notion_connection,
    ensure_summary_database,
    get_notion_connection,
    set_parent_page_id,
)
from app.services.notion_service import NotionService, NotionServiceError
from database import get_db

router = APIRouter()
notion_service = NotionService()
logger = logging.getLogger(__name__)


@router.get("/oauth/start", response_model=NotionOAuthStartResponse)
def start_notion_oauth(
    current_user: Annotated[User, Depends(get_current_user)],
) -> NotionOAuthStartResponse:
    try:
        state = notion_service.create_oauth_state(current_user.id)
        authorization_url = notion_service.build_oauth_authorization_url(state)
    except NotionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return NotionOAuthStartResponse(authorization_url=authorization_url)


@router.get("/oauth/callback", response_model=NotionOAuthCallbackResponse)
def handle_notion_oauth_callback(
    db: Annotated[Session, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> NotionOAuthCallbackResponse | RedirectResponse:
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_description or error,
        )
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="code and state are required.",
        )

    try:
        user_id = notion_service.decode_oauth_state(state)
        token_payload = notion_service.exchange_oauth_code(code)
    except NotionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if get_user_by_id(db, user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OAuth state user was not found.",
        )

    try:
        connection = connect_notion_account(db, user_id, token_payload)
    except NotionServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return _oauth_callback_response(connection)


@router.get("/me", response_model=NotionUserConnectionResponse)
def get_my_notion_connection(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NotionUserConnectionResponse:
    connection = get_notion_connection(db, current_user.id)
    if connection is None:
        return NotionUserConnectionResponse(connected=False)
    try:
        connection = ensure_summary_database(db, connection, raise_errors=False)
    except Exception as exc:
        logger.warning(
            "Notion connection self-repair on GET /me failed (user_id=%s): %s",
            current_user.id,
            exc,
        )
    return NotionUserConnectionResponse(**_connection_payload(connection))


@router.post("/me/search", response_model=NotionSearchResponse)
def search_my_notion_pages(
    request: NotionSearchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NotionSearchResponse:
    connection = _require_connection(db, current_user.id)
    service = NotionService(api_key=connection.access_token)

    try:
        response = service.search(
            query=request.query,
            object_type=request.object_type,
            page_size=request.page_size,
        )
    except NotionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return NotionSearchResponse(
        results=[_to_search_result(item) for item in response.get("results", [])],
        has_more=response.get("has_more", False),
        next_cursor=response.get("next_cursor"),
    )


@router.get("/me/parent-page-options", response_model=NotionParentPageOptionsResponse)
def list_my_notion_parent_page_options(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    query: str = "",
    page_size: int = 20,
) -> NotionParentPageOptionsResponse:
    connection = _require_connection(db, current_user.id)
    service = NotionService(api_key=connection.access_token)

    try:
        response = service.search(
            query=query,
            object_type="page",
            page_size=max(1, min(page_size, 100)),
        )
    except NotionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return NotionParentPageOptionsResponse(
        results=[
            NotionParentPageOption(
                id=item["id"],
                title=_extract_title(item),
                url=item.get("url"),
                last_edited_time=item.get("last_edited_time"),
            )
            for item in response.get("results", [])
        ],
        has_more=response.get("has_more", False),
        next_cursor=response.get("next_cursor"),
    )


@router.put("/me/parent-page", response_model=NotionUserConnectionResponse)
def save_my_notion_parent_page(
    request: NotionParentPageRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NotionUserConnectionResponse:
    connection = _require_connection(db, current_user.id)
    try:
        NotionService(api_key=connection.access_token).retrieve_page(
            request.parent_page_id
        )
    except NotionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    connection = set_parent_page_id(db, connection, request.parent_page_id)
    return NotionUserConnectionResponse(**_connection_payload(connection))


@router.post("/me/pages", response_model=NotionPageCreateResponse)
def create_my_notion_summary_page(
    request: NotionPageCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NotionPageCreateResponse:
    connection = _require_connection(db, current_user.id)
    if not connection.parent_page_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Notion parent page is not selected.",
        )

    try:
        page = _create_page_for_connection(db, connection, request)
    except NotionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return NotionPageCreateResponse(id=page["id"], url=page.get("url"))


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_my_notion(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    connection = get_notion_connection(db, current_user.id)
    if connection is not None:
        delete_notion_connection(db, connection)


def _to_search_result(item: dict[str, Any]) -> NotionSearchResult:
    return NotionSearchResult(
        id=item["id"],
        object=item["object"],
        title=_extract_title(item),
        url=item.get("url"),
        last_edited_time=item.get("last_edited_time"),
    )


def _extract_title(item: dict[str, Any]) -> str:
    properties = item.get("properties") or {}
    for value in properties.values():
        title_items = value.get("title") if isinstance(value, dict) else None
        if title_items:
            return "".join(
                part.get("plain_text", "")
                for part in title_items
                if isinstance(part, dict)
            )

    title = item.get("title") or []
    if title:
        return "".join(
            part.get("plain_text", "")
            for part in title
            if isinstance(part, dict)
        )
    return "Untitled"


def _require_connection(db: Session, user_id: int) -> NotionConnection:
    connection = get_notion_connection(db, user_id)
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notion is not connected.",
        )
    return connection


def _create_page_for_connection(
    db: Session,
    connection: NotionConnection,
    request: NotionPageCreateRequest,
) -> dict[str, Any]:
    page = create_summary_page_for_user(
        db=db,
        user_id=connection.user_id,
        title=request.title,
        summary=request.summary,
        source_url=request.source_url,
    )
    if page is None:
        raise NotionServiceError("Notion summary database is not ready.", status_code=400)
    return page


def _connection_payload(connection: NotionConnection) -> dict[str, Any]:
    return {
        "connected": True,
        "ready": bool(connection.parent_page_id),
        "workspace_id": connection.workspace_id,
        "workspace_name": connection.workspace_name,
        "workspace_icon": connection.workspace_icon,
        "bot_id": connection.bot_id,
        "parent_page_id": connection.parent_page_id,
        "summary_database_id": connection.summary_database_id,
        "summary_data_source_id": connection.summary_data_source_id,
        "duplicated_template_id": connection.duplicated_template_id,
    }


def _oauth_callback_response(
    connection: NotionConnection,
) -> NotionOAuthCallbackResponse | RedirectResponse:
    page_url = _parent_page_url(connection)
    if page_url:
        return RedirectResponse(
            url=page_url,
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return NotionOAuthCallbackResponse(
        **_connection_payload(connection),
        message=_oauth_callback_message(connection),
    )


def _parent_page_url(connection: NotionConnection) -> str | None:
    if not connection.parent_page_id:
        return None

    try:
        page = NotionService(api_key=connection.access_token).retrieve_page(
            connection.parent_page_id
        )
    except NotionServiceError:
        return None

    page_url = page.get("url")
    if not isinstance(page_url, str) or not page_url:
        return None
    return page_url


def _oauth_callback_message(connection: NotionConnection) -> str:
    if connection.parent_page_id:
        return "Notion connected."

    return "Notion connected. Select a parent page before saving pages."
