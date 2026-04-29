import asyncio
from celery.utils.log import get_task_logger
from app.services.intelligence_service import IntelligenceService
from app.services.transcript_chunking import chunk_by_time
from app.services.transcript_refine import refine_transcript_segments
from app.services.youtube_service import YouTubeService
from app.repositories.knowledge import save_chunks_to_db

# repositories — Step 1/2/3/실패 단계의 DB 호출 진입점
# (실제 SQL/모델 조작은 모두 repositories.knowledge 안에 캡슐화됨)
from app.repositories.knowledge import (
    save_chunks_to_db,
    update_knowledge_after_langgraph,
    mark_completed,
    mark_failed,
)

# TODO: Pydantic 기반 State 통일(structured_output)

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
        """Step 2 — LangGraph 실행 + 결과 DB 반영.

        흐름:
          1) 빈 chunks 가드 — Step 1에서 자막 추출 실패 시 LangGraph 스킵 + fallback dict 반환.
          2) IntelligenceService.run() — LangGraph(요약 → 벡터화 → 개요 생성) 동기 실행.
          3) update_knowledge_after_langgraph() — Knowledge.title/summary, YoutubeKnowledgeChunk.summary_detail UPDATE.
             - category_name → category_id 매핑은 향후 작업(#4)에서 추가.
             - embeddings 저장은 향후 작업(#5: embedding 컬럼 추가) 후 별도 함수에서 처리.
          4) DB UPDATE 실패해도 chain 자체는 진행 (Step 3 / 핸들러에서 종합 처리).
        """
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

        # ── DB 반영 (#2): LangGraph 산출물을 Knowledge / YoutubeKnowledgeChunk 에 UPDATE
        try:
            asyncio.run(
                update_knowledge_after_langgraph(
                    video_id=video_id,
                    title=result["title"],
                    summary=result["full_summary"],
                    summarized_chunks=result["summarized_chunks"],
                )
            )
        except Exception as e:
            # 부분 실패 — chain은 계속, 핸들러가 종합 처리
            logger.error(f"[Step 2] update_knowledge_after_langgraph 실패: {e}")

        logger.info(f"[Step 2: LangGraph] 완료 — 제목: {result['title']}")
        return result

    def publish_pipeline_result(self, data: dict):
        """Step 3 — Knowledge.status = COMPLETED + (향후) 노션 업로드 트리거.

        - mark_completed(): 정상 종료 시 status UPDATE. 레코드 없으면 best-effort로 경고만 남김.
        - 노션 업로드: 별도 작업 (TODO).
        """
        video_id = data.get("video_id")
        title = data.get("title")
        full_summary = data.get("full_summary")
        # vector_count = data.get("vector_count", 0)

        # 1) Status 업데이트 (#3)
        try:
            asyncio.run(mark_completed(video_id))
        except Exception as e:
            logger.error(f"[Step 3] mark_completed 실패: {e}")

        # 2) 노션 업로드 트리거 (TODO: 별도 작업)
        # self._trigger_notion_upload(video_id, full_summary)

        logger.info(
            f"[Step 3] 완료 video_id={video_id}, title={title}, full_summary={full_summary}"
        )
        return "Pipeline All Done"

    def handle_failure(self, video_id: str, task_id: str):
        """파이프라인 실패 시 Knowledge.status = FAILED.

        chain.on_error()로 연결되어 Step 1/2/3 어느 단계 raise든 호출됨.
        mark_failed는 best-effort — 핸들러 안에서 또 raise되어 연쇄 실패 나는 것을 방지.
        """
        logger.error(f"[Error] 파이프라인 에러 (video_id: {video_id}, task: {task_id})")
        try:
            asyncio.run(mark_failed(video_id, reason=f"Task {task_id} failed"))
        except Exception as e:
            logger.error(f"[Error] mark_failed 호출 실패: {e}")
