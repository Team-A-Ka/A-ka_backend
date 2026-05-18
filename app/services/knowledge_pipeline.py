import asyncio
import logging
from typing import Any


from app.repositories.knowledge import (
    KnowledgeRepository,
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
from app.services.notion_service import NotionServiceError
from app.services.search_service import find_similar_videos
from app.core.llm import get_chat_model_primary
from langchain_core.messages import SystemMessage, HumanMessage
from app.services.transcript_chunking import chunk_by_semantic
from app.services.transcript_refine import refine_transcript_segments
from app.services.smtp_service import send_search_result_email
from app.models.notion import NotionConnection
from app.models.knowledge import YoutubeKnowledgeChunk, YoutubeMetadata
from app.services.youtube_service import YouTubeService
from database import SessionLocal, async_session_maker
from sqlalchemy.orm import Session

# 메서드/함수 흐름에 따라 도메인 카테고리 logger를 분리한다.
upload_logger = logging.getLogger("aka.upload")
step1_logger = logging.getLogger("aka.upload.step1")
step2_logger = logging.getLogger("aka.upload.step2")
step3_logger = logging.getLogger("aka.upload.step3")
notion_logger = logging.getLogger("aka.notion")

SEMANTIC_CHUNK_THRESHOLD = 0.35
SEMANTIC_MIN_PARAGRAPH_CHARS = 150
SEMANTIC_MIN_CHUNK_CHARS = 0


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
        user_id: int | None = None,
        include_similar: bool = False,
        embedded_question: str | None = None,
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

        step1_logger.info(f"Using YouTube API key: {bool(self.youtube_service.api_key)}")

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
                "include_similar": include_similar,
                "embedded_question": embedded_question,
            }

        chunks = chunk_by_semantic(
            refined_segments,
            similarity_threshold=SEMANTIC_CHUNK_THRESHOLD,
            min_paragraph_chars=SEMANTIC_MIN_PARAGRAPH_CHARS,
            min_chunk_chars=SEMANTIC_MIN_CHUNK_CHARS,
        )
        step1_logger.info(f"Created {len(chunks)} chunks")

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
            step1_logger.info(f"First chunk start_time: {saved_chunks[0]['start_time']}")
            step1_logger.info(f"First chunk content: {saved_chunks[0]['content'][:50]}")

        return {
            "video_id": video_id,
            "user_id": user_id,
            "metadata": metadata,
            "chunks": saved_chunks,
            "include_similar": include_similar,
            "embedded_question": embedded_question,
        }

    def run_intelligence(self, data: dict[str, Any]) -> dict[str, Any]:
        video_id = data.get("video_id")
        chunks = data.get("chunks", [])
        metadata = data.get("metadata")
        user_id = data.get("user_id")
        include_similar = data.get("include_similar", False)
        embedded_question = data.get("embedded_question")

        if not chunks:
            reason = f"자막/STT 추출 후 chunks 없음 (video_id={video_id})"
            step2_logger.warning(reason)
            run_async(mark_failed(video_id, reason=reason))
            raise ValueError(reason)

        result = self.intelligence_service.run(
            {
                "video_id": video_id,
                "chunks": chunks,
                "metadata": metadata,
            }
        )
        result["user_id"] = user_id
        result["include_similar"] = include_similar
        result["embedded_question"] = embedded_question

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
            step2_logger.error(f"Failed to update knowledge result: {exc}")

        if result.get("summarized_chunks"):
            step2_logger.info(
                f"Saving embeddings for {len(result['summarized_chunks'])} chunks"
            )
            run_async(_update_chunk_embeddings(result["summarized_chunks"]))

        step2_logger.info(f"LangGraph completed title={result['title']}")
        # Celery chain(JSON)에 1536차원 embedding을 넣으면 Step3 전달이 깨질 수 있어 제외한다.
        result["summarized_chunks"] = _chunks_for_celery_chain(
            result.get("summarized_chunks", [])
        )
        return result

    def publish_pipeline_result(self, data: dict[str, Any]) -> dict[str, Any]:
        video_id = data.get("video_id")
        user_id = data.get("user_id")
        title = data.get("title", "")
        full_summary = data.get("full_summary", "")
        raw_category = data.get("category")
        include_similar = data.get("include_similar", False)
        embedded_question = data.get("embedded_question")

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
            step3_logger.info(f"Category raw={raw_category}, resolved={resolved_category}")

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
            hit_count = db_result.get("hit_count", 1) if db_result else 1
            body_summary = resolve_body_summary_for_notion(
                data,
                db_result=db_result,
            )
            step3_logger.info(
                "Notion body_summary built=%s len=%s chunks_in_task=%s",
                bool(body_summary),
                len(body_summary or ""),
                len(data.get("summarized_chunks") or []),
            )
            notion_page = save_summary_to_user_notion(
                user_id=user_id,
                video_id=video_id,
                title=title,
                full_summary=full_summary,
                body_summary=body_summary,
                category=resolved_category,
                hit_count=hit_count,
            )
            # 유사 영상 검색 — FIND_SIMILAR 의도(include_similar=True)일 때만 실행
            # UPLOAD 의도는 자동 호출하지 않음
        similar_videos = []
        if include_similar and user_id and db_result:
            current_knowledge_id = db_result.get("knowledge_id")
            if current_knowledge_id:
                try:
                    similar_videos = find_similar_videos(
                        user_id=int(user_id),
                        summary=full_summary,
                        current_knowledge_id=current_knowledge_id,
                    )
                except Exception as e:
                    step3_logger.warning(f"유사 영상 검색 실패 (파이프라인 영향 없음): {e}")

        # RAG 답변 처리 (embedded_question)
        if embedded_question and user_id and db_result:
            try:
                db = SessionLocal()
                internal_user_id = resolve_internal_user_id(db, user_id)
                if internal_user_id:
                    user_conn = db.query(NotionConnection).filter_by(user_id=internal_user_id).first()
                    recipient_email = user_conn.owner_user_email if user_conn else None

                    if recipient_email:
                        step3_logger.info(f"Generating RAG answer for embedded_question: {embedded_question}")
                        chunks_data = data.get("chunks", [])
                        # Chunks to format for the RAG LLM
                        context_parts = []
                        if full_summary:
                            context_parts.append(f"[전체 요약]\n{full_summary}")
                        
                        for i, chunk in enumerate(chunks_data[:10]):  # 앞쪽 청크 위주로 제한
                            content = chunk.get("summary_detail") or chunk.get("content", "")
                            context_parts.append(f"[본문 일부 {i+1}]\n{content}")
                        
                        context_text = "\n\n".join(context_parts)
                        
                        llm = get_chat_model_primary()
                        response = llm.invoke([
                            SystemMessage(
                                content=(
                                    "너는 방금 사용자가 전송한 유튜브 영상의 내용을 기반으로 답변하는 AI 어시스턴트야. "
                                    "아래 [영상 내용]은 영상의 전체 요약과 본문 일부야. "
                                    "반드시 이 내용만을 근거로 사용자의 질문에 답변한다.\n\n"
                                    "[필수 규칙]\n"
                                    "1. 없는 내용 금지: 영상 내용에 없는 내용은 절대 추측하거나 지어내지 않는다.\n"
                                    "2. 존댓말 필수: 모든 문장은 '~입니다', '~해요' 형태의 존댓말로 끝낸다.\n"
                                    "3. 간결하게: 3~5문장으로 친절하고 명확하게 답변한다."
                                )
                            ),
                            HumanMessage(content=f"[영상 내용]\n{context_text}\n\n[질문]\n{embedded_question}")
                        ])
                        
                        answer = getattr(response, "content", "")
                        if answer:
                            url = f"https://www.youtube.com/watch?v={video_id}"
                            pseudo_chunk = {"original_url": url, "title": title}
                            send_search_result_email(
                                recipient_email=recipient_email,
                                query=embedded_question,
                                answer=answer,
                                chunks=[pseudo_chunk]
                            )
            except Exception as e:
                step3_logger.error(f"embedded_question 처리 중 실패: {e}")

        step3_logger.info(f"Completed video_id={video_id}, title={title}")
        return {
            "status": "Pipeline All Done",
            "video_id": video_id,
            "raw_category": raw_category,
            "resolved_category": resolved_category,
            "db_result": db_result,
            "notion_page": notion_page,
            "similar_videos": similar_videos,
        }

    def handle_failure(self, video_id: str, task_id: str) -> None:
        upload_logger.error(f"Pipeline failed (video_id={video_id}, task={task_id})")
        try:
            run_async(mark_failed(video_id, reason=f"Task {task_id} failed"))
        except Exception as exc:
            upload_logger.error(f"Failed to mark pipeline failure: {exc}")


