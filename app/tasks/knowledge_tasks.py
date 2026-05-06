import asyncio

from celery import chain
from celery.utils.log import get_task_logger

from app.core.celery_app import celery_app
from app.repositories.knowledge import create_base, mark_failed
from app.services.knowledge_pipeline import KnowledgePipelineService
from app.services.save_only_service import SaveOnlyService

logger = get_task_logger(__name__)

knowledge_pipeline_service = KnowledgePipelineService()
save_only_service = SaveOnlyService()


@celery_app.task(bind=True, name="knowledge.collect_and_chunk")
def collect_and_chunk_task(self, video_id: str, user_id: str | int | None = None):
    return knowledge_pipeline_service.collect_and_chunk(video_id, user_id)


@celery_app.task(bind=True, name="knowledge.run_intelligence")
def run_intelligence_graph_task(self, data: dict):
    return knowledge_pipeline_service.run_intelligence(data)


@celery_app.task(bind=True, name="knowledge.update_status")
def update_pipeline_status_task(self, data: dict):
    return knowledge_pipeline_service.publish_pipeline_result(data)


@celery_app.task(bind=True, name="knowledge.handle_failure")
def handle_pipeline_failure_task(self, task_id, video_id: str):
    return knowledge_pipeline_service.handle_failure(video_id, task_id)


@celery_app.task(bind=True, name="knowledge.save_link_only", max_retries=3)
def save_link_only_task(self, video_id: str):
    try:
        return save_only_service.save(video_id)
    except Exception as exc:
        try:
            raise self.retry(exc=exc, countdown=5)
        except self.MaxRetriesExceededError:
            logger.error(f"[SAVE_ONLY] Max retries exceeded: video_id={video_id}")
            try:
                asyncio.run(mark_failed(video_id, reason=f"SAVE_ONLY failed: {exc}"))
            except Exception as mark_exc:
                logger.error(f"[SAVE_ONLY] Failed to mark failed: {mark_exc}")
            raise


def run_core_pipeline_task(video_id: str, user_id: str | int | None = None) -> str:
    logger.info(f"====== Pipeline trigger (video_id: {video_id}) ======")
    try:
        knowledge_user_id = (
            int(user_id) if user_id is not None and str(user_id).isdigit() else 1
        )
        knowledge_db_id = asyncio.run(create_base(video_id, knowledge_user_id))
        logger.info(f"DB initial record created: {knowledge_db_id}")
    except Exception as exc:
        logger.error(f"Failed to start pipeline during DB initialization: {exc}")
        raise

    workflow = chain(
        collect_and_chunk_task.s(video_id, user_id),
        run_intelligence_graph_task.s(),
        update_pipeline_status_task.s(),
    ).on_error(handle_pipeline_failure_task.s(video_id))

    result = workflow.delay()
    return result.id
