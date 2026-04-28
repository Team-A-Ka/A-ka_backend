"""
DB 연결 진단 스크립트.
Phase 2 실패가 (A) 내 새 코드 문제인지 (B) DB 자체 문제인지 분리하기 위해
점진적으로 더 깊은 호출을 시도.

실행: python test_db_diag.py
"""
import asyncio
import os
import sys
import logging

logging.basicConfig(level=logging.WARNING)


def step(name):
    print("\n" + "=" * 60)
    print(name)
    print("=" * 60)


# ──────────────────────────────────────────
# Step 1: .env 의 DATABASE_URL 확인
# ──────────────────────────────────────────
step("Step 1: DATABASE_URL 환경변수 확인")
from dotenv import load_dotenv
load_dotenv()
url = os.getenv("DATABASE_URL")
if not url:
    print("❌ DATABASE_URL 없음")
    sys.exit(1)
# 비밀번호 마스킹해서 출력
masked = url
if "@" in url and ":" in url.split("@")[0]:
    head, tail = url.rsplit("@", 1)
    user_part = head.rsplit(":", 1)[0]
    masked = f"{user_part}:***@{tail}"
print(f"✅ DATABASE_URL = {masked}")


# ──────────────────────────────────────────
# Step 2: asyncpg 단독 연결 (SQLAlchemy 미경유)
# ──────────────────────────────────────────
step("Step 2: asyncpg 단독 연결 테스트 (가장 원초적 검증)")

async def raw_test():
    import asyncpg
    # SQLAlchemy 형식 → asyncpg 형식 변환
    pg_url = url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql://", "postgresql://"
    )
    try:
        conn = await asyncpg.connect(pg_url)
        v = await conn.fetchval("SELECT version()")
        print(f"✅ Postgres 응답: {v[:80]}...")
        cnt = await conn.fetchval('SELECT COUNT(*) FROM "user"')
        print(f"✅ user 테이블 row 수: {cnt}")
        u1 = await conn.fetchrow('SELECT id, user_name FROM "user" WHERE id=1')
        print(f"✅ user(id=1) = {dict(u1) if u1 else 'NOT FOUND'}")
        await conn.close()
        return True
    except Exception as e:
        print(f"❌ {type(e).__name__}: {e}")
        return False

ok2 = asyncio.run(raw_test())
if not ok2:
    print("\n→ DB 자체 미가동 / DATABASE_URL 잘못됨 / 방화벽 문제")
    sys.exit(1)


# ──────────────────────────────────────────
# Step 3: SQLAlchemy async 세션 — 가장 단순 SELECT
# ──────────────────────────────────────────
step("Step 3: SQLAlchemy async 세션 SELECT")

async def sa_test():
    from database import async_session_maker
    from sqlalchemy import text
    try:
        async with async_session_maker() as session:
            res = await session.execute(text("SELECT 1"))
            print(f"✅ SELECT 1 결과: {res.scalar()}")
        return True
    except Exception as e:
        print(f"❌ {type(e).__name__}: {e}")
        return False

ok3 = asyncio.run(sa_test())


# ──────────────────────────────────────────
# Step 4: 유리님 함수 create_base() — 기존 정상 동작 확인용
# ──────────────────────────────────────────
step("Step 4: 기존 create_base() 호출 (유리님 코드)")

async def yuri_test():
    from app.repositories.knowledge import create_base
    try:
        kid = await create_base("DIAG_TEST_VID")
        print(f"✅ create_base 성공: knowledge_id={kid}")
        return True
    except Exception as e:
        print(f"❌ {type(e).__name__}: {e}")
        return False

ok4 = asyncio.run(yuri_test())


# ──────────────────────────────────────────
# Step 5: 채훈 함수 save_link_only() — Phase 2와 동일
# ──────────────────────────────────────────
step("Step 5: save_link_only() 호출 (#1 작업물)")

async def my_test():
    from app.repositories.knowledge import save_link_only
    fake_meta = {
        "video_id": "DIAG_TEST_VID2",
        "video_title": "diag test",
        "channel_name": "diag",
        "duration": 1234,
    }
    try:
        kid = await save_link_only("DIAG_TEST_VID2", fake_meta)
        print(f"✅ save_link_only 성공: knowledge_id={kid}")
        return True
    except Exception as e:
        print(f"❌ {type(e).__name__}: {e}")
        return False

ok5 = asyncio.run(my_test())


print("\n" + "=" * 60)
print(f"raw asyncpg : {'✅' if ok2 else '❌'}")
print(f"SA SELECT 1 : {'✅' if ok3 else '❌'}")
print(f"create_base : {'✅' if ok4 else '❌'} (유리님)")
print(f"save_link_only: {'✅' if ok5 else '❌'} (채훈 #1)")
print("=" * 60)
print("""
해석 가이드:
  - Step 2 ❌ : DB 자체 문제 (서버 다운, 잘못된 URL 등)
  - Step 3 ❌ : SQLAlchemy async 설정 문제 (asyncpg 드라이버 등)
  - Step 4 ❌ : 모델/스키마/유저 1번 누락 등 — 유리님 코드도 깨짐
  - Step 5 만 ❌ : 내 save_link_only 함수 자체 버그
""")