def save_summary_to_user_notion(
    user_id: str | int,
    video_id: str,
    title: str,
    full_summary: str,
    body_summary: str | None = None,
    category: str | None = None,
    hit_count: int | None = 1,
) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        internal_user_id = resolve_internal_user_id(db, user_id)
        if internal_user_id is None:
            notion_logger.warning(f"user_id={user_id} could not be resolved.")
            return None

        page = create_summary_page_for_user(
            db=db,
            user_id=internal_user_id,
            title=title or f"YouTube summary {video_id}",
            summary=full_summary or "Summary is empty.",
            body_summary=body_summary,
            source_url=f"https://www.youtube.com/watch?v={video_id}",
            category=category,
            hit_count=hit_count,
        )
        if page is None:
            notion_logger.info(
                f"user_id={internal_user_id} has no ready Notion connection."
            )
            return None

        notion_logger.info(f"Summary page saved: {page.get('url')}")
        return {
            "id": page.get("id"),
            "url": page.get("url"),
            "action": page.get("_a_ka_action"),
        }
    except NotionServiceError as exc:
        notion_logger.warning(
            "Notion API error (user_id=%s status=%s): %s",
            user_id,
            exc.status_code,
            exc,
        )
        return None
    except Exception as exc:
        notion_logger.warning(f"Failed to save summary page: {exc}")
        return None
    finally:
        db.close()


