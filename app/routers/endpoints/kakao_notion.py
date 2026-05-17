"""카카오 채널 사용자 ID 기준 Notion OAuth 시작 URL (개발·수동 연동용)."""

import html
import json
import logging
from typing import Annotated, Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.kakao import KakaoWebhookRequest
from app.schemas.notion import NotionOAuthStartResponse
from app.services.auth_service import get_or_create_kakao_user
from app.services.notion_service import NotionService, NotionServiceError
from database import get_db

router = APIRouter()
logger = logging.getLogger("aka.notion")

_KAKAO_CHANNEL = "kakao"
_LOCAL_BASE_MARKERS = ("127.0.0.1", "localhost", "0.0.0.0", "domain.com")


def _is_unreachable_public_base(base: str) -> bool:
    lower = base.lower()
    return any(marker in lower for marker in _LOCAL_BASE_MARKERS)


def _public_base_url(http_request: Request | None) -> str:
    if http_request is not None:
        forwarded_proto = (
            http_request.headers.get("x-forwarded-proto") or ""
        ).split(",")[0].strip()
        forwarded_host = (
            http_request.headers.get("x-forwarded-host")
            or http_request.headers.get("host")
            or ""
        ).split(",")[0].strip()
        if forwarded_proto and forwarded_host:
            return f"{forwarded_proto}://{forwarded_host}".rstrip("/")

        from_request = str(http_request.base_url).rstrip("/")
        if not _is_unreachable_public_base(from_request):
            return from_request

    base = settings.API_BASE_URL.rstrip("/")
    if _is_unreachable_public_base(base):
        logger.warning(
            "API_BASE_URL looks unreachable from mobile (%s). "
            "Set API_BASE_URL to your public HTTPS domain or configure "
            "X-Forwarded-Proto / X-Forwarded-Host on the reverse proxy.",
            base,
        )
    return base


def _kakao_notion_bridge_url(state: str, http_request: Request | None = None) -> str:
    base = _public_base_url(http_request)
    return f"{base}/api/v1/kakao/notion/oauth/bridge?{urlencode({'state': state})}"


def _is_kakao_in_app(user_agent: str | None) -> bool:
    return "KAKAOTALK" in (user_agent or "").upper()


def _render_bridge_page(authorization_url: str, user_agent: str | None) -> str:
    href = html.escape(authorization_url, quote=True)
    auth_js = json.dumps(authorization_url)
    open_external_js = json.dumps(
        f"kakaotalk://web/openExternal?url={quote(authorization_url, safe='')}"
    )

    if _is_kakao_in_app(user_agent):
        kakao_body = f"""
        <h2>Notion 연결</h2>
        <p class="desc">
            카카오톡에서는 Notion 로그인이 차단될 수 있어
            <strong>외부 브라우저(Safari/Chrome)</strong>에서 연동해야 합니다.
        </p>
        <p class="desc hint">
            자동으로 열리지 않으면 아래 버튼을 누르거나,
            우측 상단 <strong>⋯</strong> 메뉴에서 「Safari/Chrome에서 열기」를 선택해 주세요.
        </p>
        <a class="button" id="openExternalBtn" href="#">외부 브라우저에서 Notion 연결</a>
        <a class="button secondary" href="{href}">이 페이지에서 계속하기</a>
        <button type="button" class="button secondary" id="copyBtn">연동 링크 복사</button>
        <p class="desc" id="copyStatus"></p>
        <script>
            const authUrl = {auth_js};
            const openExternalUrl = {open_external_js};
            document.getElementById("openExternalBtn").addEventListener("click", function (e) {{
                e.preventDefault();
                window.location.href = openExternalUrl;
            }});
            setTimeout(function () {{
                window.location.href = openExternalUrl;
            }}, 400);
            document.getElementById("copyBtn").addEventListener("click", async function () {{
                const status = document.getElementById("copyStatus");
                try {{
                    await navigator.clipboard.writeText(authUrl);
                    status.textContent = "링크를 복사했습니다. Safari/Chrome 주소창에 붙여넣어 주세요.";
                }} catch (err) {{
                    status.textContent = "복사에 실패했습니다. 아래 「이 페이지에서 계속하기」를 이용해 주세요.";
                }}
            }});
        </script>
        """
    else:
        kakao_body = f"""
        <h2>Notion 연결 중...</h2>
        <p class="desc">잠시 후 Notion 로그인 페이지로 이동합니다.</p>
        <a class="button" href="{href}">Notion 연결 계속하기</a>
        <script>
            window.location.replace({auth_js});
        </script>
        """

    return f"""
    <!doctype html>
    <html lang="ko">
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Notion 연결</title>
        <style>
            body {{
                font-family: sans-serif;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                margin: 0;
                padding: 24px;
                box-sizing: border-box;
                background: #ffffff;
                text-align: center;
            }}
            .button {{
                display: inline-block;
                margin-top: 12px;
                padding: 14px 20px;
                border-radius: 12px;
                background: black;
                color: white;
                text-decoration: none;
                font-weight: bold;
                border: none;
                font-size: 16px;
                cursor: pointer;
            }}
            .button.secondary {{
                background: #444;
            }}
            .desc {{
                color: #666;
                margin-top: 12px;
                font-size: 14px;
                line-height: 1.5;
                max-width: 320px;
            }}
            .hint {{
                font-size: 13px;
            }}
        </style>
    </head>
    <body>
        {kakao_body}
    </body>
    </html>
    """


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


@router.get("/notion/oauth/bridge/ping", response_class=HTMLResponse)
def notion_oauth_bridge_ping(http_request: Request) -> str:
    base = _public_base_url(http_request)
    return (
        "<!doctype html><html lang='ko'><body>"
        "<h2>브릿지 서버 연결 OK</h2>"
        f"<p>공개 URL: {html.escape(base)}</p>"
        "</body></html>"
    )


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
    http_request: Request,
    kakao_request: KakaoWebhookRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """실제 카카오톡 응답용"""
    kakao_user_id = kakao_request.userRequest.user.id

    user = get_or_create_kakao_user(
        db=db,
        kakao_user_id=kakao_user_id,
    )

    notion_svc = NotionService()

    try:
        state = notion_svc.create_oauth_state(user.id, channel=_KAKAO_CHANNEL)
        bridge_url = _kakao_notion_bridge_url(state, http_request)
    except NotionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    logger.info("Kakao Notion bridge URL: %s", bridge_url)

    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "textCard": {
                        "title": "Notion 연동하기",
                        "description": (
                            "아래 버튼을 누른 뒤, 열리는 페이지에서 "
                            "외부 브라우저(Safari/Chrome)로 Notion 연동을 진행해 주세요."
                        ),
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
    http_request: Request,
    state: Annotated[str, Query(..., min_length=1)],
):
    try:
        authorization_url = NotionService().build_oauth_authorization_url(state)
    except NotionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    user_agent = http_request.headers.get("user-agent")
    return _render_bridge_page(authorization_url, user_agent)
