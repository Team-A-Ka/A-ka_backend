import uuid
import logging
import asyncio
from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from database import async_session_maker
from app.models.knowledge import (
    Knowledge,
    YoutubeKnowledgeChunk,
    YoutubeMetadata,
    ProcessStatus,
)

logger = logging.getLogger(__name__)


class KnowledgeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_initial_record(self, video_id: str, user_id: int = 1):
        knowledge_id = uuid.uuid4()

        try:
            knowledge = Knowledge(
                id=knowledge_id,
                user_id=user_id,
                title="처리 중인 영상",
                summary="",
                original_url=f"https://www.youtube.com/watch?v={video_id}",
                source_type="YOUTUBE",
                status="PENDING",
                category_id=1, #나중에 수정   
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )

            youtube_metadata = YoutubeMetadata(
                knowledge_id=knowledge_id,
                video_id=video_id,
                video_title="처리 중인 영상",
                channel_name="",
                duration=0,
            )

            self.session.add(knowledge)
            self.session.add(youtube_metadata)

            await self.session.commit()

            logger.info(f"최초 레코드 생성 완료: knowledge_id={knowledge_id}")
            return knowledge_id

        except Exception as e:
            await self.session.rollback()
            logger.error(f"최초 레코드 생성 실패: {e}")
            raise

async def save_chunks_to_db(video_id: str, metadata:dict, chunks: list):
    async with async_session_maker() as session:
        try:
            result = await session.execute(
                select(Knowledge.id)
                .join(
                    YoutubeMetadata,
                    YoutubeMetadata.knowledge_id == Knowledge.id,
                )
                .where(YoutubeMetadata.video_id == video_id)
                .order_by(Knowledge.created_at.desc())
                .limit(1)
            )

            knowledge_id = result.scalars().first()

            if knowledge_id is None:
                raise Exception(
                    f"video_id={video_id}에 해당하는 Knowledge 레코드가 없습니다."
                )

            metadata_result = await session.execute(
                select(YoutubeMetadata).where(
                    YoutubeMetadata.knowledge_id == knowledge_id
                )
            )
            youtube_metadata = metadata_result.scalars().first()

            if youtube_metadata:
                youtube_metadata.video_id = video_id
                youtube_metadata.video_title = metadata.get("video_title", "")
                youtube_metadata.channel_name = metadata.get("channel_name", "")
                youtube_metadata.duration = metadata.get("duration") or 0
            else:
                session.add(
                    YoutubeMetadata(
                        knowledge_id=knowledge_id,
                        video_id=video_id,
                        video_title=metadata.get("video_title", ""),
                        channel_name=metadata.get("channel_name", ""),
                        duration=metadata.get("duration") or 0,
                    )
                )

            # 3. 청크만 여러 개 저장, ID를 추적하기 위해 리스트에 보관
            saved_objects = []  
            for chunk_data in chunks:
                if not chunk_data:
                    continue


                new_chunk = YoutubeKnowledgeChunk(
                    knowledge_id=knowledge_id,
                    chunk_order=chunk_data.get("chunk_order", 0),
                    content=chunk_data.get("content", ""),
                    start_time=chunk_data.get("start_time", 0),
                )
                session.add(new_chunk)
                saved_objects.append(new_chunk) 

            await session.commit() # DB에 실제 ID가 생성되는 부분
            
            logger.info(f"[Step 1] 청킹 데이터 DB 저장 완료: {len(chunks)}개")

            #ID가 포함된 명단을 반환 (업데이트할 때 ID가 필요하기 때문)
            return [
                {
                    "id": c.id, 
                    "chunk_order": c.chunk_order, 
                    "content": c.content, 
                    "start_time": c.start_time
                } for c in saved_objects
            ]

        except Exception as e:
            await session.rollback()
            logger.error(f"[Step 1] 청킹 데이터 DB 저장 실패: {e}")
            raise   


async def create_base(video_id: str):
    async with async_session_maker() as session:
        repo = KnowledgeRepository(session)
        # DB에 PENDING 레코드 생성
        return await repo.create_initial_record(video_id)
    
