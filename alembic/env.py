"""
[Alembic 마이그레이션 환경 모듈]
데이터베이스 스키마 변화를 추적하고, 동기/비동기 환경에 맞춰 DB에 쿼리를 쏴주는 Alembic 설정 파트입니다.
저희의 프로젝트는 비동기 기반(asyncpg) 이므로, 비동기 엔진 연동이 핵심입니다.
"""
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# 1. 애플리케이션 설정 및 스키마 메타데이터 로드
# 모델 변경 사항(UserInterest, KnowledgeChunk 등)을 Alembic이 감지하게끔 Base.metadata를 연결합니다.
from app.core.config import settings
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# 2. asyncpg 연결을 위한 DATABASE_URL 동적 할당
# 마이그레이션을 돌릴 때도 애플리케이션의 .env 세팅을 그대로 재활용하여 안전성을 높입니다.
DATABASE_URL = (
    f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)
config.set_main_option("sqlalchemy.url", DATABASE_URL)

def run_migrations_offline() -> None:
    """
    [오프라인 마이그레이션 모드]
    DB 커넥션을 맺지 않고(SQL을 터미널에 출력만 함) 마이그레이션 스크립트를 생성할 때 사용됩니다.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True, # 쿼리를 문자열 그대로 출력하기 위함
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """
    [동기 브릿지 함수]
    아래 비동기 환경 내에서 불러오기 위해 순수 동기 방식 인터페이스를 껍데기로 제공합니다.
    """
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    [비동기(Online) 마이그레이션 핵심 로직]
    SQLAlchemy의 비동기 엔진(async_engine_from_config)을 사용하여 DB와 직접 커넥션을 맺습니다.
    (주의: asyncpg 드라이버가 필수입니다)
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        # 비동기 연결 객체를 동기 함수인 do_run_migrations로 감싸 실행합니다.
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """
    [온라인 마이그레이션 모드 (실제 DB 반영)]
    명령어 실행 시 진입점이 되며, 파이썬의 기본 asyncio.run()으로 비동기 루프를 띄웁니다.
    """
    asyncio.run(run_async_migrations())


# Alembic 동작 환경 구분에 따른 엔트리 분기점
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
