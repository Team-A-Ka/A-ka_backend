import logging

from app.repositories.knowledge import save_link_only
from app.services.knowledge_pipeline import run_async
from app.services.youtube_service import YouTubeService

logger = logging.getLogger("aka.save_only")


class SaveOnlyService:
    def __init__(self):
        self.youtube_service = YouTubeService()

    def save(self, video_id: str, user_id: int):
        metadata = self.youtube_service.get_metadata(video_id)
        title = metadata.get("video_title", f"영상 {video_id}")

        # DB 저장 (Knowledge + YoutubeMetadata, status=COMPLETED)
        knowledge_id = run_async(save_link_only(video_id, metadata, user_id))

        logger.info(f"[단순 저장 완료] knowledge_id={knowledge_id}, 제목: {title}")
        return {
            "video_id": video_id,
            "knowledge_id": str(knowledge_id),
            "title": title,
            "status": "COMPLETED",
        }