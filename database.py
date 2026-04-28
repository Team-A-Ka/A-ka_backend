"""
[데이터베이스 연결 모듈]
동기(Sync) 및 비동기(Async) 세션을 모두 제공합니다.
- 동기 세션: Alembic 마이그레이션, 일반 ORM 작업에 사용
- 비동기 세션: Celery 워커 내부의 고성능 비동기 DB 작업에 사용
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, NullPool
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


# 환경 변수 로드
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL 환경변수가 설정되어 있지 않습니다.")


# ==========================================
# DB URL 구성
# ==========================================

SYNC_DATABASE_URL = DATABASE_URL.replace(
    "postgresql+asyncpg://",
    "postgresql://",
)

ASYNC_DATABASE_URL = DATABASE_URL.replace(
    "postgresql://",
    "postgresql+asyncpg://",
)


# ==========================================
# 동기(Sync) 데이터베이스 연결
# Alembic, 일반 ORM 작업용
# ==========================================
engine = create_engine(
    SYNC_DATABASE_URL,
    echo=True,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==========================================
# 비동기(Async) 데이터베이스 연결
# Celery / async DB 작업용
# ==========================================
async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=True,
    pool_pre_ping=True,
    poolclass=NullPool,
    connect_args={
        "statement_cache_size": 0,
    },
)

async_session_maker = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_async_db():
    async with async_session_maker() as session:
        yield session