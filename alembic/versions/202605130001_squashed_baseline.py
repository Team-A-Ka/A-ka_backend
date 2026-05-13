"""squashed baseline — full schema with naming_convention

기존 8개 마이그레이션을 단일 파일로 통합.
새 환경: alembic upgrade head 로 전체 스키마 생성.
기존 환경: alembic stamp 202605130001 으로 버전만 갱신.

통합된 마이그레이션 목록:
  a9886e977674  init (baseline tables)
  fa51fd3fd00c  user_channel_identity + user 변경
  45c4ac899d96  youtube_knowledge_chunk.embedding 추가
  b8c3e4a7d2f1  notion_connection
  d2f4c8a9b1e7  notion 중복 방지 인덱스
  8f7cfbed1a19  merge
  e4b1c7d9a2f3  notion summary DB 컬럼
  c1a8e3b6d5f4  HNSW 인덱스

Revision ID: 202605130001
Revises:
Create Date: 2026-05-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
import pgvector
from sqlalchemy.dialects.postgresql import UUID
from alembic import op


revision: str = "202605130001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Extensions ────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── Enum 타입 ─────────────────────────────────────────────
    sourcetype = sa.Enum("YOUTUBE", "INSTAGRAM", "FILE", name="sourcetype")
    processstatus = sa.Enum("PENDING", "COMPLETED", "FAILED", name="processstatus")
    sourcetype.create(op.get_bind(), checkfirst=True)
    processstatus.create(op.get_bind(), checkfirst=True)

    # ── 1. category ───────────────────────────────────────────
    op.create_table(
        "category",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_category"),
        sa.UniqueConstraint("name", name="uq_category_name"),
    )

    # ── 2. user ───────────────────────────────────────────────
    op.create_table(
        "user",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_name", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_user"),
        sa.UniqueConstraint("user_name", name="uq_user_user_name"),
    )

    # ── 3. user_channel_identity ──────────────────────────────
    op.create_table(
        "user_channel_identity",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"],
            name="fk_user_channel_identity_user_id_user",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_channel_identity"),
        # 커스텀 이름 유지 (기존 데이터 호환)
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_provider_user"),
    )
    op.create_index(
        "ix_user_channel_identity_user_id",
        "user_channel_identity",
        ["user_id"],
        unique=False,
    )

    # ── 4. knowledge ──────────────────────────────────────────
    op.create_table(
        "knowledge",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "source_type",
            sa.Enum("YOUTUBE", "INSTAGRAM", "FILE", name="sourcetype"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("original_url", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "COMPLETED", "FAILED", name="processstatus"),
            nullable=True,
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"], ["category.id"],
            name="fk_knowledge_category_id_category",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"],
            name="fk_knowledge_user_id_user",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge"),
    )

    # ── 5. youtube_metadata ───────────────────────────────────
    op.create_table(
        "youtube_metadata",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_id", UUID(as_uuid=True), nullable=False),
        sa.Column("video_id", sa.String(length=50), nullable=False),
        sa.Column("video_title", sa.String(length=255), nullable=False),
        sa.Column("channel_name", sa.String(length=50), nullable=False),
        sa.Column("duration", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["knowledge_id"], ["knowledge.id"],
            name="fk_youtube_metadata_knowledge_id_knowledge",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_youtube_metadata"),
        sa.UniqueConstraint("knowledge_id", name="uq_youtube_metadata_knowledge_id"),
    )

    # ── 6. youtube_knowledge_chunk ────────────────────────────
    op.create_table(
        "youtube_knowledge_chunk",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_id", UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary_detail", sa.Text(), nullable=True),
        sa.Column("start_time", sa.BigInteger(), nullable=False),
        sa.Column("chunk_order", sa.Integer(), nullable=False),
        sa.Column(
            "embedding",
            pgvector.sqlalchemy.vector.VECTOR(dim=1536),
            nullable=True,
        ),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["knowledge_id"], ["knowledge.id"],
            name="fk_youtube_knowledge_chunk_knowledge_id_knowledge",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_youtube_knowledge_chunk"),
    )

    # ── 7. notion_connection ──────────────────────────────────
    op.create_table(
        "notion_connection",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_id", sa.String(length=100), nullable=False),
        sa.Column("workspace_name", sa.String(length=255), nullable=True),
        sa.Column("workspace_icon", sa.String(length=1000), nullable=True),
        sa.Column("bot_id", sa.String(length=100), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("parent_page_id", sa.String(length=50), nullable=True),
        sa.Column("summary_database_id", sa.String(length=50), nullable=True),
        sa.Column("summary_data_source_id", sa.String(length=50), nullable=True),
        sa.Column("duplicated_template_id", sa.String(length=50), nullable=True),
        sa.Column("owner_type", sa.String(length=50), nullable=True),
        sa.Column("owner_user_id", sa.String(length=100), nullable=True),
        sa.Column("owner_user_email", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"],
            name="fk_notion_connection_user_id_user",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notion_connection"),
        # 커스텀 이름 유지 (기존 데이터 호환)
        sa.UniqueConstraint("user_id", name="uq_notion_connection_user_id"),
    )
    op.create_index(
        "ix_notion_connection_user_id",
        "notion_connection",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "uq_notion_connection_workspace_owner_user_id",
        "notion_connection",
        ["workspace_id", "owner_user_id"],
        unique=True,
        postgresql_where=sa.text("owner_user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_notion_connection_workspace_owner_email_without_user_id",
        "notion_connection",
        ["workspace_id", sa.text("lower(owner_user_email)")],
        unique=True,
        postgresql_where=sa.text(
            "owner_user_id IS NULL AND owner_user_email IS NOT NULL"
        ),
    )

    # ── HNSW 인덱스 (CONCURRENTLY → autocommit 필요) ──────────
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_youtube_knowledge_chunk_embedding "
            "ON youtube_knowledge_chunk USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_youtube_knowledge_chunk_embedding"
        )

    op.drop_index("uq_notion_connection_workspace_owner_email_without_user_id", table_name="notion_connection")
    op.drop_index("uq_notion_connection_workspace_owner_user_id", table_name="notion_connection")
    op.drop_index("ix_notion_connection_user_id", table_name="notion_connection")
    op.drop_table("notion_connection")
    op.drop_table("youtube_knowledge_chunk")
    op.drop_table("youtube_metadata")
    op.drop_table("knowledge")
    op.drop_index("ix_user_channel_identity_user_id", table_name="user_channel_identity")
    op.drop_table("user_channel_identity")
    op.drop_table("user")
    op.drop_table("category")

    sa.Enum(name="processstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="sourcetype").drop(op.get_bind(), checkfirst=True)
