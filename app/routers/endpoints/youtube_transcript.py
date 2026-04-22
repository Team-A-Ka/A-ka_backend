from fastapi import APIRouter, Query
from app.services.youtube_service import YouTubeService

router = APIRouter()

youtube_service = YouTubeService()


@router.get("/transcript")
def get_transcript(video_id: str = Query(...), language: str = Query("ko")):
    return youtube_service.get_transcript(video_id, language)
