"""
[Knowledge 및 파생 모델 모듈]
AI가 참조할 RDB 데이터 원문과 임베딩(Vector) 청크를 보관합니다.
(💡 pgvector 및 하이브리드 RAG 검색의 핵심 모듈)
"""
import enum
from sqlalchemy import Column, String, text, DateTime, func, ForeignKey, Integer, Enum, Float, Text
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector
from app.models.base import Base

class SourceEnum(str, enum.Enum):
    """입력 소스의 유형을 식별하는 Enum (문서, 유튜브, 인스타 등)"""
    FILE = "FILE"
    YOUTUBE = "YOUTUBE"
    INSTAGRAM = "INSTAGRAM"

class StatusEnum(str, enum.Enum):
    """데이터의 처리 상태를 관리하는 Enum (LangGraph 등에서 상태 트래킹)"""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class Knowledge(Base):
    """
    외부에서 긁어온 원본 데이터(유튜브 링크 등)의 '전체 기준 문서' 정보를 담당합니다.
    """
    __tablename__ = "knowledge"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    category_id = Column(UUID(as_uuid=True), ForeignKey("category.id"))
    source_type = Column(Enum(SourceEnum, name="source_enum"))
    title = Column(String(255))
    original_url = Column(Text)
    status = Column(Enum(StatusEnum, name="status_enum"), server_default=text("'PENDING'"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    summary = Column(Text)
    hit_count = Column(Integer, server_default=text("1"))

class YoutubeMetadata(Base):
    """
    원본 소스가 '유튜브'일 때 추가적으로 저장되는 메타데이터 테이블입니다.
    """
    __tablename__ = "youtube_metadata"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    knowledge_id = Column(UUID(as_uuid=True), ForeignKey("knowledge.id"), unique=True)
    video_id = Column(String(50))
    video_title = Column(String(50))
    channel_name = Column(String(100))
    duration = Column(Integer, comment="초 단위 재생 시간")

class KnowledgeChunk(Base):
    """
    타 그룹에서 가공(Chunking)해 보낸 조각 단위 데이터가 입력되는 테이블입니다.
    pgvector의 Vector 타입을 사용하여 OpenAI 임베딩 수치를 RDB에 함께 보관합니다.
    """
    __tablename__ = "knowledge_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    knowledge_id = Column(UUID(as_uuid=True), ForeignKey("knowledge.id"))
    content = Column(Text)
    
    # Vector(1536): OpenAI의 `text-embedding-3-small` 임베딩 차원에 맞춘 전용 컬럼
    # Alembic에서 이 컬럼을 인식하려면 사전에 DB 확장에 'vector'가 설치되어 있어야 합니다. (upgrade() 최상단에 CREATE EXTENSION 필요)
    embedding = Column(Vector(1536), comment="OpenAI text-embedding-3-small 벡터 데이터")
    
    start_timestamp = Column(Float, comment="유튜브 자막 시작 시간")
    chunk_order = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    summary_detail = Column(Text)
