"""
Windows asyncio event loop 호환성 진단.
ProactorEventLoop(기본) vs SelectorEventLoop 둘 다 시도해서 어느 게 동작하는지 확인.
"""
import asyncio
import os
import sys
import traceback
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("DATABASE_URL")


async def try_connect(label):
    import asyncpg
    print(f"  [{label}] asyncpg.connect 시도...")
    try:
        c = await asyncpg.connect(url, timeout=5)
        v = await c.fetchval("SELECT 1")
        print(f"  ✅ [{label}] 성공! SELECT 1 = {v}")
        await c.close()
        return True
    except Exception:
        print(f"  ❌ [{label}] 실패:")
        traceback.print_exc()
        return False


# ──────────────────────────────────────────
# Test 1: 기본 ProactorEventLoop (지금 깨지는 그 환경)
# ──────────────────────────────────────────
print("\n" + "=" * 60)
print("Test 1: 기본 이벤트 루프 (ProactorEventLoop)")
print("=" * 60)
print(f"플랫폼: {sys.platform}, Python: {sys.version.split()[0]}")

ok1 = asyncio.run(try_connect("Proactor"))


# ──────────────────────────────────────────
# Test 2: SelectorEventLoop 강제 적용
# ──────────────────────────────────────────
print("\n" + "=" * 60)
print("Test 2: WindowsSelectorEventLoopPolicy 강제")
print("=" * 60)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    print(f"  적용된 정책: {type(asyncio.get_event_loop_policy()).__name__}")

ok2 = asyncio.run(try_connect("Selector"))


# ──────────────────────────────────────────
# 결론
# ──────────────────────────────────────────
print("\n" + "=" * 60)
print(f"Proactor : {'✅' if ok1 else '❌'}")
print(f"Selector : {'✅' if ok2 else '❌'}")
print("=" * 60)
if ok2 and not ok1:
    print("→ 확정: asyncpg + Windows ProactorEventLoop 호환성 문제")
    print("→ database.py 맨 위에 SelectorEventLoopPolicy 강제 적용하면 해결")
elif ok1 and ok2:
    print("→ 둘 다 OK — 현재 환경에선 문제없음. 다른 원인이 있을 수 있음")
elif not ok1 and not ok2:
    print("→ 둘 다 실패 — 더 근본적 문제 (방화벽/SSL/pg_hba)")