# DB의 embedding 컬럼에 숫자를 채워 넣는 함수
async def _update_chunk_embeddings(result_chunks: list):
    """각 Chunk의 ID를 찾아 AI가 만든 벡터 숫자를 업데이트합니다."""
    async with async_session_maker() as session:
        async with session.begin():
            for chunk_data in result_chunks:
                # AI가 돌려준 데이터에 id와 벡터값(embedding)이 있을 때만 작동
                if "id" in chunk_data and "embedding" in chunk_data:
                    stmt = (
                        update(YoutubeKnowledgeChunk)
                        .where(YoutubeKnowledgeChunk.id == chunk_data["id"])
                        .values(embedding=chunk_data["embedding"])
                    )
                    await session.execute(stmt)
        await session.commit()


# ==========================================
# Step 2 결과 반영 — LangGraph 산출물 DB UPDATE  [추가: 채훈, #2]
# ==========================================
async def update_knowledge_after_langgraph(
    video_id: str,
    title: str,
    summary: str,
    summarized_chunks: list,
):
    """LangGraph 실행 결과를 Knowledge + YoutubeKnowledgeChunk 에 반영.

    Knowledge 측:
      - title    ← LangGraph generate_overview 결과
      - summary  ← full_summary

    YoutubeKnowledgeChunk 측:
      - summary_detail ← chunk_order 별로 chunk["summary"]

    주의 / TODO:
      - category_id 는 #6 작업(카테고리 이름 → ID lookup/create) 완료 후 이 함수에 추가 예정.
      - embedding 컬럼은 #7 작업(YoutubeKnowledgeChunk.embedding) 완료 후 별도 함수에서 처리.
      - knowledge_id 매칭은 video_id 기반 (save_chunks_to_db 패턴 재사용).
    """
    async with async_session_maker() as session:
        try:
            # 1) video_id 로 가장 최근 Knowledge 찾기
            result = await session.execute(
                select(Knowledge.id)
                .join(
                    YoutubeMetadata,
                    YoutubeMetadata.knowledge_id == Knowledge.id,
                )
                .where(YoutubeMetadata.video_id == video_id)
                .order_by(Knowledge.created_at.desc())
                .limit(1)
            )
            knowledge_id = result.scalars().first()

            if knowledge_id is None:
                raise Exception(
                    f"video_id={video_id} 에 해당하는 Knowledge 레코드가 없습니다. "
                    f"(create_base / collect_and_chunk 가 먼저 실행됐는지 확인)"
                )

            # 2) Knowledge — title, summary UPDATE
            await session.execute(
                update(Knowledge)
                .where(Knowledge.id == knowledge_id)
                .values(title=title, summary=summary)
            )

            # 3) YoutubeKnowledgeChunk — chunk_order 별로 summary_detail UPDATE
            for chunk in summarized_chunks:
                order = chunk.get("chunk_order")
                summary_detail = chunk.get("summary", "")
                if order is None:
                    continue
                await session.execute(
                    update(YoutubeKnowledgeChunk)
                    .where(
                        YoutubeKnowledgeChunk.knowledge_id == knowledge_id,
                        YoutubeKnowledgeChunk.chunk_order == order,
                    )
                    .values(summary_detail=summary_detail)
                )

            await session.commit()
            logger.info(
                f"[Step 2] Knowledge UPDATE 완료: knowledge_id={knowledge_id}, "
                f"title='{title[:30]}', chunks={len(summarized_chunks)}개 summary_detail 반영"
            )
            return knowledge_id

        except Exception as e:
            await session.rollback()
            logger.error(f"[Step 2] DB UPDATE 실패: {e}")
            raise


# ==========================================
# SAVE_ONLY 의도 — 단일 INSERT (status=COMPLETED)  [추가: 채훈, #1]
# ==========================================
async def save_link_only(video_id: str, metadata: dict, user_id: int = 1):
    """SAVE_ONLY 의도용 — Knowledge + YoutubeMetadata 단일 INSERT.

    LangGraph(요약/벡터화/카테고리 분류)를 거치지 않으므로 chunks/embeddings는 만들지 않음.
    바로 status=COMPLETED 로 처리 종료.

    NOTE:
      - user_id=1 하드코딩은 임시. 카카오 user_id ↔ User.id 매핑은 #5 작업에서 보강.
        (create_initial_record 도 동일한 default를 쓰고 있어 패턴 일치.)
      - category_id 는 None — SAVE_ONLY는 카테고리 분류 안 함.
    """
    knowledge_id = uuid.uuid4()

    async with async_session_maker() as session:
        try:
            knowledge = Knowledge(
                id=knowledge_id,
                user_id=user_id,
                title=metadata.get("video_title", f"영상 {video_id}"),
                summary=None,
                original_url=f"https://www.youtube.com/watch?v={video_id}",
                source_type="YOUTUBE",
                status="COMPLETED",
                category_id=None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )

            youtube_meta = YoutubeMetadata(
                knowledge_id=knowledge_id,
                video_id=video_id,
                video_title=metadata.get("video_title", ""),
                channel_name=metadata.get("channel_name", ""),
                duration=metadata.get("duration") or 0,
            )

            session.add(knowledge)
            session.add(youtube_meta)
            await session.commit()

            logger.info(
                f"[SAVE_ONLY] Knowledge+YoutubeMetadata 저장 완료: "
                f"knowledge_id={knowledge_id}, video_id={video_id}"
            )
            return knowledge_id

        except Exception as e:
            await session.rollback()
            logger.error(f"[SAVE_ONLY] DB 저장 실패: {e}")
            raise


