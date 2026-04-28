"""
asyncpg vs psycopg2 비교 + SSL 옵션 명시 + pg_hba 진단.
실행: python test_db_diag4.py
"""
import asyncio
import os
import sys
import traceback
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("DATABASE_URL")
sync_url = url.replace("postgresql+asyncpg://", "postgresql://")


def banner(t):
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)


# ──────────────────────────────────────────
# Test 1: psycopg2 (동기 드라이버)
# ──────────────────────────────────────────
banner("Test 1: psycopg2 (동기) — asyncpg와 무관한 별도 드라이버")
ok1 = False
try:
    import psycopg2
    conn = psycopg2.connect(sync_url, connect_timeout=5)
    cur = conn.cursor()
    cur.execute("SELECT version()")
    print(f"  ✅ {cur.fetchone()[0][:80]}")
    cur.close()
    conn.close()
    ok1 = True
except ImportError:
    print("  ⚠️ psycopg2 미설치 — 건너뜀")
except Exception:
    traceback.print_exc()


# ──────────────────────────────────────────
# Test 2: asyncpg + ssl='disable' 명시
# ──────────────────────────────────────────
banner("Test 2: asyncpg + ssl=disable 강제")

async def disable_ssl():
    import asyncpg
    try:
        c = await asyncpg.connect(url, ssl=False, timeout=5)
        v = await c.fetchval("SELECT 1")
        print(f"  ✅ ssl=False 성공: {v}")
        await c.close()
        return True
    except Exception:
        traceback.print_exc()
        return False

ok2 = asyncio.run(disable_ssl())


# ──────────────────────────────────────────
# Test 3: asyncpg + ssl='require'
# ──────────────────────────────────────────
banner("Test 3: asyncpg + ssl=require 강제")

async def require_ssl():
    import asyncpg
    try:
        c = await asyncpg.connect(url, ssl="require", timeout=5)
        v = await c.fetchval("SELECT 1")
        print(f"  ✅ ssl=require 성공: {v}")
        await c.close()
        return True
    except Exception:
        traceback.print_exc()
        return False

ok3 = asyncio.run(require_ssl())


# ──────────────────────────────────────────
# Test 4: asyncpg 인자 풀어서 — host/port/db/user/password 분리
# ──────────────────────────────────────────
banner("Test 4: asyncpg 인자 풀어서 명시")

from urllib.parse import urlparse
p = urlparse(sync_url)

async def explicit_args():
    import asyncpg
    try:
        c = await asyncpg.connect(
            host=p.hostname,
            port=p.port or 5432,
            user=p.username,
            password=p.password,
            database=p.path.lstrip("/"),
            timeout=5,
            ssl=False,
        )
        v = await c.fetchval("SELECT 1")
        print(f"  ✅ 명시 인자 성공: {v}")
        await c.close()
        return True
    except Exception:
        traceback.print_exc()
        return False

ok4 = asyncio.run(explicit_args())


# ──────────────────────────────────────────
# 결론
# ──────────────────────────────────────────
banner("Summary")
print(f"  psycopg2(동기)        : {'✅' if ok1 else '❌'}")
print(f"  asyncpg ssl=disable   : {'✅' if ok2 else '❌'}")
print(f"  asyncpg ssl=require   : {'✅' if ok3 else '❌'}")
print(f"  asyncpg 명시 인자     : {'✅' if ok4 else '❌'}")
print()

if ok1 and not (ok2 or ok3 or ok4):
    print("→ psycopg2는 OK, asyncpg 전부 ❌")
    print("  asyncpg + Windows + 본인 Postgres 조합 호환성 문제")
    print("  대안: SQLAlchemy를 psycopg(동기) 또는 psycopg(async v3)로 갈아끼기")
elif not ok1:
    print("→ psycopg2도 ❌ — 서버 측 문제 (pg_hba/SSL/방화벽)")
    print("  PostgreSQL 데이터 폴더의 log/postgresql-*.log 마지막 50줄 확인 필요")
elif ok2 or ok3:
    print("→ ssl 옵션이 결정타였음 — DATABASE_URL에 ssl 파라미터 추가 또는 connect_args 수정")
