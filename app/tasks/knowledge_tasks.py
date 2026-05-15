import logging

from celery import chain, shared_task

from app.core.celery_app import celery_app
from app.repositories.knowledge import create_base, mark_failed
from app.services.knowledge_pipeline import (
    KnowledgePipelineService,
    check_duplicate_hit_count,
    save_summary_to_user_notion,
    run_async,
)
from app.services.save_only_service import SaveOnlyService
from app.services.user_notification_service import send_user_processing_error_email
from app.services.youtube_service import YouTubeService 

logger = logging.getLogger("aka.upload")

knowledge_pipeline_service = KnowledgePipelineService()
save_only_service = SaveOnlyService()
youtube_service = YouTubeService()


# ==========================================
# Step 1: 수집 + 청킹
# ==========================================
@celery_app.task(bind=True, name="knowledge.collect_and_chunk")
def collect_and_chunk_task(self, video_id: str, user_id: int, include_similar: bool = False):
    return knowledge_pipeline_service.collect_and_chunk(video_id, user_id, include_similar)


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
def handle_pipeline_failure_task(self, request, exc, traceback, video_id: str, user_id: int):
    task_id = getattr(request, "id", None) or str(request)
    result = knowledge_pipeline_service.handle_failure(video_id, task_id)
    send_user_processing_error_email(
        user_id=user_id,
        error=exc,
        user_message=f"https://www.youtube.com/watch?v={video_id}",
        context="YouTube summary pipeline",
    )
    return result


# ==========================================
# 단순 링크 저장 (SAVE_ONLY) 진입점
# ==========================================
@shared_task(bind=True, name="knowledge.save_link_only", max_retries=3)
def save_link_only_task(self, video_id: str, user_id: int, category_name: str = "미분류"):
    """
    LangGraph 요약을 타지 않고 단순 링크만 저장.
    Celery retry 모두 소진 시 status=FAILED 마킹 후 raise.
    """
    try:
        return save_only_service.save(video_id, user_id, category_name=category_name)

    except Exception as exc:
        # 재시도 여력 있으면 retry, 없으면 status=FAILED 마킹 후 최종 raise
        try:
            raise self.retry(exc=exc, countdown=5)
        except self.MaxRetriesExceededError:
            logger.error(
                f"[SAVE_ONLY] 최대 재시도 초과 — status=FAILED 마킹 (video_id: {video_id})"
            )
            try:
                run_async(mark_failed(video_id, reason=f"SAVE_ONLY 최종 실패: {exc}"))
            except Exception as e:
                logger.error(f"[SAVE_ONLY] mark_failed 호출 실패: {e}")
            send_user_processing_error_email(
                user_id=user_id,
                error=exc,
                user_message=f"https://www.youtube.com/watch?v={video_id}",
                context="YouTube link save",
            )
            raise


