"""
[User 및 UserInterest 모델 모듈]
사용자 정보와 사용자의 관심사 매핑 정보를 관리합니다.
"""
import uuid
from sqlalchemy import Column, String, text, DateTime, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.models.base import Base

class User(Base):
    """
    유저의 기본 정보와 AI의 문맥 파악 시(LLM 추론) 활용할 상태 정보(context)를 관리합니다.
    """
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_name = Column(String(100), nullable=True)
    
    # JSONB: NoSQL처럼 유동적인 데이터를 삽입/조회할 수 있는 고성능 컬럼 타입입니다.
    user_context = Column(JSONB, server_default=text("'{}'::jsonb"), comment="LLM 추론용 유동적 데이터")
    
    # func.now(), onupdate: 데이터 생성 시각은 물론 수정(update) 시에도 자동으로 현재 시간이 갱신(스탬프)됩니다.
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class UserInterest(Base):
    """
    유저와 관심 카테고리를 N:M 스키마처럼 이어주는 조인(중간) 테이블 역할의 모델입니다.
    """
    __tablename__ = "user_interest"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    
    # users 및 category 테이블의 id를 바라보는 외래키(ForeignKey) 설정
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    category_id = Column(UUID(as_uuid=True), ForeignKey("category.id"))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
