"""
[데이터베이스 연결 모듈]
SQLAlchemy 2.0의 비동기 세션을 생성하고 제공합니다.
"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

# asyncpg 연동을 위한 SQLAlchemy URL 구성
# 비동기 환경 처리를 위해 일반 postgresql:// 대신 postgresql+asyncpg:// 스키마를 사용합니다.
DATABASE_URL = (
    f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)

# 비동기 엔진 생성
# echo=False로 하여 개발 환경 콘솔이 쿼리 로그로 도배되지 않도록 제어합니다.
engine = create_async_engine(DATABASE_URL, echo=False)

# 비동기 세션 메이커
# 세션 커밋 후에도 객체 상태를 유지(expire_on_commit=False)하여 Lazy-loading 오류를 대비합니다.
async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db():
    """
    FastAPI의 Depends()를 통해 주입될 비동기 데이터베이스 세션 제너레이터입니다.
    라우터 종료 시 안전하게 DB 연결을 반환(yield 후 자동 컨텍스트 종료)합니다.
    """
    async with async_session_maker() as session:
        yield session
