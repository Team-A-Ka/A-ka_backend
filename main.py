import os
from fastapi import FastAPI
import uvicorn
from database import engine
from app import models
from app.routers.api import api_router

# Celery 앱 문맥을 FastAPI 구동 시 메모리에 적재하여
# @shared_task나 @celery_app.task들이 올바른 설정값(Broker 등)을 바라보게 합니다.
from app.core.celery_app import celery_app

# models.Base.metadata.create_all(bind=engine)
# alembic 도입했으므로 주석처리함


app = FastAPI()

app.include_router(api_router, prefix="/api/v1")

if __name__ == "__main__":
    # Railway에서 PORT 환경 변수를 주면 그걸 쓰고, 없으면 8080을 사용.
    port = int(os.environ.get("PORT", 8080))

    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
