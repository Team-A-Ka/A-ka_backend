"""카카오 채널 사용자 ID 기준 Notion OAuth 시작 URL (개발·수동 연동용)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.kakao import (
    KakaoWebhookRequest,
    KakaoWebhookResponse,
    Output,
    SimpleText,
    Template,
)
from app.schemas.notion import NotionOAuthStartResponse
from app.services.auth_service import get_or_create_kakao_user
from app.services.notion_service import NotionService, NotionServiceError
from database import get_db

router = APIRouter()


def _verify_kakao_notion_dev_key(
    x_kakao_notion_dev_key: Annotated[
        str | None, Header(alias="X-Kakao-Notion-Dev-Key")
    ] = None,
) -> None:
    expected = (settings.KAKAO_NOTION_OAUTH_DEV_KEY or "").strip()
    if not expected:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    if not x_kakao_notion_dev_key or x_kakao_notion_dev_key != expected:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


@router.get(
    "/notion/oauth/start",
    response_model=NotionOAuthStartResponse,
    dependencies=[Depends(_verify_kakao_notion_dev_key)],
)
def kakao_notion_oauth_start(
    db: Annotated[Session, Depends(get_db)],
    kakao_user_id: Annotated[
        str, Query(..., min_length=1, description="카카오 userRequest.user.id")
    ],
) -> NotionOAuthStartResponse:
    """swagger test용"""
    user = get_or_create_kakao_user(db=db, kakao_user_id=kakao_user_id)
    notion_service = NotionService()
    try:
        state = notion_service.create_oauth_state(user.id)
        authorization_url = notion_service.build_oauth_authorization_url(state)
    except NotionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return NotionOAuthStartResponse(authorization_url=authorization_url)


@router.post("/notion/oauth/start", response_model=KakaoWebhookResponse)
def kakao_notion_oauth_start_post(
    request: KakaoWebhookRequest,
    db: Annotated[Session, Depends(get_db)],
) -> KakaoWebhookResponse:
    kakao_user_id = request.userRequest.user.id

    user = get_or_create_kakao_user(
        db=db,
        kakao_user_id=kakao_user_id,
    )

    notion_service = NotionService()

    try:
        state = notion_service.create_oauth_state(user.id)
        authorization_url = notion_service.build_oauth_authorization_url(state)
    except NotionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return KakaoWebhookResponse(
        version="2.0",
        template=Template(
            outputs=[
                Output(
                    simpleText=SimpleText(
                        text=f"아래 링크를 눌러 Notion을 연결해주세요.\n{authorization_url}"
                    )
                )
            ]
        ),
    )
