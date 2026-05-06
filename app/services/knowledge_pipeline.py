import asyncio
from celery.utils.log import get_task_logger
from app.services.intelligence_service import IntelligenceService
from app.services.transcript_chunking import chunk_by_time
from app.services.transcript_refine import refine_transcript_segments
from app.services.youtube_service import YouTubeService



# repositories — Step 1/2/3/실패 단계의 DB 호출 진입점
# (실제 SQL/모델 조작은 모두 repositories.knowledge 안에 캡슐화됨)
from app.repositories.knowledge import (
    save_chunks_to_db,
    save_intelligence_result,
    mark_completed,
    mark_failed,
)

# TODO: Pydantic 기반 State 통일(structured_output)

logger = get_task_logger(__name__)


class KnowledgePipelineService:
    def __init__(self):
        self.youtube_service = YouTubeService()
        # TODO(향후 고도화): 매 태스크마다 IntelligenceService 인스턴스를 새로 생성하는 것은 비효율적임.
        # 모듈 레벨 싱글톤 패턴 또는 의존성 주입(DI) 방식으로 변경하여 재사용성 및 메모리 효율 개선 필요.
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
        # DB에 저장된 후 'ID(UUID)'가 채워진 데이터를 변수에 담기
        saved_chunks = asyncio.run(save_chunks_to_db(video_id, metadata, final_chunks))

        # 마지막 return에서 final_chunks 대신 'ID가 포함된' saved_chunks를 돌려주기
        return {
            "video_id": video_id,
            "metadata": metadata,
            "chunks": saved_chunks,
        }

    def run_intelligence(self, data: dict):
        """Step 2 — LangGraph 실행 + 결과 DB 반영.

        흐름:
          1) 빈 chunks 가드 — Step 1에서 자막 추출 실패 시 LangGraph 스킵 + fallback dict 반환.
          2) IntelligenceService.run() — LangGraph(요약 → 벡터화 → 개요 생성) 동기 실행.
          3) save_intelligence_result() — 단일 트랜잭션으로 Knowledge.title/summary, YoutubeKnowledgeChunk.summary_detail 및 embedding UPDATE.
          4) DB UPDATE 실패하면 바로 예외 던져서 핸들러가 처리하도록 함.
        """
        video_id = data.get("video_id")
        chunks = data.get("chunks", [])
        metadata = data.get("metadata")

        if not chunks:
            logger.warning(
                f"[Step 2] chunks 비어있음 — 파이프라인 중단 (video_id: {video_id})"
            )
            # 빈 chunks는 요약 불가 → FAILED 상태로 확정 짓고 에러를 던져 체인을 끊음
            asyncio.run(mark_failed(video_id, reason="자막을 추출할 수 없어 요약을 생성하지 못했습니다."))
            raise ValueError(f"자막 추출 실패 (빈 chunks) - video_id: {video_id}")

        result = self.intelligence_service.run(
            {
                "video_id": video_id,
                "chunks": chunks,
                "metadata": metadata,
            }
        )

        # ── DB 반영 (#2): LangGraph 산출물을 단일 트랜잭션으로 UPDATE
        try:
            asyncio.run(
                save_intelligence_result(
                    video_id=video_id,
                    title=result["title"],
                    summary=result["full_summary"],
                    summarized_chunks=result.get("summarized_chunks", []),
                )
            )
        except Exception as e:
            # 단일 트랜잭션 실패 — 데이터 불일치 방지를 위해 에러를 던지고 FAILED 처리하도록 함
            logger.error(f"[Step 2] save_intelligence_result 실패: {e}")
            raise

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
