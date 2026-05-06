import asyncio
from typing import Any

from celery.utils.log import get_task_logger

from app.repositories.knowledge import (
    _update_chunk_embeddings,
    list_category_names,
    mark_failed,
    save_chunks_to_db,
    update_knowledge_after_langgraph,
    update_summary_result_to_db,
)
from app.services.category_resolver import resolve_category_name
from app.services.intelligence_service import IntelligenceService
from app.services.notion_connection_service import (
    create_summary_page_for_user,
    resolve_internal_user_id,
)
from app.services.transcript_chunking import chunk_by_time
from app.services.transcript_refine import refine_transcript_segments
from app.services.youtube_service import YouTubeService
from database import SessionLocal

logger = get_task_logger(__name__)


def run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        return loop.create_task(coro)
    return asyncio.run(coro)


class KnowledgePipelineService:
    def __init__(self):
        self.youtube_service = YouTubeService()
        self.intelligence_service = IntelligenceService()

    def collect_and_chunk(
        self,
        video_id: str,
        user_id: str | int | None = None,
    ) -> dict[str, Any]:
        try:
            metadata = self.youtube_service.get_metadata(video_id)
        except Exception:
            metadata = {
                "video_id": video_id,
                "video_title": "Unknown",
                "channel_name": "Unknown",
                "duration": 0,
            }

        logger.info(f"Using YouTube API key: {bool(self.youtube_service.api_key)}")

        transcript_data = self.youtube_service.get_transcript(video_id)
        if isinstance(transcript_data, str) and transcript_data.startswith("Error"):
            raise ValueError(f"Failed to fetch transcript: {transcript_data}")

        refined_segments = refine_transcript_segments(transcript_data)
        if not refined_segments:
            return {
                "video_id": video_id,
                "user_id": user_id,
                "metadata": metadata,
                "chunks": [],
            }

        chunks = chunk_by_time(refined_segments, 60000)
        logger.info(f"[Step 1] Created {len(chunks)} chunks")

        final_chunks = [
            {
                "chunk_order": index,
                "content": raw_chunk.get("content", ""),
                "start_time": raw_chunk.get("start_time", 0),
            }
            for index, raw_chunk in enumerate(chunks)
        ]

        saved_chunks = run_async(save_chunks_to_db(video_id, metadata, final_chunks))
        if saved_chunks:
            logger.info(f"First chunk start_time: {saved_chunks[0]['start_time']}")
            logger.info(f"First chunk content: {saved_chunks[0]['content'][:50]}")

        return {
            "video_id": video_id,
            "user_id": user_id,
            "metadata": metadata,
            "chunks": saved_chunks,
        }

    def run_intelligence(self, data: dict[str, Any]) -> dict[str, Any]:
        video_id = data.get("video_id")
        chunks = data.get("chunks", [])
        metadata = data.get("metadata")
        user_id = data.get("user_id")

        if not chunks:
            logger.warning(f"[Step 2] chunks empty, skipping LangGraph: {video_id}")
            return {
                "video_id": video_id,
                "user_id": user_id,
                "metadata": metadata,
                "title": f"Video {video_id}",
                "full_summary": "Could not extract transcript, so no summary was generated.",
                "category": "미분류",
                "vector_count": 0,
                "summarized_chunks": [],
            }

        result = self.intelligence_service.run(
            {
                "video_id": video_id,
                "chunks": chunks,
                "metadata": metadata,
            }
        )
        result["user_id"] = user_id

        try:
            run_async(
                update_knowledge_after_langgraph(
                    video_id=video_id,
                    title=result["title"],
                    summary=result["full_summary"],
                    summarized_chunks=result["summarized_chunks"],
                )
            )
        except Exception as exc:
            logger.error(f"[Step 2] Failed to update knowledge result: {exc}")

        if result.get("summarized_chunks"):
            logger.info(
                f"Saving embeddings for {len(result['summarized_chunks'])} chunks"
            )
            run_async(_update_chunk_embeddings(result["summarized_chunks"]))

        logger.info(f"[Step 2: LangGraph] Completed title={result['title']}")
        return result

    def publish_pipeline_result(self, data: dict[str, Any]) -> dict[str, Any]:
        video_id = data.get("video_id")
        user_id = data.get("user_id")
        title = data.get("title", "")
        full_summary = data.get("full_summary", "")
        raw_category = data.get("category")

        db_result = None
        resolved_category = raw_category
        if video_id:
            existing_categories = run_async(list_category_names())
            resolved_category = resolve_category_name(
                raw_category=raw_category,
                title=title,
                summary=full_summary,
                existing_categories=existing_categories,
            )
            logger.info(
                f"[Category] raw={raw_category}, resolved={resolved_category}"
            )

            db_result = run_async(
                update_summary_result_to_db(
                    video_id=video_id,
                    title=title,
                    summary=full_summary,
                    category_name=resolved_category,
                )
            )

        notion_page = None
        if user_id:
            notion_page = save_summary_to_user_notion(
                user_id=user_id,
                video_id=video_id,
                title=title,
                full_summary=full_summary,
            )

        logger.info(f"[Step 3] Completed video_id={video_id}, title={title}")
        return {
            "status": "Pipeline All Done",
            "video_id": video_id,
            "raw_category": raw_category,
            "resolved_category": resolved_category,
            "db_result": db_result,
            "notion_page": notion_page,
        }

    def handle_failure(self, video_id: str, task_id: str) -> None:
        logger.error(f"[Error] Pipeline failed (video_id={video_id}, task={task_id})")
        try:
            run_async(mark_failed(video_id, reason=f"Task {task_id} failed"))
        except Exception as exc:
            logger.error(f"[Error] Failed to mark pipeline failure: {exc}")


def save_summary_to_user_notion(
    user_id: str | int,
    video_id: str,
    title: str,
    full_summary: str,
) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        internal_user_id = resolve_internal_user_id(db, user_id)
        if internal_user_id is None:
            logger.warning(f"[Notion] user_id={user_id} could not be resolved.")
            return None

        page = create_summary_page_for_user(
            db=db,
            user_id=internal_user_id,
            title=title or f"YouTube summary {video_id}",
            summary=full_summary or "Summary is empty.",
            source_url=f"https://www.youtube.com/watch?v={video_id}",
        )
        if page is None:
            logger.info(
                f"[Notion] user_id={internal_user_id} has no ready Notion connection."
            )
            return None

        logger.info(f"[Notion] Summary page saved: {page.get('url')}")
        return {"id": page.get("id"), "url": page.get("url")}
    except Exception as exc:
        logger.warning(f"[Notion] Failed to save summary page: {exc}")
        return None
    finally:
        db.close()
