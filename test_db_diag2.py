"""
DB 진단 2단계 — DB 자체 존재 여부 + aka_db 접속 분리 검증.
실행: python test_db_diag2.py
"""
import asyncio
import os
import traceback
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("DATABASE_URL")

# 비번 마스킹용
def mask(u):
    if "@" not in u or ":" not in u.split("@")[0]:
        return u
    head, tail = u.rsplit("@", 1)
    user_part, _ = head.rsplit(":", 1)
    return f"{user_part}:***@{tail}"


async def diag():
    import asyncpg

    # ──────────────────────────────────────────
    # [A] 시스템 DB(postgres)로 접속 — aka_db 유무와 무관하게 서버 응답 확인
    # ──────────────────────────────────────────
    sys_url = url.rsplit("/", 1)[0] + "/postgres"
    print(f"[A] 시스템 DB(postgres) 접속 시도")
    print(f"    URL: {mask(sys_url)}")
    try:
        c = await asyncpg.connect(sys_url, timeout=5)
        v = await c.fetchval("SELECT version()")
        print(f"    ✅ Postgres 응답: {v[:70]}...")
        rows = await c.fetch("SELECT datname FROM pg_database ORDER BY 1")
        db_list = [r["datname"] for r in rows]
        print(f"    ✅ 존재하는 DB: {db_list}")
        await c.close()

        if "aka_db" not in db_list:
            print(f"\n    ❌ 'aka_db' 가 DB 목록에 없음 → 생성 필요")
            return
        else:
            print(f"    ✅ aka_db 존재 확인")
    except Exception:
        print(f"    ❌ 시스템 DB 접속도 실패:")
        traceback.print_exc()
        return

    # ──────────────────────────────────────────
    # [B] 실제 aka_db 접속
    # ──────────────────────────────────────────
    print(f"\n[B] aka_db 접속 시도")
    print(f"    URL: {mask(url)}")
    try:
        c = await asyncpg.connect(url, timeout=5)
        print(f"    ✅ connect 성공")
        v = await c.fetchval("SELECT 1")
        print(f"    ✅ SELECT 1 = {v}")

        # 추가 — user 테이블 상태
        try:
            cnt = await c.fetchval('SELECT COUNT(*) FROM "user"')
            print(f"    ✅ user 테이블 row 수: {cnt}")
            if cnt > 0:
                u1 = await c.fetchrow('SELECT id, user_name FROM "user" ORDER BY id LIMIT 1')
                print(f"    ✅ 첫 user: {dict(u1)}")
        except Exception as e:
            print(f"    ⚠️ user 테이블 조회 실패: {type(e).__name__}: {e}")
            print(f"       → alembic upgrade head 미실행 가능성")

        await c.close()
    except Exception:
        print(f"    ❌ aka_db 접속 실패:")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(diag())
