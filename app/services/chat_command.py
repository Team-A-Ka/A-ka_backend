import re
import time
from celery.utils.log import get_task_logger
from openai import OpenAI
from app.core.config import settings

from app.schemas.intent import IntentExtraction, IntentType
from app.services.search_service import search_and_answer
from app.tasks.knowledge_tasks import run_core_pipeline_task, save_link_only_task

logger = get_task_logger(__name__)

openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)


class ChatCommandService:
    def process(self, user_id: str, user_message: str) -> dict:
        logger.info(f"====== [AI Router] 의도 분석 시작 (User: {user_id}) ======")
        logger.info(f"입력된 텍스트: {user_message}")
        intent, detected_url = self.analyze_intent(user_message)

        if intent == "UPLOAD":
            return self.handle_upload(user_id, detected_url)

        if intent == "SAVE_ONLY":
            return self.handle_save_only(user_id, detected_url)

        if intent == "SEARCH":
            return self.handle_search(user_id, user_message)

        return {
            "intent": intent,
            "detected_url": detected_url,
            "user_id": user_id,
        }

    def analyze_intent(
        self, user_message: str
    ) -> tuple[str, str | None]:  # user_id는....
        intent = IntentType.UNKNOWN.value
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
                            ),
                        },
                        {"role": "user", "content": user_message},
                    ],
                    response_format=IntentExtraction,
                )

                parsed_result = response.choices[0].message.parsed
                if parsed_result:
                    intent = parsed_result.intent.value
                    detected_url = parsed_result.detected_url
                    logger.info(
                        f"➔ [OpenAI 파싱 결과] Intent: {intent}, URL: {detected_url}"
                    )
                else:
                    logger.error("OpenAI 파싱 결과가 비어 있습니다.")
                break  # 성공 시 루프 탈출

            except Exception as e:
                logger.error(
                    f"OpenAI 의도 분석 중 에러 발생 (시도 {attempt + 1}/3): {e}"
                )
                if attempt < 2:
                    time.sleep(1)
                else:
                    # 혹시라도 모두 실패하면 장애 방지를 위해 기본값 UNKNOWN으로 처리
                    intent = IntentType.UNKNOWN.value
        return intent, detected_url

    def handle_upload(self, user_id: str, detected_url: str | None) -> dict:
        video_id = self.parse_youtube_video_id(detected_url)
        if not video_id:
            logger.warning(f"➔ URL({detected_url})이 올바른 유튜브 형식이 아닙니다.")
            return {
                "intent": "UPLOAD",
                "error": "유효한 유튜브 URL이 아닙니다.",
                "user_id": user_id,
            }

        logger.info(f"➔ 유튜브 영상 감지 완료 (Video ID: {video_id})")
        # 중복 처리(사용자 보유 링크 데이터베이스와 비교)

        result = run_core_pipeline_task(video_id)

        return {
            "intent": "UPLOAD",
            "detected_url": detected_url,
            "video_id": video_id,
            "user_id": user_id,
            "pipeline": result,
        }

    def handle_save_only(self, user_id: str, detected_url: str | None) -> dict:
        video_id = self.parse_youtube_video_id(detected_url)
        if not video_id:
            logger.warning(f"➔ URL({detected_url})이 올바른 유튜브 형식이 아닙니다.")
            return {
                "intent": "SAVE_ONLY",
                "error": "유효한 유튜브 URL이 아닙니다.",
                "user_id": user_id,
            }

        logger.info(f"➔ 단순 링크 저장 감지 (Video ID: {video_id})")
        task = save_link_only_task.delay(video_id)

        return {
            "intent": "SAVE_ONLY",
            "detected_url": detected_url,
            "video_id": video_id,
            "user_id": user_id,
            "task_id": task.id,
            "status": "QUEUED",
        }

    def handle_search(
        self,
        user_id: str,
        user_message: str,
    ) -> dict:
        logger.info("➔ SEARCH 의도 감지. RAG 검색 파이프라인 실행")

        search_result = search_and_answer(user_id, user_message)
        logger.info(f"➔ 검색 답변 생성 완료 (출처: {search_result['sources']}개)")

        return {
            "intent": "SEARCH",
            "user_id": user_id,
            "result": search_result,
        }

    #     logger.info(f"➔ 의도 파악: {intent} (일반 대화 및 예외 처리 예정)")
    # # TODO: 알 수 없음 또는 기본 챗 메시지 반환 호출

    @staticmethod
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