# ==========================================
# ⭐️ 파이프라인 진입점 — chat_command.py에서 호출
# ==========================================
def run_core_pipeline_task(
    url: str,
    video_id: str,
    user_id: int,
    include_similar: bool = False,
):
    """
    실행 순서 (순차 chain):
    (수집+청킹) → (LangGraph: 요약→벡터화→개요) → (완료)

    include_similar=True면 Step3에서 find_similar_videos를 자동 호출 (FIND_SIMILAR 의도용).
    UPLOAD 의도는 기본값 False라 유사검색이 발화하지 않는다.
    """
    logger.info(f"====== 파이프라인 트리거 (video_id: {video_id}) ======")
    try:
        is_shorts = youtube_service.is_shorts_url(url)
        logger.info(f"[URL CHECK] url={url}, is_shorts={is_shorts}")

        duplicate_result = run_async(check_duplicate_hit_count(video_id, user_id))

        # FAILED 상태 영상은 재처리 허용 — duplicate 체크에서 제외
        if duplicate_result and duplicate_result.get("status") != "FAILED":
            logger.info(
                f"중복 영상 감지: video_id={video_id}, "
                f"user_id={user_id}, hit_count={duplicate_result['hit_count']}"
            )

            # SAVE_ONLY로만 저장된 레코드 (summary 없는 COMPLETED)
            # UPLOAD 요청이면 파이프라인을 실행해 요약 생성
            # SAVE_ONLY 요청(include_similar=False이며 호출 맥락이 save_only)이면 중복 반환
            if duplicate_result.get("needs_summary"):
                if include_similar is not None:
                    # UPLOAD / FIND_SIMILAR 의도 → 요약 파이프라인 실행
                    logger.info(
                        f"[SAVE_ONLY→UPLOAD] summary 없는 중복 레코드 감지 — "
                        f"파이프라인 실행해 요약 생성 (knowledge_id={duplicate_result['knowledge_id']})"
                    )
                    # 기존 레코드 재사용 (create_base 스킵) — 파이프라인에 knowledge_id 전달
                    workflow = chain(
                        collect_and_chunk_task.s(video_id, user_id, include_similar),
                        run_intelligence_graph_task.s(),
                        update_pipeline_status_task.s(),
                    ).on_error(handle_pipeline_failure_task.s(video_id, user_id))
                    result = workflow.delay()
                    return {
                        "video_id": video_id,
                        "status": "QUEUED_SUMMARY",
                        "task_id": result.id,
                        "hit_count": duplicate_result["hit_count"],
                        "knowledge_id": duplicate_result["knowledge_id"],
                    }

            response = {
                "video_id": video_id,
                "user_id": user_id,
                "status": "duplicate",
                "duplicate": True,
                "hit_count": duplicate_result["hit_count"],
                "knowledge_id": duplicate_result["knowledge_id"],
            }

            if duplicate_result.get("status") == "COMPLETED" and not duplicate_result.get("needs_summary"):
                notion_page = save_summary_to_user_notion(
                    user_id=user_id,
                    video_id=video_id,
                    title=duplicate_result.get("title")
                    or f"YouTube summary {video_id}",
                    full_summary=duplicate_result.get("summary") or "Summary is empty.",
                    category=duplicate_result.get("category"),
                    hit_count=duplicate_result.get("hit_count"),
                )
                response["status"] = "duplicate_no_notion"
                if notion_page:
                    response["status"] = (
                        "duplicate_hit_count_updated_in_notion"
                        if notion_page.get("action") == "updated_hit_count"
                        else "duplicate_saved_to_notion"
                    )
                response["notion_page"] = notion_page

            return response
                
        if is_shorts:
            logger.info("[Shorts 감지] 요약 없이 즉시 저장을 시작합니다.")
            result = save_link_only_task.delay(
                video_id,
                user_id,
                category_name="쇼츠",
            )

            return {
                "video_id": video_id,
                "category": "쇼츠",
                "task_id": result.id,
            }

        # 1. 파이프라인 시작 전에 Knowledge + YoutubeMetadata 빈 레코드 생성
        knowledge_db_id = run_async(create_base(video_id, user_id))
        logger.info(f"DB 초기 레코드 생성 성공: {knowledge_db_id}")

    except Exception as e:
        logger.error(f"파이프라인 시작 실패 (DB 초기화 에러): {e}")
        send_user_processing_error_email(
            user_id=user_id,
            error=e,
            user_message=f"https://www.youtube.com/watch?v={video_id}",
            context="YouTube pipeline startup",
        )
        return "Failed to start pipeline: DB Error"

    workflow = chain(
        collect_and_chunk_task.s(video_id, user_id, include_similar),
        run_intelligence_graph_task.s(),
        update_pipeline_status_task.s(),
    ).on_error(handle_pipeline_failure_task.s(video_id, user_id))

    result = workflow.delay()

    return {
        "video_id": video_id,
        "status": "QUEUED",
        "task_id": result.id,
    }
