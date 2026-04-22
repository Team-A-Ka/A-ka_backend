import re
from enum import Enum
from pydantic import BaseModel, Field
from celery.utils.log import get_task_logger
from openai import OpenAI
from app.core.celery_app import celery_app
from app.core.config import settings

# 지식 파이프라인 트리거 함수 임포트
from app.services.knowledge_pipeline import run_core_pipeline_task

logger = get_task_logger(__name__)

# OpenAI 클라이언트 초기화
if not settings.OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY가 설정되지 않았습니다. AI 라우터가 정상 작동하지 않을 수 있습니다.")
openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

# 의도 분류 상수 Enum
class IntentType(str, Enum):
    UPLOAD = "UPLOAD"     # 링크 저장, 영상 요약 및 적재 등
    SEARCH = "SEARCH"     # 과거 데이터 기반 질문, 검색, RAG
    UNKNOWN = "UNKNOWN"   # 기타 일상 대화, 의미 없는 텍스트

# OpenAI Structured Output을 위한 Pydantic Schema
class IntentExtraction(BaseModel):
    intent: IntentType = Field(description="사용자 발화의 핵심 의도")
    extracted_url: str | None = Field(description="사용자 발화에 포함된 URL 파싱 결과. 없으면 null")

def extract_youtube_video_id(url: str) -> str | None:
    """유튜브 URL에서 video_id를 추출하는 헬퍼 함수"""
    if not url:
        return None
    
    # 정규식을 사용하여 v=... 또는 youtu.be/... 형태에서 파싱
    regex = r"(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/)([^\"&?\/\s]{11})"
    match = re.search(regex, url)
    if match:
        return match.group(1)
    return None

@celery_app.task(bind=True, name="router.analyze_intent")
def analyze_intent_and_route(self, user_id: str, utterance: str):
    """
    [AI 라우터 (Function Calling)]
    카카오톡에서 들어온 사용자의 발화(utterance)를 분석하여 의도(Intent)를 파악합니다.
    분석 결과에 따라 적절한 파이프라인(UPLOAD, SEARCH 등)으로 라우팅합니다.
    """
    logger.info(f"====== [AI Router] 의도 분석 시작 (User: {user_id}) ======")
    logger.info(f"입력된 텍스트: {utterance}")
    
    intent = "UNKNOWN"
    extracted_url = None

    try:
        # OpenAI 베타 API(Structured Outputs)를 활용한 파싱
        response = openai_client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "너는 사용자의 입력을 분석하여 핵심 의도를 파악하는 AI 시스템이야. "
                        "1. 사용자가 지식이나 유튜브 링크를 저장, 업로드, 요약해달라고 하면 'UPLOAD'로 묶어. "
                        "2. 질문을 하거나 과거의 정보를 찾아달라고 하면 'SEARCH'로 묶어. "
                        "3. 그 외의 단순 인사, 잡담, 파악 불가능한 말은 모두 'UNKNOWN'으로 처리해. "
                        "또한 텍스트에 웹사이트 링크가 들어있다면 반드시 그대로 추출해줘."
                    )
                },
                {"role": "user", "content": utterance}
            ],
            response_format=IntentExtraction,
        )
        
        parsed_result = response.choices[0].message.parsed
        if parsed_result:
            intent = parsed_result.intent.value
            extracted_url = parsed_result.extracted_url
            logger.info(f"➔ [OpenAI 파싱 결과] Intent: {intent}, URL: {extracted_url}")
        else:
            logger.error("OpenAI 파싱 결과가 비어 있습니다.")

    except Exception as e:
        logger.error(f"OpenAI 의도 분석 중 에러 발생: {e}")
        # 혹시라도 실패하면 장애 방지를 위해 기본값 UNKNOWN으로 처리
        intent = "UNKNOWN"

    # ==========================================
    # 파이프라인 분기 (Routing)
    # ==========================================
    if intent == "UPLOAD":
        if extracted_url:
            video_id = extract_youtube_video_id(extracted_url)
            if video_id:
                logger.info(f"➔ 유튜브 영상 감지 완료 (Video ID: {video_id}). 지식 파이프라인으로 격발합니다.")
                # 비동기 백그라운드 트리거 
                run_core_pipeline_task(video_id)
            else:
                logger.warning(f"➔ URL({extracted_url})이 파싱되었으나 올바른 유튜브 형식이 아닙니다.")
        else:
            logger.warning("➔ UPLOAD 의도이나 URL이 포함되어 있지 않습니다.")
            
    elif intent == "SEARCH":
        logger.info(f"➔ 의도 파악: {intent} (RAG 검색 파이프라인으로 이동 예정)")
        # TODO: SEARCH 파이프라인 호출
        
    else:
        logger.info(f"➔ 의도 파악: {intent} (일반 대화 및 예외 처리 예정)")
        # TODO: 알 수 없음 또는 기본 챗 메시지 반환 호출
        
    return {"intent": intent, "extracted_url": extracted_url, "user_id": user_id}
