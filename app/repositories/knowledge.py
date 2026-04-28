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
    YoutubeMetadata
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

            # 3. 청크만 여러 개 저장
            for chunk_data in chunks:
                if not chunk_data:
                    continue

                session.add(
                    YoutubeKnowledgeChunk(
                        knowledge_id=knowledge_id,
                        chunk_order=chunk_data.get("chunk_order", 0),
                        content=chunk_data.get("content", ""),
                        start_time=chunk_data.get("start_time", 0),
                    )
                )

            await session.commit()
            logger.info(f"[Step 1] 청킹 데이터 DB 저장 완료: {len(chunks)}개")

        except Exception as e:
            await session.rollback()
            logger.error(f"[Step 1] 청킹 데이터 DB 저장 실패: {e}")
            raise   


async def create_base(video_id: str):
    async with async_session_maker() as session:
        repo = KnowledgeRepository(session)
        # DB에 PENDING 레코드 생성
        return await repo.create_initial_record(video_id)


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