# ==========================================
# Step 3 — 정상 종료 status UPDATE  [추가: 채훈, #3]
# ==========================================
async def mark_completed(video_id: str):
    """파이프라인 정상 종료 시 Knowledge.status = COMPLETED.

    update_pipeline_status (Step 3) 에서 호출.
    - video_id 기반으로 가장 최근 Knowledge 찾기 (save_chunks_to_db / update_knowledge_after_langgraph 패턴 재사용).
    - 레코드 없으면 경고만 찍고 None 리턴 — chain 마지막 단계가 raise로 끊겨 핸들러로 넘어가는 것을 방지.
    """
    async with async_session_maker() as session:
        try:
            result = await session.execute(
                select(Knowledge.id)
                .join(
                    YoutubeMetadata,
                    YoutubeMetadata.knowledge_id == Knowledge.id,
                )
                .where(YoutubeMetadata.video_id == video_id)
                .order_by(Knowledge.created_at.desc())
                .limit(1)
            )
            knowledge_id = result.scalars().first()

            if knowledge_id is None:
                logger.warning(
                    f"[Step 3] mark_completed: video_id={video_id} 레코드 없음 — UPDATE 스킵"
                )
                return None

            await session.execute(
                update(Knowledge)
                .where(Knowledge.id == knowledge_id)
                .values(status=ProcessStatus.COMPLETED)
            )
            await session.commit()
            logger.info(
                f"[Step 3] Knowledge.status = COMPLETED (knowledge_id={knowledge_id})"
            )
            return knowledge_id

        except Exception as e:
            await session.rollback()
            logger.error(f"[Step 3] mark_completed 실패: {e}")
            raise


# ==========================================
# 에러 핸들러 — 실패 status UPDATE  [추가: 채훈, #4]
# ==========================================
async def mark_failed(video_id: str, reason: str = ""):
    """파이프라인 실패 확정 시 Knowledge.status = FAILED.

    호출 위치:
      - handle_pipeline_failure (chain.on_error → UPLOAD 분기 실패)
      - save_link_only_task except (retry exhausted → SAVE_ONLY 분기 최종 실패)

    동작:
      - video_id 기반 가장 최근 Knowledge 찾기. 레코드 없으면 경고만.
      - best-effort: 핸들러가 또 실패하면 로그만 남기고 raise 안 함 (재귀/연쇄 실패 방지).
    """
    async with async_session_maker() as session:
        try:
            result = await session.execute(
                select(Knowledge.id)
                .join(
                    YoutubeMetadata,
                    YoutubeMetadata.knowledge_id == Knowledge.id,
                )
                .where(YoutubeMetadata.video_id == video_id)
                .order_by(Knowledge.created_at.desc())
                .limit(1)
            )
            knowledge_id = result.scalars().first()

            if knowledge_id is None:
                logger.warning(
                    f"[Error] mark_failed: video_id={video_id} 레코드 없음 — UPDATE 스킵 "
                    f"(아주 초반에 죽었거나 SAVE_ONLY가 INSERT 직전에 실패했을 가능성)"
                )
                return None

            await session.execute(
                update(Knowledge)
                .where(Knowledge.id == knowledge_id)
                .values(status=ProcessStatus.FAILED)
            )
            await session.commit()
            logger.info(
                f"[Error] Knowledge.status = FAILED "
                f"(knowledge_id={knowledge_id}, reason='{reason[:80]}')"
            )
            return knowledge_id

        except Exception as e:
            await session.rollback()
            # 핸들러 안에서 또 죽어도 raise하지 않음 — 연쇄 실패 방지.
            logger.error(f"[Error] mark_failed 실패: {e}")
            return None
