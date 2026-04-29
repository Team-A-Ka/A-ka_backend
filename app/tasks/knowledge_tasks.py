# 실패 시 retry / 재시도 제어
# service/repository 호출 + retry/failure 제어

# tasks.py
#  ├── service 호출
#  ├── retry 처리

import asyncio

from celery import shared_task
from celery.utils.log import get_task_logger
from app.repositories.knowledge import create_base
from app.services.knowledge_pipeline import KnowledgePipelineService
from app.services.save_only_service import SaveOnlyService
from celery import chain

logger = get_task_logger(__name__)

knowledge_pipeline_service = KnowledgePipelineService()
save_only_service = SaveOnlyService()


# ==========================================
# Step 1: 수집 + 청킹
# ==========================================
@shared_task(bind=True, name="knowledge.collect_and_chunk")
def collect_and_chunk_task(self, video_id: str):
    return knowledge_pipeline_service.collect_and_chunk(video_id)


# ==========================================
# Step 2: AI 추론 그래프
# ==========================================
@shared_task(bind=True, name="knowledge.run_intelligence")
def run_intelligence_graph_task(self, data: dict):

    return knowledge_pipeline_service.run_intelligence(data)


# ==========================================
# Step 3: 완료 처리
# ==========================================
@shared_task(bind=True, name="knowledge.update_status")
def update_pipeline_status_task(self, data: dict):
    return knowledge_pipeline_service.publish_pipeline_result(data)


# ==========================================
# 에러 핸들러
# ==========================================
@shared_task(bind=True, name="knowledge.handle_failure")
def handle_pipeline_failure_task(self, task_id, video_id: str):
    return knowledge_pipeline_service.handle_failure(video_id, task_id)


# ==========================================
# 단순 링크 저장 (SAVE_ONLY) 진입점
# ==========================================
@shared_task(bind=True, name="knowledge.save_link_only")
def save_link_only_task(self, video_id: str):
    """
    LangGraph 요약을 타지 않고 단순 링크만 저장
    """
    try:
        return save_only_service.save(video_id)

    except Exception as exc:
        raise self.retry(exc=exc, countdown=5)


# ==========================================
# ⭐️ 파이프라인 진입점 — chat_command.py에서 호출
# ==========================================
def run_core_pipeline_task(video_id: str):
    """
    실행 순서 (순차 chain):
    (수집+청킹) → (LangGraph: 요약→벡터화→개요) → (완료)
    """
    logger.info(f"====== 파이프라인 트리거 (video_id: {video_id}) ======")
    try:
        # 1. 파이프라인 시작 전에 Knowledge + YoutubeMetadata 빈 레코드 생성
        knowledge_db_id = asyncio.run(create_base(video_id))
        logger.info(f"DB 초기 레코드 생성 성공: {knowledge_db_id}")

    except Exception as e:
        logger.error(f"파이프라인 시작 실패 (DB 초기화 에러): {e}")
        return "Failed to start pipeline: DB Error"

    workflow = chain(
        collect_and_chunk_task.s(video_id),  # Step 1: 현지/수왕
        run_intelligence_graph_task.s(),  # Step 2: 채훈 (LangGraph)
        update_pipeline_status_task.s(),  # Step 3: 완료
    ).on_error(handle_pipeline_failure_task.s(video_id))

    workflow.delay()

    return {
        "video_id": video_id,
        # "status": "QUEUED", 흠!!!!!!!
    }
