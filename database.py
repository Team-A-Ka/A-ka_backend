"""
[데이터베이스 연결 모듈]
동기(Sync) 및 비동기(Async) 세션을 모두 제공합니다.
- 동기 세션: Alembic 마이그레이션, 일반 ORM 작업에 사용
- 비동기 세션: Celery 워커 내부의 고성능 비동기 DB 작업에 사용
"""

from sqlalchemy import create_engine, MetaData, NullPool
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.config import settings

# 마이그레이션 자동 생성 시 제약 이름을 일관되게 만들어주는 규칙.
# alembic autogenerate가 이 규칙을 따라 이름을 붙인다.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


# ==========================================
# DB URL 구성
# DATABASE_URL 하나만 쓰고, sync/async 드라이버는 여기서 자동 파생.
# ==========================================

DATABASE_URL = settings.database_url

# 사용자가 .env에 어떤 형태로 넣어도, 자동으로 sync/async 양쪽 URL 생성
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
    echo=settings.SQL_ECHO,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


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
    echo=settings.SQL_ECHO,
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
