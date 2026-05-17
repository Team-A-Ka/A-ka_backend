"""카카오 채널 사용자 ID 기준 Notion OAuth 시작 URL (개발·수동 연동용)."""

import html
import json
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.kakao import KakaoWebhookRequest
from app.schemas.notion import NotionOAuthStartResponse
from app.services.auth_service import get_or_create_kakao_user
from app.services.notion_service import NotionService, NotionServiceError
from database import get_db

router = APIRouter()


def _kakao_notion_bridge_url(state: str) -> str:
    base = settings.API_BASE_URL.rstrip("/")
    return f"{base}/api/v1/kakao/notion/oauth/bridge?{urlencode({'state': state})}"


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
    notion_svc = NotionService()
    try:
        state = notion_svc.create_oauth_state(user.id)
        authorization_url = notion_svc.build_oauth_authorization_url(state)
    except NotionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return NotionOAuthStartResponse(authorization_url=authorization_url)


@router.post("/notion/oauth/start")
def kakao_notion_oauth_start_post(
    request: KakaoWebhookRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """실제 카카오톡 응답용"""
    kakao_user_id = request.userRequest.user.id

    user = get_or_create_kakao_user(
        db=db,
        kakao_user_id=kakao_user_id,
    )

    notion_svc = NotionService()

    try:
        state = notion_svc.create_oauth_state(user.id)
        bridge_url = _kakao_notion_bridge_url(state)
    except NotionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "textCard": {
                        "title": "Notion 연동하기",
                        "description": "아래 버튼을 눌러 Notion 워크스페이스를 연결해주세요.",
                        "buttons": [
                            {
                                "action": "webLink",
                                "label": "Notion 연결",
                                "webLinkUrl": bridge_url,
                            }
                        ],
                    }
                }
            ]
        },
    }


@router.get("/notion/oauth/bridge", response_class=HTMLResponse)
def notion_oauth_bridge(
    state: Annotated[str, Query(..., min_length=1)],
):
    try:
        authorization_url = NotionService().build_oauth_authorization_url(state)
    except NotionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    href = html.escape(authorization_url, quote=True)
    auth_js = json.dumps(authorization_url)

    return f"""
    <!doctype html>
    <html lang="ko">
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Notion 연결 중...</title>

        <style>
            body {{
                font-family: sans-serif;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background: #ffffff;
            }}

            .button {{
                margin-top: 20px;
                padding: 14px 20px;
                border-radius: 12px;
                background: black;
                color: white;
                text-decoration: none;
                font-weight: bold;
            }}

            .desc {{
                color: #666;
                margin-top: 12px;
                font-size: 14px;
            }}
        </style>
    </head>

    <body>
        <h2>Notion 연결 중...</h2>

        <p class="desc">
            자동으로 이동하지 않으면 아래 버튼을 눌러주세요.
        </p>

        <a
            class="button"
            href="{href}"
            rel="noopener noreferrer"
        >
            Notion 연결 계속하기
        </a>

        <script>
            window.location.replace({auth_js});
        </script>
    </body>
    </html>
    """
