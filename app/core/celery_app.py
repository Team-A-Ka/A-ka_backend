import os
from celery import Celery
from app.core.config import settings

# Celery 앱 인스턴스 생성
# Redis를 메시지 브로커(Broker)와 결과 저장소(Backend)로 모두 사용
celery_app = Celery("aka_tasks", broker=settings.REDIS_URL, backend=settings.REDIS_URL)

# Celery 설정 업데이트
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Seoul",
    enable_utc=False,
    # Task 에러 발생 시 재시도 간격 등 추가 설정 가능
    # task_acks_late=True,
)

# 생성될 task 모듈들을 명시적으로 임포트
celery_app.conf.imports = [
    "app.tasks.router_tasks",
    "app.tasks.knowledge_tasks",
]
