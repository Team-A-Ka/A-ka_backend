from fastapi import APIRouter
from app.routers.endpoints import webhook # 경로 수정됨

api_router = APIRouter()

# webhook 라우터를 포함
api_router.include_router(webhook.router, prefix="/webhook", tags=["kakao"])
