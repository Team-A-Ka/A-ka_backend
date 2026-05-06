import asyncio

from celery.utils.log import get_task_logger

from app.repositories.knowledge import save_link_only
from app.services.youtube_service import YouTubeService

logger = get_task_logger(__name__)


class SaveOnlyService:
    def __init__(self):
        self.youtube_service = YouTubeService()

    def save(self, video_id: str):
        metadata = self.youtube_service.get_metadata(video_id)
        title = metadata.get("video_title", f"영상 {video_id}")
        knowledge_id = asyncio.run(save_link_only(video_id, metadata))

        logger.info(f"[SAVE_ONLY] Saved knowledge_id={knowledge_id}, title={title}")
        return {
            "video_id": video_id,
            "knowledge_id": str(knowledge_id),
            "title": title,
            "status": "COMPLETED",
        }
