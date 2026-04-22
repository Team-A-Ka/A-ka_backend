from fastapi import FastAPI
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


@app.get("/")
def read_root():
    return {"Hello": "asd"}
