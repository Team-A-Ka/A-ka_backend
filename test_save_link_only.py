"""
[#1 작업 검증용 라이브 테스트]

save_link_only_task의 두 가지 동작을 단계별로 검증:
  1) YouTube 메타데이터 추출 (get_metadata 호출 — 기존 버그였던 get_video_info 대체)
  2) DB 저장 (Knowledge + YoutubeMetadata, status=COMPLETED)

요구 환경:
  - .env 의 YOUTUBE_API_KEY, OPENAI_API_KEY (메타 추출에는 YOUTUBE_API_KEY 만 필요)
  - .env 의 DATABASE_URL + 실제 PostgreSQL 가동
  - User 테이블에 id=1 레코드 존재 (Knowledge.user_id FK)

실행:
  python test_save_link_only.py
또는 Celery 워커로:
  celery -A app.core.celery_app worker -l info
  → 다른 셸: python -c "from app.services.knowledge_pipeline import save_link_only_task; save_link_only_task.delay('3n5IpwV79Gs')"
"""

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)


# ──────────────────────────────────────────
# Phase 1: 메타데이터 추출만 검증 (DB 불필요)
# ──────────────────────────────────────────
def test_phase1_metadata_only():
    print("\n" + "=" * 60)
    print("Phase 1: get_metadata 호출 검증 (DB 불필요)")
    print("=" * 60)

    from app.services.youtube_service import YouTubeService

    yt = YouTubeService()
    video_id = "3n5IpwV79Gs"  # 기존 test_ai_router.py 에서 쓰던 동일 영상

    try:
        metadata = yt.get_metadata(video_id)
    except AttributeError as e:
        print(f"❌ AttributeError — get_metadata 미존재? {e}")
        return False
    except Exception as e:
        print(f"❌ get_metadata 실패: {e}")
        return False

    print(f"✅ 반환 dict 키: {list(metadata.keys())}")
    print(f"   video_title : {metadata.get('video_title')}")
    print(f"   channel_name: {metadata.get('channel_name')}")
    print(f"   duration(ms): {metadata.get('duration')}")

    # 키 이름 검증 — 'title' 이 아니라 'video_title' 이어야 함
    assert "video_title" in metadata, "키 이름 변경 누락 — title → video_title"
    print("✅ 'video_title' 키 존재 확인")
    return True


# ──────────────────────────────────────────
# Phase 2: DB 저장 검증 (실제 INSERT 발생)
# ──────────────────────────────────────────
def test_phase2_db_insert():
    print("\n" + "=" * 60)
    print("Phase 2: save_link_only repository 호출 검증 (DB INSERT)")
    print("=" * 60)

    from app.services.youtube_service import YouTubeService
    from app.repositories.knowledge import save_link_only

    yt = YouTubeService()
    video_id = "3n5IpwV79Gs"

    metadata = yt.get_metadata(video_id)

    try:
        knowledge_id = asyncio.run(save_link_only(video_id, metadata))
    except Exception as e:
        print(f"❌ DB 저장 실패: {type(e).__name__} — {e}")
        print("   힌트: User.id=1 존재 여부, DATABASE_URL, asyncpg 드라이버 확인")
        return False

    print(f"✅ Knowledge INSERT 성공")
    print(f"   knowledge_id : {knowledge_id}")
    print(f"   user_id      : 1 (하드코딩, #5 작업에서 매핑 예정)")
    print(f"   status       : COMPLETED")
    return True


# ──────────────────────────────────────────
# Phase 3: Celery task 본체 호출 검증 (apply / 동기)
# ──────────────────────────────────────────
def test_phase3_task_apply():
    """task.apply(args=...) 는 .delay() 와 달리 큐를 안 거치고 동기 실행.
    워커 없이 task 본체 로직만 검증할 때 사용."""
    print("\n" + "=" * 60)
    print("Phase 3: save_link_only_task.apply() (동기 실행)")
    print("=" * 60)

    # 리팩토링 후: task는 app.tasks.knowledge_tasks 로 이동
    from app.tasks.knowledge_tasks import save_link_only_task

    video_id = "3n5IpwV79Gs"

    try:
        result = save_link_only_task.apply(args=[video_id])
        # AsyncResult-like — .result 로 반환값 확인
        if result.failed():
            print(f"❌ task 실패: {result.traceback}")
            return False
        print(f"✅ task 반환: {result.result}")
        return True
    except Exception as e:
        print(f"❌ apply 호출 자체 실패: {type(e).__name__} — {e}")
        return False


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"

    results = {}

    if phase in ("all", "1"):
        results["phase1"] = test_phase1_metadata_only()

    if phase in ("all", "2"):
        results["phase2"] = test_phase2_db_insert()

    if phase in ("all", "3"):
        results["phase3"] = test_phase3_task_apply()

    print("\n" + "=" * 60)
    print("Summary:")
    for k, v in results.items():
        print(f"  {k}: {'✅ PASS' if v else '❌ FAIL'}")
    print("=" * 60)

    sys.exit(0 if all(results.values()) else 1)
