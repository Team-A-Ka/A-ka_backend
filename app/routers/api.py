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

# [디버그용] LangGraph 시각화 라우터 포함
from app.routers.endpoints import debug_graph
api_router.include_router(
    debug_graph.router, prefix="/debug/graph", tags=["debug"]
)
