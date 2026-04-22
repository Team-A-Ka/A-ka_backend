from fastapi import APIRouter
from app.routers.endpoints import webhook
from app.routers.endpoints import youtube_transcript

api_router = APIRouter()

# webhook 라우터를 포함
api_router.include_router(webhook.router, tags=["kakao"])

# youtube_transcript 라우터를 포함
api_router.include_router(
    youtube_transcript.router, prefix="/youtube", tags=["youtube"]
)
