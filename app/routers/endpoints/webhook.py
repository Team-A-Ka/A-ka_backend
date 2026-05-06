from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.core.auth_dependencies import get_current_user
from app.models.user import User
from app.schemas.kakao import (
    ChatRequest,
    KakaoWebhookRequest,
    KakaoWebhookResponse,
    Output,
    SimpleText,
    Template,
)
from typing import Annotated
from app.models.user import User
from app.core.auth_dependencies import get_current_user

# AI 라우터 Celery Task 임포트
from app.services.auth_service import get_or_create_kakao_user
from app.tasks.router_tasks import process_ai_routing_task
from database import get_db

router = APIRouter()


def trigger_ai_router(user_id: int, user_message: str):
    """Celery 큐에 밀어넣는 작업 자체도 백그라운드에서 처리하여 5초 응답을 완벽히 보장합니다."""
    try:
        process_ai_routing_task.delay(user_id, user_message)
    except Exception as e:
        print(f"⚠️ [경고] 워커 큐(Redis) 전송 실패. 백그라운드 작업이 지연됩니다: {e}")


@router.post("/chat")
async def chat(
    request: ChatRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
):
    user_id = current_user.id
    user_message = request.message

    background_tasks.add_task(trigger_ai_router, user_id, user_message)
    return 0


@router.post("/chat/webhook", response_model=KakaoWebhookResponse)
async def kakao_webhook(
    request: KakaoWebhookRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
):
    """
    카카오 user_id (request) -> get_or_create_kakao_user()
    -> 내부 user.id -> trigger_ai_router에 내부 user.id 전달
    """
    # 1. userRequest에서 사용자 ID와 메시지 추출 및 로깅
    kakao_user_id = request.userRequest.user.id
    user_message = request.userRequest.user_message

    user = get_or_create_kakao_user(
        db=db,
        kakao_user_id=kakao_user_id,
    )

    internal_user_id = user.id

    print(f"========== [카카오 웹훅 수신] ==========")
    print(f"Kakao User ID: {kakao_user_id}")
    print(f"Internal User ID: {internal_user_id}")
    print(f"Message: {user_message}")

    # 2. Celery 백그라운드 워커로 작업 이관을 통지 (비동기 위임)
    background_tasks.add_task(trigger_ai_router, internal_user_id, user_message)

    return KakaoWebhookResponse(
        version="2.0",
        template=Template(
            outputs=[
                Output(
                    simpleText=SimpleText(
                        text="서버 연결 성공! 요청하신 내용을 확인했습니다."
                    )
                )
            ]
        ),
    )
