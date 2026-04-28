import uuid
import logging
import asyncio
from datetime import datetime
from sqlalchemy import select         
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

