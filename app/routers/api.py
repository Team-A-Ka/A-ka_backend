from fastapi import APIRouter
from app.routers.endpoints import webhook

api_router = APIRouter()

# webhook 라우터를 포함 (prefix를 제거하여 webhook.py 내부의 /chat/webhook 경로를 직관적으로 사용)
api_router.include_router(webhook.router, tags=["kakao"])
