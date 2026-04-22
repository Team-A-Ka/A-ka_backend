"""
[Category 모델 모듈]
카테고리 정보를 담는 데이터베이스 스키마입니다.
"""
import uuid
from sqlalchemy import Column, String, text
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base

class Category(Base):
    """
    사용자가 조회/관리하는 주제나 카테고리를 저장하는 모델(테이블)입니다.
    """
    __tablename__ = "category"

    # 서버 단에서 uuid를 자동 생성하도록 text("gen_random_uuid()")를 기본값으로 위임합니다.
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(String(100), nullable=True)
