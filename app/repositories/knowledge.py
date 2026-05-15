import logging
import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.category import Category
from app.models.knowledge import (
    Knowledge,
    ProcessStatus,
    SourceType,
    YoutubeKnowledgeChunk,
    YoutubeMetadata,
)
from database import async_session_maker

logger = logging.getLogger("aka.db")


class KnowledgeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create_category(self, category_name: str | None) -> Category:
        name = normalize_category_name(category_name)
        result = await self.session.execute(
            select(Category).where(Category.name == name)
        )
        category = result.scalars().first()
        if category is not None:
            return category

        category = Category(name=name)
        self.session.add(category)
        await self.session.flush()
        return category

    async def create_initial_record(self, video_id: str, user_id: int):
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
                category_id=None,
                hit_count=1,
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

            logger.info(
                f"Initial knowledge record created: knowledge_id={knowledge_id}"
            )
            return knowledge_id
        except Exception as exc:
            await self.session.rollback()
            logger.error(f"Failed to create initial knowledge record: {exc}")
            raise

    async def find_by_user_and_video_id(self, user_id: int, video_id: str):
        result = await self.session.execute(
            select(Knowledge)
            .join(
                YoutubeMetadata,
                YoutubeMetadata.knowledge_id == Knowledge.id,
            )
            .where(
                Knowledge.user_id == user_id,
                YoutubeMetadata.video_id == video_id,
            )
            .options(selectinload(Knowledge.category))
            .order_by(Knowledge.created_at.desc())
            .limit(1)
        )

        return result.scalars().first()

    async def increase_hit_count(self, knowledge: Knowledge):
        knowledge.hit_count = (knowledge.hit_count or 0) + 1
        knowledge.updated_at = datetime.utcnow()

        self.session.add(knowledge)

        await self.session.commit()
        await self.session.refresh(knowledge)

        return knowledge


async def save_chunks_to_db(video_id: str, metadata: dict, chunks: list):
    async with async_session_maker() as session:
        try:
            result = await session.execute(
                select(Knowledge.id)
                .join(YoutubeMetadata, YoutubeMetadata.knowledge_id == Knowledge.id)
                .where(YoutubeMetadata.video_id == video_id)
                .order_by(Knowledge.created_at.desc())
                .limit(1)
            )
            knowledge_id = result.scalars().first()
            if knowledge_id is None:
                raise Exception(f"No Knowledge record found for video_id={video_id}.")

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

            saved_objects = []
            for chunk_data in chunks:
                if not chunk_data:
                    continue

                chunk = YoutubeKnowledgeChunk(
                    knowledge_id=knowledge_id,
                    chunk_order=chunk_data.get("chunk_order", 0),
                    content=chunk_data.get("content", ""),
                    start_time=chunk_data.get("start_time", 0),
                )
                session.add(chunk)
                saved_objects.append(chunk)

            await session.commit()
            logger.info(f"[Step 1] Saved {len(saved_objects)} chunks to DB")

            return [
                {
                    "id": chunk.id,
                    "chunk_order": chunk.chunk_order,
                    "content": chunk.content,
                    "start_time": chunk.start_time,
                }
                for chunk in saved_objects
            ]
        except Exception as exc:
            await session.rollback()
            logger.error(f"[Step 1] Failed to save chunks to DB: {exc}")
            raise


async def create_base(video_id: str, user_id: int):
    async with async_session_maker() as session:
        repo = KnowledgeRepository(session)
        return await repo.create_initial_record(video_id, user_id)


def normalize_category_name(category_name: str | None) -> str:
    name = (category_name or "").strip().replace(" ", "")
    return name[:50] or "미분류"


async def list_category_names() -> list[str]:
    async with async_session_maker() as session:
        result = await session.execute(select(Category.name).order_by(Category.name))
        return list(result.scalars().all())


async def update_summary_result_to_db(
    video_id: str,
    title: str,
    summary: str,
    category_name: str | None,
) -> dict:
    async with async_session_maker() as session:
        try:
            repo = KnowledgeRepository(session)
            result = await session.execute(
                select(Knowledge)
                .join(YoutubeMetadata, YoutubeMetadata.knowledge_id == Knowledge.id)
                .where(YoutubeMetadata.video_id == video_id)
                .order_by(Knowledge.created_at.desc())
                .limit(1)
            )
            knowledge = result.scalars().first()
            if knowledge is None:
                raise Exception(f"No Knowledge record found for video_id={video_id}.")

            category = await repo.get_or_create_category(category_name)
            knowledge.title = (title or knowledge.title)[:255]
            knowledge.summary = summary or ""
            knowledge.category_id = category.id
            knowledge.status = ProcessStatus.COMPLETED
            knowledge.updated_at = datetime.utcnow()

            await session.commit()
            return {
                "knowledge_id": str(knowledge.id),
                "category_id": category.id,
                "category_name": category.name,
                "hit_count": knowledge.hit_count,
            }
        except Exception:
            await session.rollback()
            raise


