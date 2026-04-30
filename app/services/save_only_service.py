import asyncio

from celery.utils.log import get_task_logger

from app.services.youtube_service import YouTubeService
from app.repositories.knowledge import save_link_only

logger = get_task_logger(__name__)


# ==========================================
# 단순 링크 저장 (SAVE_ONLY) 진입점
# ==========================================
class SaveOnlyService:
    """LangGraph(요약/벡터화/카테고리)를 거치지 않고 메타데이터만 DB에 박는 경로.

    - 호출자: tasks/knowledge_tasks.py::save_link_only_task
    - 상태: 진입 즉시 status=COMPLETED 로 INSERT (PENDING → COMPLETED 단계 분리 없음)
    - user_id 매핑은 향후 작업(#3 user_id ↔ User.id)에서 보강 — 현재는 repository 기본값 사용.
    """

    def __init__(self):
        self.youtube_service = YouTubeService()

    def save(self, video_id: str, user_id: str):
        metadata = self.youtube_service.get_metadata(video_id)
        title = metadata.get("video_title", f"영상 {video_id}")

        # DB 저장 (Knowledge + YoutubeMetadata, status=COMPLETED)
        knowledge_id = asyncio.run(save_link_only(video_id, metadata, user_id))

        logger.info(f"[단순 저장 완료] knowledge_id={knowledge_id}, 제목: {title}")
        return {
            "video_id": video_id,
            "knowledge_id": str(knowledge_id),
            "title": title,
            "status": "COMPLETED",
        }
