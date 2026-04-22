from celery.utils.log import get_task_logger
from app.core.celery_app import celery_app

logger = get_task_logger(__name__)

@celery_app.task(bind=True, name="router.analyze_intent")
def analyze_intent_and_route(self, user_id: str, utterance: str):
    """
    [AI 라우터 (Function Calling)]
    카카오톡에서 들어온 사용자의 발화(utterance)를 분석하여 의도(Intent)를 파악합니다.
    분석 결과에 따라 적절한 파이프라인(UPLOAD, SEARCH 등)으로 라우팅합니다.
    """
    logger.info(f"====== [AI Router] 의도 분석 시작 (User: {user_id}) ======")
    logger.info(f"입력된 텍스트: {utterance}")
    
    # 향후 여기에 OpenAI Function Calling 로직이 위치합니다.
    # 현재는 키워드 기반 더미 분기 처리
    
    if "저장" in utterance or "업로드" in utterance:
        intent = "UPLOAD"
        logger.info(f"➔ 의도 파악: {intent} (지식 입력 파이프라인으로 이동 예정)")
        # TODO: UPLOAD 파이프라인 (knowledge_pipeline) 호출
        
    elif "검색" in utterance or "찾아" in utterance:
        intent = "SEARCH"
        logger.info(f"➔ 의도 파악: {intent} (RAG 검색 파이프라인으로 이동 예정)")
        # TODO: SEARCH 파이프라인 호출
        
    else:
        intent = "UNKNOWN"
        logger.info(f"➔ 의도 파악: {intent} (일반 대화 및 예외 처리 예정)")
        # TODO: 알 수 없음 또는 기본 챗 메시지 반환 호출
        
    return {"intent": intent, "user_id": user_id}
