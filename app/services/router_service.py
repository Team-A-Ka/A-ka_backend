import re
import time
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
    logger.warning(
        "OPENAI_API_KEY가 설정되지 않았습니다. AI 라우터가 정상 작동하지 않을 수 있습니다."
    )
openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)


# 의도 분류 상수 Enum
class IntentType(str, Enum):
    SAVE_ONLY = "SAVE_ONLY"  # 단순 링크 저장
    UPLOAD = "UPLOAD"     # 링크 저장, 영상 요약 및 적재 등
    SEARCH = "SEARCH"     # 과거 데이터 기반 질문, 검색, RAG
    UNKNOWN = "UNKNOWN"   # 기타 일상 대화, 의미 없는 텍스트

# OpenAI Structured Output을 위한 Pydantic Schema
class IntentExtraction(BaseModel):
    intent: IntentType = Field(description="사용자 발화의 핵심 의도")
    detected_url: str | None = Field(
        description="사용자 발화에 포함된 URL. 없으면 null"
    )


def parse_youtube_video_id(url: str) -> str | None:
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
def process_ai_routing(self, user_id: str, user_message: str):
    """
    [AI 라우터 (Function Calling)]
    카카오톡에서 들어온 사용자의 메시지(user_message)를 분석하여 의도(Intent)를 파악합니다.
    분석 결과에 따라 적절한 파이프라인(UPLOAD, SEARCH 등)으로 라우팅합니다.
    """
    logger.info(f"====== [AI Router] 의도 분석 시작 (User: {user_id}) ======")
    logger.info(f"입력된 텍스트: {user_message}")

    intent = "UNKNOWN"
    detected_url = None

    for attempt in range(3):
        try:
            # OpenAI 베타 API(Structured Outputs)를 활용한 파싱
            response = openai_client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "너는 사용자의 입력을 분석하여 핵심 의도를 파악하는 AI 시스템이야. "
                            "1. 사용자가 유튜브 링크만 덩그러니 보냈거나, 요약/분석해달라고 지시하면 무조건 'UPLOAD'로 묶어. (링크만 보내면 기본 동작은 요약 및 적재야) "
                            "2. 사용자가 '저장만 해', '단순 저장해' 등 명시적으로 '저장'만 하라고 지시했을 때만 예외적으로 'SAVE_ONLY'로 묶어. "
                            "3. 질문을 하거나 과거의 정보를 찾아달라고 하면 'SEARCH'로 묶어. "
                            "4. 그 외의 단순 인사, 잡담, 파악 불가능한 말은 모두 'UNKNOWN'으로 처리해. "
                            "또한 텍스트에 웹사이트 링크가 들어있다면 반드시 그대로 추출해줘."
                        )
                    },
                    {"role": "user", "content": user_message}
                ],
                response_format=IntentExtraction,
            )
            
            parsed_result = response.choices[0].message.parsed
            if parsed_result:
                intent = parsed_result.intent.value
                detected_url = parsed_result.detected_url
                logger.info(f"➔ [OpenAI 파싱 결과] Intent: {intent}, URL: {detected_url}")
            else:
                logger.error("OpenAI 파싱 결과가 비어 있습니다.")
            break  # 성공 시 루프 탈출

        except Exception as e:
            logger.error(f"OpenAI 의도 분석 중 에러 발생 (시도 {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(1)
            else:
                # 혹시라도 모두 실패하면 장애 방지를 위해 기본값 UNKNOWN으로 처리
                intent = "UNKNOWN"

    # ==========================================
    # 파이프라인 분기 (Routing)
    # ==========================================
    if intent == "UPLOAD":
        if detected_url:
            video_id = parse_youtube_video_id(detected_url)
            if video_id:
                logger.info(f"➔ 유튜브 영상 감지 완료 (Video ID: {video_id}). 지식 파이프라인으로 격발합니다.")
                # ───────────────────────────────────────
                # task 호출 방식 정리 (#10)
                # ───────────────────────────────────────
                # run_core_pipeline_task는 @shared_task로 등록된 Celery task.
                # 이전 코드는 함수처럼 직접 호출(run_core_pipeline_task(video_id))해서
                # 큐를 거치지 않고 본 워커에서 동기 실행하는 anti-pattern이었음.
                # .delay()로 명시 호출하여 별도 워커가 처리하도록 변경.
                # user_id 전파는 #5(카카오 user_id ↔ User.id 매핑) 작업에서 추가.
                run_core_pipeline_task.delay(video_id)
            else:
                logger.warning(
                    f"➔ URL({detected_url})이 파싱되었으나 올바른 유튜브 형식이 아닙니다."
                )
        else:
            logger.warning("➔ UPLOAD 의도이나 URL이 포함되어 있지 않습니다.")

    elif intent == "SAVE_ONLY":
        if detected_url:
            video_id = parse_youtube_video_id(detected_url)
            if video_id:
                logger.info(f"➔ 단순 링크 저장 감지 (Video ID: {video_id}). 가벼운 저장 파이프라인을 격발합니다.")
                # 함수 안에서 lazy import — 순환 import 방지 + SAVE_ONLY 분기일 때만 모듈 로드
                from app.services.knowledge_pipeline import save_link_only_task
                # user_id 전파는 #5 작업에서 추가
                save_link_only_task.delay(video_id)
            else:
                logger.warning(f"➔ URL({detected_url})이 파싱되었으나 올바른 유튜브 형식이 아닙니다.")
        else:
            logger.warning("➔ SAVE_ONLY 의도이나 URL이 포함되어 있지 않습니다.")
            
    elif intent == "SEARCH":
        logger.info(f"➔ 의도 파악: {intent} (RAG 검색 파이프라인 실행)")
        from app.services.search_service import search_and_answer

        search_result = search_and_answer(user_id, user_message)
        logger.info(f"➔ 검색 답변 생성 완료 (출처: {search_result['sources']}개)")

    else:
        logger.info(f"➔ 의도 파악: {intent} (일반 대화 및 예외 처리 예정)")
        # TODO: 알 수 없음 또는 기본 챗 메시지 반환 호출

    return {"intent": intent, "detected_url": detected_url, "user_id": user_id}
