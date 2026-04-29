from app.services.youtube_service import YouTubeService


# ==========================================
# 단순 링크 저장 (SAVE_ONLY) 진입점
# ==========================================


class SaveOnlyService:
    def __init__(self):
        self.youtube_service = YouTubeService()

    def save(self, video_id: str):
        metadata = self.youtube_service.get_metadata(video_id)

        title = metadata.get("video_title", f"영상 {video_id}")

        # repository.save_link(...)
        return {
            "video_id": video_id,
            "title": title,
            "status": "COMPLETED",
        }