def _chunks_for_celery_chain(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slim: list[dict[str, Any]] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        slim.append(
            {
                key: value
                for key, value in chunk.items()
                if key != "embedding"
            }
        )
    return slim


def resolve_body_summary_for_notion(
    data: dict[str, Any],
    *,
    db_result: dict[str, Any] | None,
) -> str | None:
    duration_ms = (data.get("metadata") or {}).get("duration")
    body_summary = build_timestamped_summary(
        data.get("summarized_chunks", []),
        duration_ms=duration_ms,
    )
    if body_summary:
        return body_summary

    knowledge_id = (db_result or {}).get("knowledge_id")
    if knowledge_id:
        body_summary = fetch_timestamped_body_summary_for_knowledge(str(knowledge_id))
        if body_summary:
            step3_logger.info(
                "Notion body_summary loaded from DB knowledge_id=%s len=%s",
                knowledge_id,
                len(body_summary),
            )
            return body_summary

    return None


def _chunk_summary_text(chunk: dict[str, Any]) -> str:
    return (chunk.get("summary") or chunk.get("summary_detail") or "").strip()


def fetch_timestamped_body_summary_for_knowledge(knowledge_id: str) -> str | None:
    db = SessionLocal()
    try:
        return _fetch_timestamped_body_summary_for_knowledge(db, knowledge_id)
    finally:
        db.close()


def _fetch_timestamped_body_summary_for_knowledge(
    db: Session,
    knowledge_id: str,
) -> str | None:
    chunks = (
        db.query(YoutubeKnowledgeChunk)
        .filter(YoutubeKnowledgeChunk.knowledge_id == knowledge_id)
        .order_by(YoutubeKnowledgeChunk.chunk_order)
        .all()
    )
    if not chunks:
        return None

    duration_row = (
        db.query(YoutubeMetadata.duration)
        .filter(YoutubeMetadata.knowledge_id == knowledge_id)
        .first()
    )
    duration_ms = duration_row[0] if duration_row else None
    summarized_chunks = [
        {
            "chunk_order": chunk.chunk_order,
            "start_time": chunk.start_time,
            "summary": chunk.summary_detail,
            "summary_detail": chunk.summary_detail,
        }
        for chunk in chunks
    ]
    return build_timestamped_summary(
        summarized_chunks,
        duration_ms=duration_ms,
    )


def build_timestamped_summary(
    summarized_chunks: list[dict[str, Any]],
    *,
    duration_ms: int | None = None,
) -> str | None:
    chunks = [
        chunk
        for chunk in summarized_chunks
        if _chunk_summary_text(chunk)
    ]
    if not chunks:
        return None

    chunks.sort(key=lambda chunk: chunk.get("chunk_order", 0))
    parts = []
    for index, chunk in enumerate(chunks):
        summary = _chunk_summary_text(chunk)
        start_ms = _safe_int(chunk.get("start_time"), default=0)
        end_ms = _timestamp_end_ms(chunks, index, start_ms, duration_ms)
        parts.append(f"[{_format_timestamp_range(start_ms, end_ms)}] {summary}")

    return "\n\n".join(parts)


def _timestamp_end_ms(
    chunks: list[dict[str, Any]],
    index: int,
    start_ms: int,
    duration_ms: int | None,
) -> int | None:
    if index + 1 < len(chunks):
        next_start = _safe_int(chunks[index + 1].get("start_time"), default=0)
        if next_start > start_ms:
            return next_start

    duration = _safe_int(duration_ms, default=0)
    if duration > start_ms:
        return duration
    return None


def _format_timestamp_range(start_ms: int, end_ms: int | None) -> str:
    start = _format_timestamp(start_ms)
    if end_ms is None:
        return start
    return f"{start}~{_format_timestamp(end_ms)}"


def _format_timestamp(ms: int) -> str:
    total_seconds = max(ms, 0) // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def check_duplicate_hit_count(video_id: str, user_id: int):
    async with async_session_maker() as session:
        knowledge_repository = KnowledgeRepository(session)

        existing_knowledge = await knowledge_repository.find_by_user_and_video_id(
            user_id=int(user_id),
            video_id=video_id,
        )

        if not existing_knowledge:
            return None

        duplicate_result = _build_duplicate_result(
            existing_knowledge,
            counted=False,
        )

        existing_status = duplicate_result["status"]

        # FAILED면 hit_count 증가 X → 호출 측에서 재처리 허용
        if existing_status == "FAILED":
            return duplicate_result

        # hit_count는 상태에 관계없이 항상 증가
        updated_knowledge = await knowledge_repository.increase_hit_count(
            existing_knowledge
        )
        duplicate_result["hit_count"] = updated_knowledge.hit_count
        duplicate_result["counted"] = True

        # summary 없는 COMPLETED (SAVE_ONLY로 저장된 레코드)
        # → hit_count는 올렸지만, 요약 파이프라인은 아직 미실행
        # → needs_summary=True 반환: 호출 측에서 UPLOAD이면 파이프라인 실행
        if existing_status == "COMPLETED" and not existing_knowledge.summary:
            duplicate_result["needs_summary"] = True
            return duplicate_result

        return duplicate_result


def _build_duplicate_result(knowledge, counted: bool) -> dict[str, Any]:
    status = getattr(knowledge.status, "value", knowledge.status)
    category = getattr(knowledge, "category", None)
    return {
        "knowledge_id": str(knowledge.id),
        "hit_count": knowledge.hit_count,
        "status": status,
        "duplicate": True,
        "counted": counted,
        "title": knowledge.title,
        "summary": knowledge.summary,
        "category": category.name if category is not None else None,
    }