async def _update_chunk_embeddings(result_chunks: list):
    async with async_session_maker() as session:
        async with session.begin():
            for chunk_data in result_chunks:
                if "id" not in chunk_data or "embedding" not in chunk_data:
                    continue
                await session.execute(
                    update(YoutubeKnowledgeChunk)
                    .where(YoutubeKnowledgeChunk.id == chunk_data["id"])
                    .values(embedding=chunk_data["embedding"])
                )
        await session.commit()


async def update_knowledge_after_langgraph(
    video_id: str,
    title: str,
    summary: str,
    summarized_chunks: list,
):
    async with async_session_maker() as session:
        try:
            result = await session.execute(
                select(Knowledge.id)
                .join(YoutubeMetadata, YoutubeMetadata.knowledge_id == Knowledge.id)
                .where(YoutubeMetadata.video_id == video_id)
                .order_by(Knowledge.created_at.desc())
                .limit(1)
            )
            knowledge_id = result.scalars().first()
            if knowledge_id is None:
                raise Exception(f"No Knowledge record found for video_id={video_id}.")

            await session.execute(
                update(Knowledge)
                .where(Knowledge.id == knowledge_id)
                .values(title=title[:255], summary=summary)
            )

            for chunk in summarized_chunks:
                order = chunk.get("chunk_order")
                if order is None:
                    continue
                await session.execute(
                    update(YoutubeKnowledgeChunk)
                    .where(
                        YoutubeKnowledgeChunk.knowledge_id == knowledge_id,
                        YoutubeKnowledgeChunk.chunk_order == order,
                    )
                    .values(summary_detail=chunk.get("summary", ""))
                )

            await session.commit()
            logger.info(
                f"[Step 2] Knowledge updated: knowledge_id={knowledge_id}, "
                f"chunks={len(summarized_chunks)}"
            )
            return knowledge_id
        except Exception as exc:
            await session.rollback()
            logger.error(f"[Step 2] Failed to update LangGraph result: {exc}")
            raise


async def save_link_only(
    video_id: str,
    metadata: dict,
    user_id: int,
    category_name: str = "미분류",
):
    knowledge_id = uuid.uuid4()

    async with async_session_maker() as session:
        try:
            name = (category_name or "미분류").strip().replace(" ", "")[:50]
                        
            stmt = select(Category).where(
                Category.name == name
            )
            result = await session.execute(stmt)
            category = result.scalars().first()

            if not category:
                try:
                    category = Category(name=name)
                    session.add(category)
                    await session.flush()  # 새 카테고리 ID 발급
                except IntegrityError:
                    await session.rollback()
                    result = await session.execute(stmt)
                    category = result.scalars().first()

            knowledge = Knowledge(
                id=knowledge_id,
                user_id=user_id,
                title=metadata.get("video_title", f"영상 {video_id}")[:255],
                summary=None,
                original_url=f"https://www.youtube.com/watch?v={video_id}",
                source_type=SourceType.YOUTUBE,
                status=ProcessStatus.COMPLETED,
                category_id=category.id,
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
                f"[SAVE_ONLY] Saved Knowledge+YoutubeMetadata with '미분류' category: "
                f"knowledge_id={knowledge_id}, video_id={video_id}"
            )
            return knowledge_id
        except Exception as exc:
            await session.rollback()
            logger.error(f"[SAVE_ONLY] Failed to save link only: {exc}")
            raise


async def mark_completed(video_id: str):
    async with async_session_maker() as session:
        try:
            result = await session.execute(
                select(Knowledge.id)
                .join(YoutubeMetadata, YoutubeMetadata.knowledge_id == Knowledge.id)
                .where(YoutubeMetadata.video_id == video_id)
                .order_by(Knowledge.created_at.desc())
                .limit(1)
            )
            knowledge_id = result.scalars().first()
            if knowledge_id is None:
                logger.warning(f"[Step 3] No Knowledge record for video_id={video_id}")
                return None

            await session.execute(
                update(Knowledge)
                .where(Knowledge.id == knowledge_id)
                .values(status=ProcessStatus.COMPLETED)
            )
            await session.commit()
            return knowledge_id
        except Exception as exc:
            await session.rollback()
            logger.error(f"[Step 3] Failed to mark completed: {exc}")
            raise


async def mark_failed(video_id: str, reason: str = ""):
    async with async_session_maker() as session:
        try:
            result = await session.execute(
                select(Knowledge.id)
                .join(YoutubeMetadata, YoutubeMetadata.knowledge_id == Knowledge.id)
                .where(YoutubeMetadata.video_id == video_id)
                .order_by(Knowledge.created_at.desc())
                .limit(1)
            )
            knowledge_id = result.scalars().first()
            if knowledge_id is None:
                logger.warning(f"[Error] No Knowledge record for video_id={video_id}")
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
        except Exception as exc:
            await session.rollback()
            logger.error(f"[Error] Failed to mark failed: {exc}")
            return None
