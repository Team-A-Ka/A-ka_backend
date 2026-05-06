from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends

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
from app.tasks.router_tasks import process_ai_routing_task

router = APIRouter()


def trigger_ai_router(user_id: str | int, user_message: str):
    try:
        process_ai_routing_task.delay(user_id, user_message)
    except Exception as exc:
        print(f"[Warning] Failed to enqueue AI router task: {exc}")


@router.post("/chat")
async def chat(
    request: ChatRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
):
    background_tasks.add_task(
        trigger_ai_router,
        current_user.id,
        request.message,
    )
    return {"status": "queued"}


@router.post("/chat/webhook", response_model=KakaoWebhookResponse)
async def kakao_webhook(
    request: KakaoWebhookRequest,
    background_tasks: BackgroundTasks,
):
    user_id = request.userRequest.user.id
    user_message = request.userRequest.user_message

    print("========== [Kakao webhook received] ==========")
    print(f"User ID: {user_id}")
    print(f"Message: {user_message}")

    background_tasks.add_task(trigger_ai_router, user_id, user_message)

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
