"""
[기본 모델 모듈]
모든 SQLAlchemy 모델이 상속받을 Base 클래스를 정의합니다.
"""
from sqlalchemy.orm import declarative_base

# Alembic이 메타데이터를 수집하고 DB 테이블을 매핑하는 기초 클래스입니다.
Base = declarative_base()
