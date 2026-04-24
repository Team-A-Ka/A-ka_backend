"""
[유리님 참고용 — KnowledgeRepository 예시 구현]

이 파일은 다음 둘과 1:1로 맞도록 작성된 참고 구현이에요.
  (1) docs/유리님_구현_가이드라인.md
  (2) app/services/knowledge_pipeline.py 의 Repository 호출부

실제 배치 위치: app/repositories/knowledge.py
  → 이 파일을 그대로 복사해서 바로 돌릴 수도 있지만, 유리님이 이미 작성해 둔 스타일/검증 로직을
     최대한 유지하면서 가이드라인과 어긋나는 부분만 수정하는 걸 권장해요.

선행 조건 (가이드라인 §2 참고):
  - app/models/knowledge.py
      · YoutubeKnowledgeChunk.__tablename__ = "knowledge_chunk"
      · embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(1536), nullable=True)
  - Alembic 마이그레이션: pgvector extension + 모델 변경 반영
  - uv add pgvector
"""
import uuid
from datetime import datetime

from sqlalchemy import select, update, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import (
    Knowledge,
    YoutubeKnowledgeChunk,  # 모델 클래스명은 그대로, __tablename__만 "knowledge_chunk"로 변경
    YoutubeMetadata,
    SourceType,
    ProcessStatus,
)
from app.models.user import User, UserChannelIdentity
from app.models.category import Category


