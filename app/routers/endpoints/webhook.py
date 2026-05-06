from fastapi import APIRouter, BackgroundTasks, Depends
from app.schemas.kakao import (
    ChatRequest,
    KakaoWebhookRequest,
    KakaoWebhookResponse,
    Template,
    Output,
    SimpleText,
)
from typing import Annotated
from app.models.user import User
from app.core.auth_dependencies import get_current_user

# AI 라우터 Celery Task 임포트
from app.tasks.router_tasks import process_ai_routing_task

router = APIRouter()             

def trigger_ai_router(user_id: str, user_message: str):
    """Celery 큐에 밀어넣는 작업 자체도 백그라운드에서 처리하여 5초 응답을 완벽히 보장합니다."""
    try:
        process_ai_routing_task.delay(user_id, user_message)
    except Exception as e:
        print(f"⚠️ [경고] 워커 큐(Redis) 전송 실패. 백그라운드 작업이 지연됩니다: {e}")

@router.post("/chat")
async def chat(
    request: ChatRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    background_tasks: BackgroundTasks

):
    user_id = current_user.id
    user_message = request.message

    background_tasks.add_task(trigger_ai_router, user_id, user_message)
    return 0      

@router.post("/chat/webhook", response_model=KakaoWebhookResponse)
async def kakao_webhook(
    request: KakaoWebhookRequest, background_tasks: BackgroundTasks
):
    # 1. userRequest에서 사용자 ID와 메시지 추출 및 로깅
    user_id = request.userRequest.user.id
    user_message = request.userRequest.user_message

    print(f"========== [카카오 웹훅 수신] ==========")
    print(f"User ID: {user_id}")
    print(f"Message: {user_message}")

    # 2. Celery 백그라운드 워커로 작업 이관을 통지 (비동기 위임)
    background_tasks.add_task(trigger_ai_router, user_id, user_message)

    # 3. 즉시 카카오 Response 반환 (5초 타임아웃 완벽 방어)
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
