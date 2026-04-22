from fastapi import APIRouter
from .endpoints import youtube_transcript

api_router = APIRouter()

api_router.include_router(
    youtube_transcript.router, prefix="/youtube", tags=["youtube"]
)