class KnowledgeRepository:
    """
    파이프라인이 호출하는 4개 공개 메서드:
      1. create_pipeline_record(payload)           → Step 1 (레코드 최초 생성)
      2. update_pipeline_result(data)              → Step 2 (AI 결과 반영)
      3. mark_completed(knowledge_id)              → Step 3 (status=COMPLETED)
      4. mark_failed_by_video(video_id, kakao_user_id)  → 에러 경로 (status=FAILED)
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    # ==========================================================
    # 1-1. create_pipeline_record
    # ==========================================================
    async def create_pipeline_record(self, payload: dict) -> uuid.UUID:
        """
        Step 1 최초 레코드 생성 — 가이드라인 §1-1 참조.

        payload:
          {
            "kakao_user_id": str,   # → user_channel_identity.provider_user_id (provider='kakao')
            "video_id": str,        # → youtube_metadata.video_id
            "original_url": str,    # → knowledge.original_url
            "metadata": {"video_title", "channel_name", "duration"},
            "chunks": [{"chunk_order", "content", "start_time"}, ...],
          }

        동작:
          1) user_channel_identity 조회, 없으면 User + UserChannelIdentity 생성
          2) Knowledge INSERT (status=PROCESSING, title=video_title 임시값)
          3) YoutubeMetadata INSERT
          4) knowledge_chunk bulk INSERT (summary_detail/embedding=NULL)
          5) 생성된 knowledge_id(UUID) 반환
        """
        kakao_user_id: str = payload["kakao_user_id"]
        video_id: str = payload["video_id"]
        original_url: str = payload["original_url"]
        metadata: dict = payload["metadata"]
        chunks: list = payload["chunks"]

        try:
            # 1) user_channel_identity 조회/생성 → user.id 확보
            user_id = await self._get_or_create_user(kakao_user_id)

            # 2) Knowledge INSERT
            new_knowledge = Knowledge(
                user_id=user_id,
                source_type=SourceType.YOUTUBE,
                title=metadata.get("video_title", "Unknown"),
                original_url=original_url,
                status=ProcessStatus.PROCESSING,
            )
            self.session.add(new_knowledge)
            await self.session.flush()  # knowledge.id 확보를 위해 flush
            knowledge_id = new_knowledge.id

            # 3) YoutubeMetadata INSERT
            self.session.add(
                YoutubeMetadata(
                    knowledge_id=knowledge_id,
                    video_id=video_id,
                    video_title=metadata.get("video_title", "Unknown"),
                    channel_name=metadata.get("channel_name", "Unknown"),
                    duration=metadata.get("duration", 0),
                )
            )

            # 4) knowledge_chunk bulk INSERT
            #    summary_detail / embedding은 Step 2에서 UPDATE되므로 여기서는 미포함(=NULL)
            if chunks:
                chunk_rows = [
                    {
                        "knowledge_id": knowledge_id,
                        "content": c["content"],
                        "start_time": c["start_time"],
                        "chunk_order": c["chunk_order"],
                    }
                    for c in chunks
                ]
                await self.session.execute(insert(YoutubeKnowledgeChunk), chunk_rows)

            await self.session.commit()
            return knowledge_id

        except Exception as e:
            await self.session.rollback()
            raise e

    # ==========================================================
    # 1-2. update_pipeline_result
    # ==========================================================
    async def update_pipeline_result(self, data: dict) -> None:
        """
        Step 2 AI 결과 반영 — 가이드라인 §1-2 참조.

        data:
          {
            "video_id": str,
            "metadata": {"video_title", "channel_name", "duration"},
            "overview": {
              "title", "summary",
              "category_name",   # ★ A안: 여기서 받아 Category 테이블 upsert 후 FK로 변환
              "source_type": "YOUTUBE",
              "original_url",
            },
            "chunks": [{"chunk_order", "content", "start_time",
                        "summary_detail", "embedding"}, ...],
          }

        ⚠️ status는 여기서 세팅하지 않아요 (mark_completed가 담당).
        """
        target_video_id = data["video_id"]
        metadata = data["metadata"]
        overview = data["overview"]
        chunks = data["chunks"]

        try:
            # 1) video_id → knowledge.id 역조회 (youtube_metadata JOIN)
            stmt = (
                select(Knowledge)
                .join(YoutubeMetadata, Knowledge.id == YoutubeMetadata.knowledge_id)
                .where(YoutubeMetadata.video_id == target_video_id)
            )
            result = await self.session.execute(stmt)
            knowledge_record = result.scalar_one_or_none()

            if not knowledge_record:
                raise Exception(
                    f"해당 video_id({target_video_id})를 가진 Knowledge 레코드가 DB에 없습니다."
                )
            knowledge_id = knowledge_record.id

            # 2) Category upsert (A안) → category_id
            category_id = await self._upsert_category(overview["category_name"])

            # 3) Knowledge UPDATE (status는 건드리지 않음)
            await self.session.execute(
                update(Knowledge)
                .where(Knowledge.id == knowledge_id)
                .values(
                    title=overview["title"],
                    summary=overview["summary"],
                    category_id=category_id,
                    source_type=SourceType(overview["source_type"]),  # "YOUTUBE" → Enum
                    original_url=overview["original_url"],
                    updated_at=datetime.utcnow(),
                )
            )

            # 4) YoutubeMetadata UPDATE
            await self.session.execute(
                update(YoutubeMetadata)
                .where(YoutubeMetadata.knowledge_id == knowledge_id)
                .values(
                    video_title=metadata["video_title"],
                    channel_name=metadata["channel_name"],
                    duration=metadata["duration"],
                )
            )

            # 5) knowledge_chunk UPDATE × N — (knowledge_id, chunk_order) 매칭
            for c in chunks:
                await self.session.execute(
                    update(YoutubeKnowledgeChunk)
                    .where(
                        YoutubeKnowledgeChunk.knowledge_id == knowledge_id,
                        YoutubeKnowledgeChunk.chunk_order == c["chunk_order"],
                    )
                    .values(
                        content=c["content"],
                        start_time=c["start_time"],
                        summary_detail=c["summary_detail"],
                        embedding=c.get("embedding"),  # None이어도 안전
                    )
                )

            await self.session.commit()

        except Exception as e:
            await self.session.rollback()
            raise e

    # ==========================================================
    # 1-3. mark_completed
    # ==========================================================
    async def mark_completed(self, knowledge_id: uuid.UUID) -> None:
        """Knowledge.status → COMPLETED — 가이드라인 §1-3"""
        try:
            await self.session.execute(
                update(Knowledge)
                .where(Knowledge.id == knowledge_id)
                .values(status=ProcessStatus.COMPLETED, updated_at=datetime.utcnow())
            )
            await self.session.commit()
        except Exception as e:
            await self.session.rollback()
            raise e

    # ==========================================================
    # 1-4. mark_failed_by_video
    # ==========================================================
    async def mark_failed_by_video(self, video_id: str, kakao_user_id: str) -> None:
        """
        에러 경로 (knowledge_id를 모르는 상태) — 가이드라인 §1-4.

        매칭 순서:
          1) user_channel_identity(provider='kakao', provider_user_id=kakao_user_id) → user_id
          2) youtube_metadata.video_id = video_id AND knowledge.user_id = user_id → knowledge.id
          3) knowledge.status = FAILED

        레코드를 못 찾으면 조용히 종료 (Step 1 INSERT 전에 실패한 케이스).
        """
        try:
            # 1) kakao_user_id → user_id
            user_stmt = select(UserChannelIdentity.user_id).where(
                UserChannelIdentity.provider == "kakao",
                UserChannelIdentity.provider_user_id == kakao_user_id,
            )
            user_id = (await self.session.execute(user_stmt)).scalar_one_or_none()
            if user_id is None:
                return  # 매핑 없음 — 조용히 종료

            # 2) (video_id, user_id) → knowledge.id
            kn_stmt = (
                select(Knowledge.id)
                .join(YoutubeMetadata, Knowledge.id == YoutubeMetadata.knowledge_id)
                .where(
                    YoutubeMetadata.video_id == video_id,
                    Knowledge.user_id == user_id,
                )
            )
            knowledge_id = (await self.session.execute(kn_stmt)).scalar_one_or_none()
            if knowledge_id is None:
                return  # 레코드 없음 — 조용히 종료

            # 3) status → FAILED
            await self.session.execute(
                update(Knowledge)
                .where(Knowledge.id == knowledge_id)
                .values(status=ProcessStatus.FAILED, updated_at=datetime.utcnow())
            )
            await self.session.commit()
        except Exception as e:
            await self.session.rollback()
            raise e

    # ==========================================================
    # 내부 헬퍼
    # ==========================================================
    async def _get_or_create_user(self, kakao_user_id: str) -> int:
        """
        user_channel_identity(provider='kakao', provider_user_id=kakao_user_id) 조회.
        없으면 user + user_channel_identity 생성 후 user.id 반환.

        user.user_name은 unique 제약이 있고 nullable=True이므로, 중복 위험을 피하기 위해
        기본적으로 None으로 둡니다. (추후 닉네임 수집 기능이 생기면 그때 채우면 됨)
        """
        stmt = select(UserChannelIdentity.user_id).where(
            UserChannelIdentity.provider == "kakao",
            UserChannelIdentity.provider_user_id == kakao_user_id,
        )
        existing_user_id = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing_user_id is not None:
            return existing_user_id

        # 신규 생성
        new_user = User(user_name=None, is_active=True)
        self.session.add(new_user)
        await self.session.flush()  # user.id 확보

        self.session.add(
            UserChannelIdentity(
                user_id=new_user.id,
                provider="kakao",
                provider_user_id=kakao_user_id,
            )
        )
        await self.session.flush()
        return new_user.id

    async def _upsert_category(self, category_name: str) -> int:
        """
        A안: category_name 문자열 → category 테이블 조회, 없으면 INSERT → id 반환.

        NOTE: category.name에 UNIQUE 제약이 이미 걸려 있습니다 (models/category.py).
              완전한 동시성 대응이 필요하면 추후 pg insert().on_conflict_do_nothing()
              + RETURNING 패턴으로 전환하면 됩니다. 현재 트래픽 수준에서는 SELECT 후
              INSERT로 충분합니다.
        """
        stmt = select(Category.id).where(Category.name == category_name)
        existing_id = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing_id is not None:
            return existing_id

        new_cat = Category(name=category_name)
        self.session.add(new_cat)
        await self.session.flush()  # id 확보
        return new_cat.id
