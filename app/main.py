from fastapi import FastAPI
from app.routers.api import api_router # 경로 수정됨

# Celery 앱 문맥을 FastAPI 구동 시 1순위로 메모리에 적재하여 
# @shared_task들이 올바른 Broker(127.0.0.1)를 바라보게 구성합니다.
from app.core.celery_app import celery_app

app = FastAPI(title="A-Ka Backend API")

# 모아둔 라우터를 /api/v1 주소 아래에 포함시키기
app.include_router(api_router, prefix="/api/v1")

@app.get("/")
def read_root():
    return {"message": "Server is running!"}