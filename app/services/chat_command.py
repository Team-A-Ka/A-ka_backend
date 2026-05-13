import re
import time

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import get_chat_model_primary
from app.schemas.intent import IntentExtraction, IntentType
from app.services.search_service import find_similar_videos, search_and_answer
from app.tasks.knowledge_tasks import run_core_pipeline_task, save_link_only_task
from app.services.smtp_service import send_search_result_email
from app.models.notion import NotionConnection
from database import SessionLocal

logger = logging.getLogger("aka.intent")

_intent_chain = None


def _get_intent_chain():
    global _intent_chain
    if _intent_chain is None:
        _intent_chain = get_chat_model_primary().with_structured_output(
            IntentExtraction,
        )
    return _intent_chain


class ChatCommandService:
    def process(self, user_id: int, user_message: str) -> dict:
        logger.info(f"====== [AI Router] 의도 분석 시작 (User: {user_id}) ======")
        logger.info(f"입력된 텍스트: {user_message}")
        intent, detected_url = self.analyze_intent(user_message)

        if intent == IntentType.FIND_SIMILAR:
            return self.handle_find_similar(user_id, detected_url)
        if intent == IntentType.UPLOAD:
            return self.handle_upload(user_id, detected_url)
        if intent == IntentType.SAVE_ONLY:
            return self.handle_save_only(user_id, detected_url)
        if intent == IntentType.SEARCH:
            return self.handle_search(user_id, user_message)

        return {
            "intent": intent.value,
            "detected_url": detected_url,
            "user_id": user_id,
        }

    def analyze_intent(self, user_message: str) -> tuple[IntentType, str | None]:
        intent = IntentType.UNKNOWN
        detected_url = None
        last_error: Exception | None = None
        parsed_successfully = False

        for attempt in range(3):
            try:
                parsed_result = _get_intent_chain().invoke(
                    [
                        SystemMessage(
                            content=(
                                "사용자의 입력을 분석해 의도를 분류한다.\n"
                                "FIND_SIMILAR: 유튜브 URL이 포함되어 있고, '비슷한', '관련된', '같은 주제', '유사한' 등 유사 영상 탐색을 요청한 경우. "
                                "예: 'https://youtube.com/... 이 영상이랑 비슷한 것 찾아줘', '이 링크랑 관련된 영상 있어?'\n"
                                "UPLOAD: 유튜브 URL이 포함되어 있고, 요약/분석을 요청하거나 URL만 보낸 경우.\n"
                                "SAVE_ONLY: 유튜브 URL이 포함되어 있고, '저장만', '요약 말고 저장' 등 저장만 명시한 경우.\n"
                                "SEARCH: URL 없이 정보·지식·내용을 묻거나 설명을 요청하는 질문. "
                                "예: '와인이 두통을 유발하는 이유는?', 'AI의 미래에 대해 알려줘', '어제 본 영상에서 뭐라고 했어?'\n"
                                "UNKNOWN: 인사말, 의미 없는 텍스트, 단순 감탄사 등 위 어디에도 해당하지 않는 경우. "
                                "예: '안녕', 'ㅋㅋ', '고마워'\n"
                                "URL이 있으면 detected_url에 그대로 추출한다."
                            ),
                        ),
                        HumanMessage(content=user_message),
                    ],
                )
                if isinstance(parsed_result, dict):
                    parsed_result = IntentExtraction.model_validate(parsed_result)
                parsed_successfully = True
                if parsed_result:
                    intent = parsed_result.intent
                    detected_url = parsed_result.detected_url
                    logger.info(
                        f"[AI Router] intent={intent.value}, detected_url={detected_url}"
                    )
                break
            except Exception as exc:
                last_error = exc
                logger.error(f"Failed to analyze intent ({attempt + 1}/3): {exc}")
                if attempt < 2:
                    time.sleep(1)

        if last_error is not None and not parsed_successfully:
            raise RuntimeError("Failed to analyze user intent") from last_error

        return intent, detected_url

    def handle_upload(self, user_id: int, detected_url: str | None) -> dict:
        video_id = self.parse_youtube_video_id(detected_url)
        if not video_id:
            return {
                "intent": IntentType.UPLOAD.value,
                "error": "Invalid Youtube URL",
                "user_id": user_id,
            }

        result = run_core_pipeline_task(video_id, user_id, detected_url)
        return {
            "intent": IntentType.UPLOAD.value,
            "detected_url": detected_url,
            "video_id": video_id,
            "user_id": user_id,
            "pipeline": result,
        }

    def handle_save_only(self, user_id: int, detected_url: str | None) -> dict:
        video_id = self.parse_youtube_video_id(detected_url)
        if not video_id:
            return {
                "intent": IntentType.SAVE_ONLY.value,
                "error": "Invalid Youtube URL",
                "user_id": user_id,
            }
        
        category_name = "쇼츠" if "/shorts/" in (detected_url or "") else "미분류"

        task = save_link_only_task.delay(video_id, user_id, category_name=category_name)
        return {
            "intent": IntentType.SAVE_ONLY.value,
            "detected_url": detected_url,
            "video_id": video_id,
            "user_id": user_id,
            "task_id": task.id,
            "status": "QUEUED",
        }

    def handle_find_similar(self, user_id: int, detected_url: str | None) -> dict:
        """FIND_SIMILAR: UPLOAD 파이프라인 트리거 후 Step 3에서 유사 영상 자동 검색.

        - 새 영상: 파이프라인 완료 후 Step 3에서 find_similar_videos() 자동 실행
        - 중복 영상: 파이프라인 스킵되므로 여기서 직접 find_similar_videos() 호출
        """
        logger.info("➔ FIND_SIMILAR 의도 감지. UPLOAD 파이프라인 트리거")

        video_id = self.parse_youtube_video_id(detected_url)
        if not video_id:
            return {
                "intent": IntentType.FIND_SIMILAR.value,
                "error": "Invalid Youtube URL",
                "user_id": user_id,
            }

        result = run_core_pipeline_task(detected_url, video_id, user_id)

        # 중복 영상은 파이프라인이 스킵되므로 유사 영상 검색을 직접 실행
        similar_videos = []
        if isinstance(result, dict) and result.get("duplicate"):
            knowledge_id = result.get("knowledge_id")
            summary = (
                self._get_knowledge_summary(knowledge_id) if knowledge_id else None
            )
            if summary:
                try:
                    similar_videos = find_similar_videos(
                        user_id=user_id,
                        summary=summary,
                        current_knowledge_id=knowledge_id,
                    )
                    logger.info(
                        f"[FIND_SIMILAR] 중복 영상 유사 검색 완료: {len(similar_videos)}개"
                    )
                except Exception as e:
                    logger.warning(f"[FIND_SIMILAR] 유사 영상 검색 실패: {e}")

        return {
            "intent": IntentType.FIND_SIMILAR.value,
            "detected_url": detected_url,
            "video_id": video_id,
            "user_id": user_id,
            "pipeline": result,
            "similar_videos": similar_videos,
        }

    @staticmethod
    def _get_knowledge_summary(knowledge_id: str) -> str | None:
        """knowledge_id로 summary 조회"""
        from database import SessionLocal
        from sqlalchemy import text as sql_text

        db = SessionLocal()
        try:
            row = db.execute(
                sql_text("SELECT summary FROM knowledge WHERE id = CAST(:kid AS uuid)"),
                {"kid": knowledge_id},
            ).fetchone()
            return row[0] if row and row[0] else None
        except Exception as e:
            logger.warning(f"[FIND_SIMILAR] summary 조회 실패: {e}")
            return None
        finally:
            db.close()

    def handle_search(
        self,
        user_id: int,
        user_message: str,
    ) -> dict:
        logger.info("➔ SEARCH 의도 감지. RAG 검색 파이프라인 실행")

        search_result = search_and_answer(user_id, user_message)

        session = SessionLocal()
        try:
            # notion_connection 테이블에서 해당 사용자의 정보를 가져오기
            conn = session.query(NotionConnection).filter_by(user_id=user_id).first()

            # 이메일 정보 있는지 확인
            if conn and conn.owner_user_email:
                recipient_email = conn.owner_user_email

                # 3. 이메일 발송
                send_search_result_email(
                    recipient_email=recipient_email,
                    query=user_message,
                    answer=search_result["answer"],
                    chunks=search_result.get("chunks", []),
                )
                logger.info(f"노션 연동 메일({recipient_email})로 검색 결과 전송 완료")
            else:
                logger.warning(
                    f"사용자 {user_id}의 NotionConnection 정보나 이메일이 없습니다."
                )

        except Exception as e:
            logger.error(f"노션 이메일 조회 및 발송 중 오류: {e}")
        finally:
            session.close()

        return {
            "intent": IntentType.SEARCH.value,
            "user_id": user_id,
            "result": search_result["answer"],
            "sources": search_result.get("sources", 0),
        }

    @staticmethod
    def parse_youtube_video_id(url: str | None) -> str | None:
        if not url:
            return None

        pattern = (
            r"(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?|shorts)\/|.*[?&]v=)"
            r"|youtu\.be\/)([^\"&?\/\s]{11})"
        )
        match = re.search(pattern, url)
        if match:
            return match.group(1)
        return None
