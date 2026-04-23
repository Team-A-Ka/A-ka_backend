"""
[데이터베이스 연결 모듈]
동기(Sync) 및 비동기(Async) 세션을 모두 제공합니다.
- 동기 세션: Alembic 마이그레이션, 일반 ORM 작업에 사용
- 비동기 세션: Celery 워커 내부의 고성능 비동기 DB 작업에 사용
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

# 환경 변수 로드
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# ==========================================
# 동기(Sync) 데이터베이스 연결
# ==========================================
# DB 엔진 생성
engine = create_engine(DATABASE_URL, echo=True)

# 세션 생성기 정의
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# SQLAlchemy 2.0 스타일의 Base 클래스 선언
class Base(DeclarativeBase):
    pass


# DB 세션 의존성 주입 함수 (동기)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==========================================
# 비동기(Async) 데이터베이스 연결
# ==========================================
# asyncpg 연동을 위한 SQLAlchemy URL 구성
ASYNC_DATABASE_URL = (
    f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)

# 비동기 엔진 생성
async_engine = create_async_engine(ASYNC_DATABASE_URL, echo=False)

# 비동기 세션 메이커
# 세션 커밋 후에도 객체 상태를 유지(expire_on_commit=False)하여 Lazy-loading 오류를 대비합니다.
async_session_maker = async_sessionmaker(
    async_engine, class_=AsyncSession, expire_on_commit=False
)

async def get_async_db():
    """
    FastAPI의 Depends()를 통해 주입될 비동기 데이터베이스 세션 제너레이터입니다.
    라우터 종료 시 안전하게 DB 연결을 반환(yield 후 자동 컨텍스트 종료)합니다.
    """
    async with async_session_maker() as session:
        yield session
