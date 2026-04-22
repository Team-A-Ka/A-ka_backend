from fastapi import APIRouter, BackgroundTasks
from app.schemas.kakao import KakaoWebhookRequest, KakaoWebhookResponse, Template, Output, SimpleText

# 새로 만든 AI 라우터 Celery Task 임포트
from app.services.router_service import analyze_intent_and_route

router = APIRouter()

def dispatch_to_celery(user_id: str, utterance: str):
    """Celery 큐에 밀어넣는 작업 자체도 백그라운드에서 처리하여 5초 응답을 완벽히 보장합니다."""
    try:
        analyze_intent_and_route.delay(user_id, utterance)
    except Exception as e:
        print(f"⚠️ [경고] 워커 큐(Redis) 전송 실패. 백그라운드 작업이 지연됩니다: {e}")

@router.post("/chat/webhook", response_model=KakaoWebhookResponse)
async def kakao_webhook(request: KakaoWebhookRequest, background_tasks: BackgroundTasks):
    # 1. userRequest.utterance 값 추출 및 로깅
    user_id = request.userRequest.user.id
    utterance = request.userRequest.utterance
    
    print(f"========== [카카오 웹훅 수신] ==========")
    print(f"User ID: {user_id}")
    print(f"Utterance: {utterance}")
    
    # 2. Celery 백그라운드 워커로 작업 이관을 통지 (비동기 위임)
    background_tasks.add_task(dispatch_to_celery, user_id, utterance)

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
        )
    )