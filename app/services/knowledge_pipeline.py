import asyncio
from celery.utils.log import get_task_logger
from app.services.intelligence_service import IntelligenceService
from app.services.transcript_chunking import chunk_by_time
from app.services.transcript_refine import refine_transcript_segments
from app.services.youtube_service import YouTubeService

# TODO: Pydantic 기반 State 통일(structured_output)
from app.repositories.knowledge import save_chunks_to_db, create_base
from app.models.knowledge import Knowledge, YoutubeMetadata, YoutubeKnowledgeChunk
from sqlalchemy import select, update
from database import async_session_maker

logger = get_task_logger(__name__)


# --- Celery에서 async 함수를 실행하기 위한 헬퍼 ---
def run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        return loop.create_task(coro)
    else:
        return asyncio.run(coro)


class KnowledgePipelineService:
    def __init__(self):
        self.youtube_service = YouTubeService()
        self.intelligence_service = IntelligenceService()

    def collect_and_chunk(self, video_id: str):
        """자막 추출 → 정제 → 청킹 → DB 저장"""
        try:
            metadata = self.youtube_service.get_metadata(video_id)
        except Exception:
            metadata = {
                "video_id": video_id,
                "video_title": "Unknown",
                "channel_name": "Unknown",
                "duration": 0,
            }
        logger.info(f"사용중인 API KEY 존재 여부: {bool(self.youtube_service.api_key)}")

        transcript_data = self.youtube_service.get_transcript(video_id)
        if isinstance(transcript_data, str) and transcript_data.startswith("Error"):
            raise ValueError(f"자막 추출 실패: {transcript_data}")

        refine_seg = refine_transcript_segments(transcript_data)

        if not refine_seg:
            return {
                "video_id": video_id,
                "metadata": metadata,
                "chunks": [],
            }

        chunks = chunk_by_time(refine_seg, 60000)
        logger.info(f"[Step 1] 완료: {len(chunks)} 개의 청크 생성")

        final_chunks = []
        for i, raw_chunk in enumerate(chunks):
            final_chunks.append(
                {
                    "chunk_order": i,
                    "content": raw_chunk.get("content", ""),
                    "start_time": raw_chunk.get("start_time", 0),
                }
            )

        # ── DB 저장 로직
        asyncio.run(save_chunks_to_db(video_id, metadata, final_chunks))

        logger.info(f"첫번째 청크 시작시간: {final_chunks[0]['start_time']}")
        logger.info(f"첫번째 청크 내용: {final_chunks[0]['content'][:50]}")

        return {
            "video_id": video_id,
            "metadata": metadata,
            "chunks": final_chunks,
        }

    def run_intelligence(self, data: dict):
        "LangGraph 실행 및 결과 처리"
        """LangGraph를 실행하여 요약 → 벡터화 → 개요 생성을 순차 수행"""

        video_id = data.get("video_id")
        chunks = data.get("chunks", [])
        metadata = data.get("metadata")

        if not chunks:
            logger.warning(
                f"[Step 2] chunks 비어있음 — LangGraph 스킵 (video_id: {video_id})"
            )
            return {
                "video_id": video_id,
                "metadata": metadata,
                "title": f"영상 {video_id}",
                "full_summary": "자막을 추출할 수 없어 요약을 생성하지 못했습니다.",
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
        #### DB ####

        ############

        logger.info(f"[Step 2: LangGraph] 완료 — 제목: {result['title']}")
        return result

    def publish_pipeline_result(self, data: dict):
        """상태 업데이트 및 노션 트리거"""
        video_id = data.get("video_id")
        title = data.get("title")
        full_summary = data.get("full_summary")
        # vector_count = data.get("vector_count", 0)
        # 1. Status 업데이트 (COMPLETED)
        # TODO: Knowledge.status = ProcessStatus.COMPLETED 로직 작성
        # 2. 노션 업로드 트리거
        # self._trigger_notion_upload(video_id)
        logger.info(
            f"[Step 3] 완료 video_id={video_id}, title={title}, full_summary={full_summary} "
        )
        return "Pipeline All Done"

    def handle_failure(self, video_id: str, task_id: str):
        """에러 상태 업데이트"""
        logger.error(f"[Error] 파이프라인 에러 (video_id: {video_id}, task: {task_id})")
        # TODO: Knowledge.status = ProcessStatus.FAILED 로직 작성
