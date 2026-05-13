"""
[Alembic 환경 설정]

target_metadata: SQLAlchemy ORM의 모든 모델 메타데이터를 alembic에 노출시켜
                 autogenerate가 모델-DB 차이를 추적할 수 있게 한다.

autogenerate 정확도 옵션:
- compare_type=True              : 컬럼 타입 변경 감지 (String(50)→String(100), Integer→BigInteger 등)
- compare_server_default=True    : server_default 변경 감지 (now() 등)

pgvector:
- Vector 컬럼 타입을 alembic이 인식하도록 임포트만 해둔다. autogenerate가
  embedding 컬럼류의 타입 변경을 정상 추적하기 위함.

naming_convention:
- 도입 시 기존 자동 명명된 PK/FK와 충돌해 rename diff가 대량 발생 가능.
- 별도 작업으로 분리한다. (database.py의 Base.metadata에 적용 + 기존 제약 rename 마이그레이션 추가)
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# pgvector 타입 인식 (autogenerate가 Vector 컬럼을 정상 추적하도록 등록 목적 임포트)
import pgvector.sqlalchemy  # noqa: F401

from app import models
from database import SYNC_DATABASE_URL


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# autogenerate 대상이 될 모델 메타데이터
target_metadata = models.Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    # Alembic은 항상 동기 드라이버로만 동작 -> SYNC_DATABASE_URL("postgresql://...")
    context.configure(
        url=SYNC_DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = SYNC_DATABASE_URL

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
