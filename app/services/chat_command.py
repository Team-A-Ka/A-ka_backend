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
        logger.info(f"====== [AI Router] Analyze intent (user={user_id}) ======")
        logger.info(f"Input: {user_message}")
        intent, detected_url = self.analyze_intent(user_message)

        if intent == IntentType.UPLOAD.value:
            return self.handle_upload(user_id, detected_url)
        if intent == IntentType.SAVE_ONLY.value:
            return self.handle_save_only(user_id, detected_url)
        if intent == IntentType.SEARCH.value:
            return self.handle_search(user_id, user_message)

        return {
            "intent": intent,
            "detected_url": detected_url,
            "user_id": user_id,
        }

    def analyze_intent(self, user_message: str) -> tuple[str, str | None]:
        intent = IntentType.UNKNOWN.value
        detected_url = None

        for attempt in range(3):
            try:
                response = openai_client.beta.chat.completions.parse(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "사용자의 입력을 분석해 의도를 분류한다. "
                                "유튜브 링크만 보내거나 요약/분석/저장을 요청하면 UPLOAD다. "
                                "'링크만 저장', '요약하지 말고 저장'처럼 명시하면 SAVE_ONLY다. "
                                "이전에 저장한 정보에 대한 질문이면 SEARCH다. "
                                "그 외는 UNKNOWN이다. URL이 있으면 detected_url에 그대로 추출한다."
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
                        f"[AI Router] intent={intent}, detected_url={detected_url}"
                    )
                break
            except Exception as exc:
                logger.error(
                    f"Failed to analyze intent ({attempt + 1}/3): {exc}"
                )
                if attempt < 2:
                    time.sleep(1)

        return intent, detected_url

    def handle_upload(self, user_id: str, detected_url: str | None) -> dict:
        video_id = self.parse_youtube_video_id(detected_url)
        if not video_id:
            return {
                "intent": "UPLOAD",
                "error": "Invalid Youtube URL",
                "user_id": user_id,
            }

        result = run_core_pipeline_task(video_id, user_id)
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
            return {
                "intent": "SAVE_ONLY",
                "error": "Invalid Youtube URL",
                "user_id": user_id,
            }

        task = save_link_only_task.delay(video_id)
        return {
            "intent": "SAVE_ONLY",
            "detected_url": detected_url,
            "video_id": video_id,
            "user_id": user_id,
            "task_id": task.id,
            "status": "QUEUED",
        }

    def handle_search(self, user_id: str, user_message: str) -> dict:
        search_result = search_and_answer(user_id, user_message)
        return {
            "intent": "SEARCH",
            "user_id": user_id,
            "result": search_result,
        }

    @staticmethod
    def parse_youtube_video_id(url: str | None) -> str | None:
        if not url:
            return None

        pattern = (
            r"(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)"
            r"|youtu\.be\/)([^\"&?\/\s]{11})"
        )
        match = re.search(pattern, url)
        if match:
            return match.group(1)
        return None
