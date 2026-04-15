from fastapi import APIRouter, BackgroundTasks
from app.schemas.kakao import KakaoWebhookRequest, KakaoWebhookResponse, Template, Output, SimpleText
import asyncio

router = APIRouter()

# 임시 워커 함수
async def mock_celery_worker(user_id: str, utterance: str):
    print(f"\n[Worker]  유저 {user_id}의 데이터 비동기 처리 시작: {utterance}")
    await asyncio.sleep(3) # 3초 딜레이
    print(f"[Worker]  유저 {user_id}의 데이터 처리 완료 및 노션 전송 완료!\n")

@router.post("/kakao", response_model=KakaoWebhookResponse)
async def handle_kakao_webhook(
    request: KakaoWebhookRequest, 
    background_tasks: BackgroundTasks
):
    user_id = request.userRequest.user.id
    utterance = request.userRequest.utterance
    
    print(f" [Webhook] 카카오 요청 수신 | Text: {utterance}")

    # 백그라운드로 무거운 작업 넘기기
    background_tasks.add_task(mock_celery_worker, user_id, utterance)

    # 즉시 응답
    return KakaoWebhookResponse(
        template=Template(
            outputs=[
                Output(
                    simpleText=SimpleText(
                        text="요청을 접수했습니다! 분석을 시작합니다. 완료되면 알려드릴게요 "
                    )
                )
            ]
        )
    )